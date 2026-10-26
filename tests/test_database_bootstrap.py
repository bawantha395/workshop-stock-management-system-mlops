"""Real PostgreSQL regression tests; CI supplies an isolated PostgreSQL 17 service."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bootstrap_database import initialise_service


@pytest.fixture
def database():
    dsn = os.environ.get('TEST_DATABASE_DSN')
    if not dsn:
        pytest.skip('TEST_DATABASE_DSN must point at an isolated PostgreSQL 16+ test server')
    token = uuid.uuid4().hex[:12]
    admin = 'bootstrap_admin_' + token
    name = 'bootstrap_test_' + token
    password = uuid.uuid4().hex
    roles = {service: service + '_' + token for service in ('inventory', 'workshop', 'vision')}
    with psycopg.connect(dsn, autocommit=True) as root:
        assert root.info.server_version >= 160000
        root.execute(sql.SQL('CREATE ROLE {} LOGIN CREATEROLE NOSUPERUSER PASSWORD {}')
                     .format(sql.Identifier(admin), sql.Literal(password)))
        root.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(admin)))
        try:
            with psycopg.connect(make_conninfo(dsn, dbname=name, user=admin, password=password),
                                 autocommit=True) as db:
                assert not db.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0]
                yield SimpleNamespace(db=db, root=root, roles=roles, admin=admin,
                                      connect=lambda role: psycopg.connect(
                                          make_conninfo(dsn, dbname=name, user=role,
                                                        password=password), autocommit=True),
                                      password=password)
        finally:
            root.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            for role in roles.values():
                root.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
            root.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(admin)))


def test_reproduces_rds_error_then_creates_isolated_service_schemas(database):
    d = database
    inventory = d.roles['inventory']
    d.db.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(inventory)))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match='must be able to SET ROLE'):
        d.db.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}')
                     .format(sql.Identifier(inventory), sql.Identifier(inventory)))
    for role in d.roles.values():
        initialise_service(d.db, role, d.password)
        owner = d.db.execute('SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s',
                             (role,)).fetchone()[0]
        assert owner == role
        assert not d.db.execute('SELECT pg_has_role(current_user,%s,%s)', (role, 'SET')).fetchone()[0]
        with d.connect(role) as app:
            assert app.execute('SELECT current_schema()').fetchone()[0] == role
            app.execute('CREATE TABLE marker (value integer)')
    with d.connect(inventory) as app:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(sql.SQL('SELECT * FROM {}.marker').format(sql.Identifier(d.roles['workshop'])))


def test_repeat_preserves_existing_application_data(database):
    d = database
    role = d.roles['inventory']
    initialise_service(d.db, role, d.password)
    with d.connect(role) as app:
        app.execute('CREATE TABLE marker (value integer)')
        app.execute('INSERT INTO marker VALUES (50)')
    initialise_service(d.db, role, d.password)
    with d.connect(role) as app:
        assert app.execute('SELECT value FROM marker').fetchall() == [(50,)]


def test_preserves_existing_grant_options(database):
    d = database
    role = d.roles['inventory']
    d.db.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    d.db.execute(sql.SQL('GRANT {} TO CURRENT_USER WITH INHERIT TRUE, SET FALSE GRANTED BY CURRENT_USER')
                 .format(sql.Identifier(role)))
    query = '''SELECT admin_option, inherit_option, set_option FROM pg_auth_members
        WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname=%s)
          AND member=(SELECT oid FROM pg_roles WHERE rolname=current_user) AND grantor=member'''
    before = d.db.execute(query, (role,)).fetchone()
    assert before == (False, True, False)
    initialise_service(d.db, role, d.password)
    assert d.db.execute(query, (role,)).fetchone() == before


def test_preserves_existing_set_membership(database):
    d = database
    role = d.roles['inventory']
    d.db.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    d.db.execute(sql.SQL('GRANT {} TO CURRENT_USER WITH SET TRUE GRANTED BY CURRENT_USER')
                 .format(sql.Identifier(role)))
    initialise_service(d.db, role, d.password)
    assert d.db.execute('SELECT pg_has_role(current_user,%s,%s)', (role, 'SET')).fetchone()[0]


def test_wrong_schema_owner_rolls_back_new_role_and_temporary_grant(database):
    d = database
    role = d.roles['inventory']
    d.db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(role)))
    with pytest.raises(RuntimeError, match='different owner'):
        initialise_service(d.db, role, d.password)
    assert d.db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone() is None
    assert d.db.execute('SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s',
                        (role,)).fetchone()[0] == d.admin

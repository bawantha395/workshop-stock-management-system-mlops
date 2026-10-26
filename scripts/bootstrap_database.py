"""Initialise service-owned schemas using the database-bootstrap Pod Identity.

Secrets stay in memory. PostgreSQL role membership needed for schema ownership
is granted only inside the service transaction and restored before commit.
"""
import json
import os

import boto3
import psycopg
from psycopg import sql


def initialise_service(db, service, password):
    """Resume partial initialisation without retaining temporary SET privileges."""
    role = sql.Identifier(service)
    with db.transaction():
        database = db.execute('SELECT current_database()').fetchone()[0]
        if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (service,)).fetchone():
            db.execute(sql.SQL('CREATE ROLE {} LOGIN').format(role))
        db.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(role, sql.Literal(password)))

        # RDS administrators are not PostgreSQL superusers. Since PostgreSQL 16,
        # CREATEROLE's automatic ADMIN membership has SET FALSE: creating a role
        # does not allow assigning schema ownership to it without this grant.
        can_set = db.execute('SELECT pg_has_role(current_user, %s, %s)', (service, 'SET')).fetchone()[0]
        previous = None
        if not can_set:
            previous = db.execute('''SELECT set_option FROM pg_auth_members
                WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname=%s)
                  AND member=(SELECT oid FROM pg_roles WHERE rolname=current_user)
                  AND grantor=member''', (service,)).fetchone()
            options = 'SET TRUE' if previous is not None else 'INHERIT FALSE, SET TRUE'
            db.execute(sql.SQL('GRANT {} TO CURRENT_USER WITH ' + options +
                               ' GRANTED BY CURRENT_USER').format(role))

        db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}').format(role, role))
        owner = db.execute('SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s',
                           (service,)).fetchone()[0]
        if owner != service:
            raise RuntimeError('Existing service schema has a different owner: ' + service)
        db.execute(sql.SQL('ALTER ROLE {} IN DATABASE {} SET search_path TO {},public')
                   .format(role, sql.Identifier(database), role))

        if not can_set:
            if previous is None:
                db.execute(sql.SQL('REVOKE {} FROM CURRENT_USER GRANTED BY CURRENT_USER').format(role))
            else:
                db.execute(sql.SQL('GRANT {} TO CURRENT_USER WITH SET FALSE GRANTED BY CURRENT_USER').format(role))
    print('Initialised service schema: ' + service, flush=True)


def main():
    client = boto3.client('secretsmanager')

    def secret(arn):
        return json.loads(client.get_secret_value(SecretId=arn)['SecretString'])

    master = secret(os.environ['MASTER_SECRET_ARN'])
    with psycopg.connect(host=os.environ['DATABASE_HOST'], dbname='stocklane',
                         user=master['username'], password=master['password'],
                         sslmode='verify-full', sslrootcert='/app/certs/rds-global-bundle.pem',
                         connect_timeout=15, autocommit=True) as db:
        db.execute('CREATE EXTENSION IF NOT EXISTS vector')
        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        for service, arn in json.loads(os.environ['DATABASE_SECRETS']).items():
            initialise_service(db, service, secret(arn)['password'])
    print('Service-owned schemas and credentials initialised. No secret values were logged.')


if __name__ == '__main__':
    main()

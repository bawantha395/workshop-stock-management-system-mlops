"""Run inside the VPC using the temporary database-bootstrap Pod Identity.
Secrets are fetched in memory and never written to logs or output files.
"""
import json,os
import boto3
import psycopg
from psycopg import sql
client=boto3.client('secretsmanager')
def secret(arn):return json.loads(client.get_secret_value(SecretId=arn)['SecretString'])
master=secret(os.environ['MASTER_SECRET_ARN'])
with psycopg.connect(host=os.environ['DATABASE_HOST'],dbname='stocklane',user=master['username'],password=master['password'],sslmode='verify-full',sslrootcert='/app/certs/rds-global-bundle.pem',autocommit=True) as db:
    db.execute('CREATE EXTENSION IF NOT EXISTS vector')
    db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    for service,arn in json.loads(os.environ['DATABASE_SECRETS']).items():
        data=secret(arn)
        if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(service,)).fetchone():db.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(service)))
        db.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(service),sql.Literal(data['password'])))
        db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}').format(sql.Identifier(service),sql.Identifier(service)))
        db.execute(sql.SQL('ALTER ROLE {} IN DATABASE stocklane SET search_path TO {},public').format(sql.Identifier(service),sql.Identifier(service)))
print('Service-owned schemas and credentials initialised. No secret values were logged.')

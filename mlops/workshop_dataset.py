"""Which confirmed-photo dataset the weekly photo training should use (self-learning loop).

The vision service exports staff-confirmed photos every Sunday to datasets/workshop/latest.json.
`next` prints that dataset when it has not been trained yet (empty otherwise), so an unchanged
dataset never starts a paid SageMaker job twice. `mark` records the dataset as trained.
"""
import argparse,json,os
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

POINTER='datasets/workshop/latest.json'
TRAINED='datasets/workshop/trained.json'


def read(s3,bucket,key):
    try:return json.loads(s3.get_object(Bucket=bucket,Key=key)['Body'].read(1024*1024))
    except ClientError as error:
        if error.response['Error']['Code'] in {'NoSuchKey','404'}:return None
        raise


def next_dataset(s3,bucket):
    latest=read(s3,bucket,POINTER)
    if not latest:return '','No confirmed-photo dataset exported yet'
    if not latest['datasetUri'].startswith('s3://'+bucket+'/datasets/'):raise ValueError('Unexpected dataset location')
    trained=read(s3,bucket,TRAINED)
    if trained and trained.get('datasetVersion')==latest['datasetVersion']:return '','This week\'s photos were already trained'
    return latest['datasetUri'],'New confirmed photos: '+str(latest['images'])+' photos of '+str(latest['items'])+' items'


def mark(s3,bucket,uri):
    latest=read(s3,bucket,POINTER) or {}
    version=latest.get('datasetVersion') if latest.get('datasetUri')==uri else uri.rstrip('/').rsplit('/',1)[-1]
    s3.put_object(Bucket=bucket,Key=TRAINED,Body=json.dumps({'datasetVersion':version,'datasetUri':uri}).encode(),ContentType='application/json')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['next','mark']);p.add_argument('--config',required=True);p.add_argument('--dataset',default='')
    a=p.parse_args();c=json.loads(Path(a.config).read_text());c=c.get('deployment',{}).get('value',c)
    s3=boto3.client('s3',region_name=c['region'])
    if a.action=='next':
        uri,reason=next_dataset(s3,c['model_bucket']);print(reason)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('uri='+uri+'\n')
    else:mark(s3,c['model_bucket'],a.dataset)

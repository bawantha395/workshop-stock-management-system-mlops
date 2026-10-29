"""Nightly forecast: read the app's exported history -> pretrained Chronos-Bolt -> back-test gate -> publish.

Runs on the GitHub runner (CPU is enough); no SageMaker job and nothing to train.
The result is a versioned JSON file in S3 that the forecast service reads.
"""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
import forecast as engine

MAX_BYTES=12*1024*1024

def read(s3,bucket,key):
    response=s3.get_object(Bucket=bucket,Key=key)
    with response['Body'] as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Artifact exceeds size limit')
    return raw

def write_report(report):
    Path('artifacts').mkdir(exist_ok=True);Path('artifacts/forecast-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return report

def execute(c,publish=False,predict=None):
    s3=boto3.client('s3',region_name=c['region'])
    if boto3.client('sts').get_caller_identity()['Account']!=c['account_id']:raise ValueError('Account mismatch')
    bucket=c['model_bucket']
    try:pointer=json.loads(read(s3,bucket,'forecast/datasets/latest.json'))
    except ClientError as error:
        if error.response['Error']['Code'] not in {'NoSuchKey','404'}:raise
        return write_report({'published':False,'status':'no_history','message':'No stock history exported yet. The app exports it every night once stock movements exist.'})
    key=pointer['key']
    if not key.startswith('forecast/datasets/') or not key.endswith('/history.json'):raise ValueError('Invalid snapshot key')
    raw=read(s3,bucket,key)
    if hashlib.sha256(raw).hexdigest()!=pointer['sha256']:raise ValueError('Snapshot checksum mismatch')
    data=json.loads(raw);engine.validate(data)
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(data['asOf'].replace('Z','+00:00'))).total_seconds()
    if not 0<=age<=7*86400:raise ValueError('The exported history is older than seven days; check the nightly export in the app')
    result=engine.forecast(data,predict or engine.load_predictor())
    encoded=json.dumps(result,allow_nan=False,separators=(',',':')).encode()
    digest=hashlib.sha256(encoded).hexdigest();release_key='forecast/releases/'+digest+'/forecast.json'
    s3.put_object(Bucket=bucket,Key=release_key,Body=encoded,ContentType='application/json')
    if publish:
        try:
            current=json.loads(read(s3,bucket,'forecast/current.json'))
            if current['historyUntil']>result['historyUntil']:raise ValueError('Refusing an older history snapshot over a newer forecast')
        except ClientError as error:
            if error.response['Error']['Code'] not in {'NoSuchKey','404'}:raise
        s3.put_object(Bucket=bucket,Key='forecast/current.json',Body=encoded,ContentType='application/json')
    counts={s:sum(p['status']==s for p in result['products']) for s in ('forecast','not_moving','unreliable','needs_more_history')}
    return write_report({'published':publish,'model':result['model']['name'],'releaseUri':'s3://'+bucket+'/'+release_key,'sha256':digest,'counts':counts,
                         'evaluations':[{'sku':p['sku'],**p['evaluation']} for p in result['products'] if 'evaluation' in p]})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--publish',action='store_true');args=p.parse_args()
    config=json.loads(Path(args.config).read_text());execute(config.get('deployment',{}).get('value',config),args.publish)

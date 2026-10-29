"""Collect current Stocklane evidence without provisioning or changing stock.

Run in AWS CloudShell. --kubernetes uses temporary kubeconfig and kubectl exec for
read-only workload checks. --probe-bedrock additionally makes one bounded model
request under Vision's actual IAM identity. It never starts SageMaker training,
approves a model, publishes/deletes a queue message, or changes infrastructure.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT=Path(__file__).resolve().parents[1]
MAX_BYTES=12*1024*1024
MISSING={'NoSuchKey','404','NotFound'}


def read_json(s3,bucket,key):
    response=s3.get_object(Bucket=bucket,Key=key)
    with response['Body'] as stream:
        raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Artifact size limit exceeded')
    return json.loads(raw)


def attempt(call):
    try:return call()
    except ClientError as error:
        return {'status':'unverified','errorCode':error.response.get('Error',{}).get('Code','Unknown')}
    except Exception as error:
        return {'status':'unverified','errorCode':type(error).__name__}


def summarize_forecast(model,now=None):
    now=now or datetime.now(timezone.utc)
    if model.get('schemaVersion')!=1 or model.get('task')!='stock_usage_forecast':
        raise ValueError('Unexpected forecast artifact')
    if model.get('syntheticData'):
        return {'status':'demo_data_not_production','productionReadiness':'synthetic demo artifact is not live workshop evidence'}
    if model.get('benchmarkOnly'):
        return {'status':'public_benchmark_not_production','productionReadiness':'external benchmark results require workshop validation'}
    counts=collections.Counter(row['status'] for row in model['products'])
    if set(counts)-{'trained_ml','weekday_baseline','insufficient_history'}:
        raise ValueError('Unexpected forecast method')
    history_until=date.fromisoformat(model['historyUntil'])
    trained_at=datetime.fromisoformat(model['trainedAt'].replace('Z','+00:00'))
    if trained_at.tzinfo is None or trained_at>now+timedelta(minutes=5):
        raise ValueError('Invalid artifact timestamp')
    age=(now.astimezone(ZoneInfo('Asia/Colombo')).date()-history_until).days
    if age<0:raise ValueError('History is in the future')
    state='ml_artifact_published' if counts['trained_ml'] else ('baseline_only' if counts['weekday_baseline'] else 'insufficient_history')
    if counts['trained_ml'] and not all((model.get('trainingJob'),model.get('modelPackageArn'),model.get('qualityGatePassed'))):
        state='invalid_ml_lineage'
    if age>7 or now-trained_at>timedelta(days=7):state='stale'
    return {'status':state,'historyUntil':model['historyUntil'],'ageDays':age,
        'counts':{name:counts[name] for name in ('trained_ml','weekday_baseline','insufficient_history')},
        'trainingJob':model.get('trainingJob'),'modelPackageArn':model.get('modelPackageArn'),
        'productionReadiness':'requires accepted evaluation, deployed version and business acceptance'}


def check_forecast(s3,c):
    try:return summarize_forecast(read_json(s3,c['model_bucket'],'forecast/current.json'))
    except ClientError as error:
        if error.response['Error']['Code'] in MISSING:return {'status':'not_published'}
        raise


def check_history(s3,c):
    try:pointer=read_json(s3,c['model_bucket'],'forecast/datasets/latest.json')
    except ClientError as error:
        if error.response['Error']['Code'] in MISSING:return {'status':'not_exported'}
        raise
    key=pointer['key']
    if not key.startswith('forecast/datasets/') or not key.endswith('/history.json'):
        raise ValueError('Unexpected history key')
    # This module imports scikit-learn only inside fit(), which is never called.
    import hashlib
    response=s3.get_object(Bucket=c['model_bucket'],Key=key)
    with response['Body'] as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=pointer['sha256']:
        raise ValueError('History checksum mismatch')
    sys.path.insert(0,str(ROOT/'mlops'))
    from forecast import eligible, validate
    data=json.loads(raw);rows=validate(data)
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(data['asOf'].replace('Z','+00:00'))).total_seconds()
    if not 0<=age<=7*86400:return {'status':'stale','products':len(rows)}
    count=sum(eligible(row) for row in rows)
    return {'status':'eligible_for_training' if count else 'needs_more_history',
        'products':len(rows),'mlEligibleProducts':count,
        'historyDays':{row['sku']:len(row['usage']) for row in rows},
        'note':'Eligibility is not a passed model evaluation. No training was started.'}


def check_registry(sm,group):
    packages=sm.list_model_packages(ModelPackageGroupName=group,SortBy='CreationTime',SortOrder='Descending',MaxResults=5)['ModelPackageSummaryList']
    versions=[]
    for p in packages:
        details=sm.describe_model_package(ModelPackageName=p['ModelPackageArn'])
        versions.append({'version':p.get('ModelPackageVersion'),'arn':p['ModelPackageArn'],
            'packageStatus':p['ModelPackageStatus'],'approval':p.get('ModelApprovalStatus'),
            'syntheticData':details.get('CustomerMetadataProperties',{}).get('syntheticData')=='true',
            'benchmarkOnly':details.get('CustomerMetadataProperties',{}).get('benchmarkOnly')=='true'})
    approved=any(not(p['syntheticData'] or p['benchmarkOnly']) and p['packageStatus']=='Completed' and p['approval']=='Approved' for p in versions)
    state='no_registered_model' if not versions else 'demo_only' if all(p['syntheticData'] for p in versions) else 'awaiting_approval_or_completion'
    if versions and all(p['benchmarkOnly'] for p in versions):state='public_benchmark_only'
    return {'status':'approved_candidate_exists' if approved else state,
        'group':group,'recentVersions':versions,'deployedVersionVerified':False}


def check_queue(sqs,cw,url,c,now=None):
    expected='https://sqs.'+c['region']+'.amazonaws.com/'+c['account_id']+'/'
    if not url.startswith(expected):raise ValueError('Queue belongs to another scope')
    attrs=sqs.get_queue_attributes(QueueUrl=url,AttributeNames=['QueueArn','ApproximateNumberOfMessages',
        'ApproximateNumberOfMessagesNotVisible','RedrivePolicy'])['Attributes']
    arn=attrs['QueueArn']
    prefix='arn:aws:sqs:'+c['region']+':'+c['account_id']+':'
    if not arn.startswith(prefix):raise ValueError('Unexpected queue ARN')
    result={'status':'configured','visible':int(attrs.get('ApproximateNumberOfMessages',0)),
        'inFlight':int(attrs.get('ApproximateNumberOfMessagesNotVisible',0)),
        'activityWindowMinutes':15,
        'note':'Queue existence and zero backlog do not prove a successful business event.'}
    redrive=json.loads(attrs.get('RedrivePolicy','{}'))
    if not redrive.get('deadLetterTargetArn','').startswith(prefix):
        result.update(status='missing_or_unverified_dlq');return result
    def dlq():
        target=sqs.get_queue_url(QueueName=redrive['deadLetterTargetArn'].split(':')[-1],QueueOwnerAWSAccountId=c['account_id'])['QueueUrl']
        a=sqs.get_queue_attributes(QueueUrl=target,AttributeNames=['ApproximateNumberOfMessages'])['Attributes']
        return {'visible':int(a.get('ApproximateNumberOfMessages',0))}
    result['deadLetters']=attempt(dlq)
    now=now or datetime.now(timezone.utc)
    def activity():
        values={}
        for name in ('NumberOfMessagesSent','NumberOfMessagesReceived','NumberOfMessagesDeleted'):
            response=cw.get_metric_statistics(Namespace='AWS/SQS',MetricName=name,
                Dimensions=[{'Name':'QueueName','Value':arn.split(':')[-1]}],StartTime=now-timedelta(minutes=15),
                EndTime=now,Period=60,Statistics=['Sum'])
            values[name]=sum(p['Sum'] for p in response['Datapoints'])
        return values
    result['activity']=attempt(activity)
    if result['deadLetters'].get('visible',0)>0:result['status']='dead_letters_present'
    elif result['visible']>0:result['status']='messages_pending'
    return result


def workload_probe(c,probe_bedrock=False,runner=subprocess.run):
    namespace=c.get('workload_namespace','stocklane-'+c['environment'])
    if not re.fullmatch(r'[a-z0-9-]+',namespace):raise ValueError('Invalid namespace')
    with tempfile.TemporaryDirectory(prefix='stocklane-readiness-') as directory:
        kubeconfig=str(Path(directory)/'kubeconfig')
        runner(['aws','eks','update-kubeconfig','--region',c['region'],'--name',c['cluster_name'],
                '--kubeconfig',kubeconfig],check=True,capture_output=True,text=True,timeout=30)
        command=['kubectl','--kubeconfig',kubeconfig,'--request-timeout=10s','-n',namespace,
                 'exec','-i','deployment/vision','-c','vision','--','python','-']
        if probe_bedrock:command.append('--probe-bedrock')
        response=runner(command,input=(ROOT/'scripts/vision_runtime_probe.py').read_text(),
            capture_output=True,text=True,timeout=55)
        if response.returncode:
            return {'status':'unverified','errorCode':'KUBERNETES_PROBE_FAILED',
                'message':'Check private API reachability, EKS access and the Vision deployment.'}
        return {'status':'collected',**json.loads(response.stdout)}


def collect(c,session,kubernetes=False,probe_bedrock=False):
    config=Config(connect_timeout=5,read_timeout=10,retries={'total_max_attempts':1})
    client=lambda name:session.client(name,region_name=c['region'],config=config)
    s3=client('s3');sm=client('sagemaker');sqs=client('sqs');cw=client('cloudwatch')
    result={'checkedAt':datetime.now(timezone.utc).isoformat(),'environment':c['environment'],
        'region':c['region'],'productionReady':False,
        'productionNote':'This report collects operational evidence; it does not certify production readiness.'}
    result['forecast']=attempt(lambda:check_forecast(s3,c))
    result['forecastHistory']=attempt(lambda:check_history(s3,c))
    result['sagemaker']={name:attempt(lambda group=c[key]:check_registry(sm,group))
        for name,key in [('photo','model_package_group'),('forecast','forecast_model_package_group')] if c.get(key)}
    result['queues']={name:attempt(lambda url=c[key]:check_queue(sqs,cw,url,c))
        for name,key in [('stock','stock_queue_url'),('catalogue','catalogue_queue_url')] if c.get(key)}
    result['workloads']=attempt(lambda:workload_probe(c,probe_bedrock)) if kubernetes else {
        'status':'not_checked','message':'Use --kubernetes to inspect the running Vision identity and model.'}
    return result


def main(args):
    if args.probe_bedrock and not args.kubernetes:
        raise ValueError('--probe-bedrock requires --kubernetes so the real Vision IAM role is tested')
    if not re.fullmatch(r'[0-9]{12}',args.expected_account):raise ValueError('Invalid expected account')
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,19}',args.project):raise ValueError('Invalid project name')
    session=boto3.Session(region_name=args.region)
    cfg=Config(connect_timeout=5,read_timeout=10,retries={'total_max_attempts':1})
    if session.client('sts',config=cfg).get_caller_identity()['Account']!=args.expected_account:
        raise ValueError('Unexpected AWS account; stopped before inspecting project resources')
    s3=session.client('s3',config=cfg)
    envelope=read_json(s3,args.project+'-automation-'+args.expected_account,'outputs/'+args.environment+'/current.json')
    c=envelope['deployment']['value']
    expected={'account_id':args.expected_account,'region':args.region,'name':args.project,'environment':args.environment}
    if any(c.get(key)!=value for key,value in expected.items()):raise ValueError('Deployment scope mismatch')
    result=collect(c,session,args.kubernetes,args.probe_bedrock)
    path=Path(args.report).expanduser();path.parent.mkdir(parents=True,exist_ok=True)
    os.umask(0o077);path.write_text(json.dumps(result,indent=2)+'\n');path.chmod(0o600)
    print(json.dumps(result,indent=2))
    print('Readiness evidence saved to '+str(path))
    print('No training, stock change, queue message send/delete or infrastructure update was executed.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--expected-account',required=True)
    parser.add_argument('--region',default='ap-southeast-2')
    parser.add_argument('--environment',choices=['dev','staging','prod'],default='dev')
    parser.add_argument('--kubernetes',action='store_true')
    parser.add_argument('--probe-bedrock',action='store_true')
    parser.add_argument('--report',default='artifacts/readiness-report.json')
    main(parser.parse_args())

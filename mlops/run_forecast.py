"""One protected workflow: snapshot preflight -> bounded SageMaker -> gate -> publish.
Insufficient history never starts a paid training job. Forecasts are batch artifacts.
"""
import argparse,hashlib,io,json,os,signal,tarfile,time
from datetime import datetime,timezone
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from forecast import validate,eligible,train

MAX_BYTES=12*1024*1024

def read(s3,bucket,key):
    response=s3.get_object(Bucket=bucket,Key=key)
    with response['Body'] as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Artifact exceeds size limit')
    return raw

def execute(c,publish=False):
    s3=boto3.client('s3',region_name=c['region']);sm=boto3.client('sagemaker',region_name=c['region'])
    if boto3.client('sts').get_caller_identity()['Account']!=c['account_id']:raise ValueError('Account mismatch')
    bucket=c['model_bucket'];pointer=json.loads(read(s3,bucket,'forecast/datasets/latest.json'));key=pointer['key']
    if not key.startswith('forecast/datasets/') or not key.endswith('/history.json'):raise ValueError('Invalid snapshot key')
    raw=read(s3,bucket,key)
    if hashlib.sha256(raw).hexdigest()!=pointer['sha256']:raise ValueError('Snapshot checksum mismatch')
    data=json.loads(raw);rows=validate(data)
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(data['asOf'].replace('Z','+00:00'))).total_seconds()
    if not 0<=age<=7*86400:raise ValueError('Prepare a fresh history snapshot (at most seven days old)')
    job_name=None;artifact_uri=None;package_arn=None
    if any(eligible(row) for row in rows):
        images=json.loads((Path('deploy/kubernetes/apps/overlays')/c['environment']/'images.json').read_text());image=images['ml-training']
        if not image.startswith(c['account_id']+'.dkr.ecr.'+c['region']+'.amazonaws.com/') or '@sha256:' not in image:raise ValueError('Use the released training image digest')
        job_name=c['name']+'-forecast-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        sm.create_training_job(TrainingJobName=job_name,RoleArn=c['training_role_arn'],AlgorithmSpecification={'TrainingImage':image,'TrainingInputMode':'File'},HyperParameters={'task':'stock_forecast'},
            InputDataConfig=[{'ChannelName':'dataset','DataSource':{'S3DataSource':{'S3DataType':'S3Prefix','S3Uri':'s3://'+bucket+'/'+key.rsplit('/',1)[0]+'/','S3DataDistributionType':'FullyReplicated'}}}],
            OutputDataConfig={'S3OutputPath':'s3://'+bucket+'/forecast/training'},ResourceConfig={'InstanceType':'ml.m5.large','InstanceCount':1,'VolumeSizeInGB':10},StoppingCondition={'MaxRuntimeInSeconds':600},EnableNetworkIsolation=True)
        print('Bounded forecast training:',job_name,flush=True)
        def interrupted(*_):raise InterruptedError('Forecast training interrupted')
        signal.signal(signal.SIGTERM,interrupted)
        try:
            deadline=time.monotonic()+1200
            while time.monotonic()<deadline:
                job=sm.describe_training_job(TrainingJobName=job_name)
                if job['TrainingJobStatus'] in {'Completed','Failed','Stopped'}:break
                time.sleep(15)
            else:raise TimeoutError('Forecast wall-clock limit exceeded')
            if job['TrainingJobStatus']!='Completed':raise RuntimeError('SageMaker training failed; inspect its CloudWatch log')
        except BaseException:
            sm.stop_training_job(TrainingJobName=job_name);raise
        artifact_uri=job['ModelArtifacts']['S3ModelArtifacts'];artifact_bucket,artifact_key=artifact_uri[5:].split('/',1)
        if artifact_bucket!=bucket or not artifact_key.startswith('forecast/training/'):raise ValueError('Unexpected artifact location')
        archive=read(s3,bucket,artifact_key)
        with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
            entry=tar.getmember('forecast.json')
            if not entry.isfile() or entry.size>MAX_BYTES:raise ValueError('Invalid forecast bundle')
            result=json.load(tar.extractfile(entry))
        expected=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if result.get('datasetSha256')!=expected or result.get('task')!='stock_usage_forecast':raise ValueError('Training lineage mismatch')
        if result.get('qualityGatePassed'):
            package=sm.create_model_package(ModelPackageGroupName=c['forecast_model_package_group'],ModelPackageDescription='Daily stock usage Ridge models; recursive held-out quality gate; batch projections served by EKS forecast service.',ModelApprovalStatus='Approved' if publish else 'PendingManualApproval',
                InferenceSpecification={'Containers':[{'Image':image,'ModelDataUrl':artifact_uri}],'SupportedContentTypes':['application/json'],'SupportedResponseMIMETypes':['application/json']},
                CustomerMetadataProperties={'task':'stock_usage_forecast','datasetSha256':expected,'artifactSha256':hashlib.sha256(archive).hexdigest(),'trainingJob':job_name})
            package_arn=package['ModelPackageArn']
    else:
        print('Insufficient ML history: no paid SageMaker job started. Preparing labelled baseline/insufficient-data results.')
        result=train(data)
    result.update(trainingJob=job_name,modelPackageArn=package_arn,snapshotSha256=pointer['sha256'])
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
    report={'published':publish,'trainingJob':job_name,'modelPackageArn':package_arn,'artifactUri':artifact_uri,'releaseUri':'s3://'+bucket+'/'+release_key,'sha256':digest,'counts':{status:sum(p['status']==status for p in result['products']) for status in ('trained_ml','weekday_baseline','insufficient_history')},'evaluations':[{'sku':p['sku'],**p['evaluation']} for p in result['products'] if 'evaluation' in p]}
    Path('artifacts').mkdir(exist_ok=True);Path('artifacts/forecast-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--publish',action='store_true');args=p.parse_args()
    config=json.loads(Path(args.config).read_text());execute(config.get('deployment',{}).get('value',config),args.publish)

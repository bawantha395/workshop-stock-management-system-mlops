"""Run bounded SageMaker demos on generated data without touching live releases.

Successful candidates are visibly marked SYNTHETIC DEMO and remain pending in
the existing registry groups. Approval, promotion and serving reject synthetic
models. This script never updates forecast/current.json or a GitOps model URI.
"""
import argparse
import hashlib
import io
import json
import signal
import tarfile
import tempfile
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from generate_demo_data import generate
from stage_encoder import stage
from upload_dataset import immutable_put

ROOT=Path(__file__).resolve().parents[1]
MAX_ARTIFACT=40*1024*1024


def upload_demo(root,bucket,s3):
    root=Path(root)
    if json.loads((root/'dataset-metadata.json').read_text()).get('synthetic') is not True:
        raise ValueError('The demo workflow accepts only marked synthetic inputs')
    files={p.relative_to(root).as_posix():p for p in sorted(root.rglob('*')) if p.is_file()}
    checks={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files.items()}
    digest=hashlib.sha256(json.dumps(checks,sort_keys=True).encode()).hexdigest()
    prefix='demo/datasets/'+digest+'/'
    for name,path in files.items():
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=checks[name]:raise ValueError('Demo input changed during upload')
        immutable_put(s3,bucket,prefix+name,raw)
    return 's3://'+bucket+'/'+prefix


def wait_for_job(sm,name):
    deadline=time.monotonic()+1200
    def interrupted(*_):raise InterruptedError('Training interrupted')
    previous=signal.signal(signal.SIGTERM,interrupted)
    last_status=None
    try:
        while time.monotonic()<deadline:
            job=sm.describe_training_job(TrainingJobName=name)
            current=(job['TrainingJobStatus'],job.get('SecondaryStatus',''))
            if current!=last_status:
                print('SageMaker job state:',name,*current,flush=True);last_status=current
            if job['TrainingJobStatus'] in {'Completed','Failed','Stopped'}:
                if job['TrainingJobStatus']!='Completed':
                    raise RuntimeError('Training '+job['TrainingJobStatus']+'; inspect /aws/sagemaker/TrainingJobs for '+name)
                return job
            time.sleep(15)
        raise TimeoutError('Training wall-clock limit exceeded')
    except BaseException:
        # Preserve the original error if a completed/failed job cannot be stopped.
        try:sm.stop_training_job(TrainingJobName=name)
        except ClientError:pass
        raise
    finally:signal.signal(signal.SIGTERM,previous)


def read_artifact(s3,bucket,uri,filename):
    prefix='s3://'+bucket+'/demo/training/'
    if not uri.startswith(prefix):raise ValueError('Demo artifact is outside the isolated prefix')
    response=s3.get_object(Bucket=bucket,Key=uri.split('/',3)[3])
    with response['Body'] as stream:raw=stream.read(MAX_ARTIFACT+1)
    if len(raw)>MAX_ARTIFACT:raise ValueError('Demo artifact is unexpectedly large')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        member=archive.getmember(filename)
        if not member.isfile() or member.size>12*1024*1024:raise ValueError('Invalid demo report member')
        value=json.load(archive.extractfile(member))
    if value.get('syntheticData') is not True:raise ValueError('Released training image is missing demo support; run Prepare AWS release and merge its GitOps PR first')
    return value,hashlib.sha256(raw).hexdigest()


def train_one(task,c,sm,s3,image,dataset,encoder):
    name=c['name']+'-demo-'+task+'-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]
    channel=dataset+('photos/' if task=='photo' else 'forecast/seasonal_mixed/')
    inputs=[('dataset',channel)]
    if task=='photo':inputs.append(('encoder',encoder))
    sm.create_training_job(TrainingJobName=name,RoleArn=c['training_role_arn'],
        AlgorithmSpecification={'TrainingImage':image,'TrainingInputMode':'File'},
        HyperParameters={'task':'stock_forecast' if task=='forecast' else 'visual_sku','demo_mode':'true'},
        InputDataConfig=[{'ChannelName':key,'DataSource':{'S3DataSource':{'S3DataType':'S3Prefix',
            'S3Uri':uri,'S3DataDistributionType':'FullyReplicated'}}} for key,uri in inputs],
        OutputDataConfig={'S3OutputPath':'s3://'+c['model_bucket']+'/demo/training'},
        ResourceConfig={'InstanceType':'ml.m5.large','InstanceCount':1,'VolumeSizeInGB':10},
        StoppingCondition={'MaxRuntimeInSeconds':600},EnableNetworkIsolation=True)
    print('Started bounded SYNTHETIC DEMO job:',name,flush=True)
    job=wait_for_job(sm,name);uri=job['ModelArtifacts']['S3ModelArtifacts']
    metrics,digest=read_artifact(s3,c['model_bucket'],uri,'metrics.json' if task=='photo' else 'forecast.json')
    if metrics.get('qualityGatePassed') is not True:raise ValueError('Demo candidate did not pass its evaluation gate')
    metric_key='demo/evaluations/'+name+'/metrics.json'
    immutable_put(s3,c['model_bucket'],metric_key,json.dumps(metrics,allow_nan=False).encode())
    group=c['model_package_group'] if task=='photo' else c['forecast_model_package_group']
    package=sm.create_model_package(ModelPackageGroupName=group,
        ModelPackageDescription='SYNTHETIC DEMO ONLY: pipeline practice; not workshop quality evidence; production promotion disabled.',
        ModelApprovalStatus='PendingManualApproval',
        InferenceSpecification={'Containers':[{'Image':image,'ModelDataUrl':uri}],
            'SupportedContentTypes':['application/json'],'SupportedResponseMIMETypes':['application/json']},
        ModelMetrics={'ModelQuality':{'Statistics':{'ContentType':'application/json',
            'S3Uri':'s3://'+c['model_bucket']+'/'+metric_key}}},
        CustomerMetadataProperties={'syntheticData':'true','dataPurpose':'mlops_demo_only',
            'artifactSha256':digest,'trainingJob':name})
    return {'task':task,'status':'demo_training_completed','syntheticData':True,'productionEligible':False,
        'trainingJob':name,'modelPackageArn':package['ModelPackageArn'],'artifactUri':uri,
        'approval':'PendingManualApproval','qualityGatePassed':True,
        'counts':{state:sum(p['status']==state for p in metrics.get('products',[]))
                  for state in ('trained_ml','weekday_baseline','insufficient_history')} if task=='forecast' else
                 {key:metrics[key] for key in ('imageCount','precision','recall','testPairs')}}


def run(c,task='both',seed=20261027):
    session=boto3.Session(region_name=c['region'])
    if session.client('sts').get_caller_identity()['Account']!=c['account_id']:raise ValueError('Unexpected AWS account')
    overlay=ROOT/'deploy/kubernetes/apps/overlays'/c['environment']
    image=json.loads((overlay/'images.json').read_text())['ml-training']
    if not image.startswith(c['account_id']+'.dkr.ecr.'+c['region']+'.amazonaws.com/') or '@sha256:' not in image:
        raise ValueError('Use the released project training image digest')
    s3=session.client('s3');sm=session.client('sagemaker')
    result={'syntheticData':True,'productionEligible':False,'liveReleaseChanged':False,'seed':seed,'results':[]}
    tasks=['photo','forecast'] if task=='both' else [task]
    with tempfile.TemporaryDirectory(prefix='stocklane-demo-') as temp:
        generate(temp,seed)
        dataset=upload_demo(temp,c['model_bucket'],s3)
        result['datasetUri']=dataset
        encoder=stage(json.loads((overlay/'release.json').read_text()),c['model_bucket'],s3) if 'photo' in tasks else None
        for selected in tasks:
            try:result['results'].append(train_one(selected,c,sm,s3,image,dataset,encoder))
            except Exception as error:
                code=error.response['Error']['Code'] if isinstance(error,ClientError) else type(error).__name__
                result['results'].append({'task':selected,'status':'failed','errorCode':code,
                    'syntheticData':True,'productionEligible':False,
                    'message':'Inspect the SageMaker job/logs. Do not lower the model gate to make a demo pass.'})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--task',choices=['both','photo','forecast'],default='both')
    parser.add_argument('--seed',type=int,default=20261027);args=parser.parse_args()
    config=json.loads(Path(args.config).read_text());c=config.get('deployment',{}).get('value',config)
    report=run(c,args.task,args.seed)
    target=Path('artifacts/demo-training-report.json');target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    if any(item['status']=='failed' for item in report['results']):raise SystemExit(1)

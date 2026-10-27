"""Create actual SageMaker jobs on real public data using existing project roles.

Public benchmark candidates stay pending and cannot replace live workshop models.
The job name/ARN is recorded so it can be found in the Sydney SageMaker console.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
from datetime import datetime,timezone
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from prepare_public_data import prepare
from run_demo_training import wait_for_job
from stage_encoder import stage
from upload_dataset import immutable_put

ROOT=Path(__file__).resolve().parents[1]


def upload_public(directory,bucket,s3):
    root=Path(directory)
    lock=json.loads((root/'source-lock.json').read_text())
    if lock.get('purpose')!='public_data_benchmark' or lock.get('syntheticData') is not False:
        raise ValueError('Expected verified real public inputs')
    files={p.relative_to(root).as_posix():p for p in sorted(root.rglob('*')) if p.is_file()}
    checks={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}
    digest=hashlib.sha256(json.dumps(checks,sort_keys=True).encode()).hexdigest()
    prefix='benchmarks/public/datasets/'+digest+'/'
    for name,path in files.items():
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=checks[name]:raise ValueError('Input changed during upload')
        immutable_put(s3,bucket,prefix+name,data)
    return 's3://'+bucket+'/'+prefix,digest


def read_metrics(s3,bucket,uri):
    if not uri.startswith('s3://'+bucket+'/benchmarks/public/training/'):
        raise ValueError('Training returned an unexpected benchmark artifact location')
    response=s3.get_object(Bucket=bucket,Key=uri.split('/',3)[3])
    with response['Body'] as stream:raw=stream.read(40*1024*1024+1)
    if len(raw)>40*1024*1024:raise ValueError('Unexpected benchmark artifact size')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        member=archive.getmember('metrics.json')
        if not member.isfile() or member.size>2*1024*1024:raise ValueError('Invalid evaluation member')
        metrics=json.load(archive.extractfile(member))
    if metrics.get('benchmarkOnly') is not True or metrics.get('syntheticData') is not False:
        raise ValueError('Training image has no real-benchmark support; release the updated ml-training image first')
    return metrics,hashlib.sha256(raw).hexdigest()


def train_one(task,c,sm,s3,image,dataset,encoder,dataset_sha,source_sha,result):
    name=c['name']+'-public-'+task+'-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:4]
    result.update(task=task,trainingJob=name,creationConfirmed=False,syntheticData=False,
                  benchmarkOnly=True,productionEligible=False)
    inputs=[('dataset',dataset+('photos/' if task=='photo' else 'monthly-history/'))]
    if task=='photo':inputs.append(('encoder',encoder))
    names=['precision','recall'] if task=='photo' else ['meanModelMAE','meanBaselineMAE']
    print('Requesting real-data SageMaker job:',name,flush=True)
    submitted=sm.create_training_job(TrainingJobName=name,RoleArn=c['training_role_arn'],
        AlgorithmSpecification={'TrainingImage':image,'TrainingInputMode':'File',
            'MetricDefinitions':[{'Name':'benchmark:'+key,'Regex':'"'+key+'":\\s*([0-9.eE+-]+)'} for key in names]},
        HyperParameters={'task':'visual_sku' if task=='photo' else 'monthly_car_parts_benchmark','benchmark_mode':'true'},
        InputDataConfig=[
            {'ChannelName':key,'DataSource':{'S3DataSource':{'S3DataType':'S3Prefix','S3Uri':uri,
                'S3DataDistributionType':'FullyReplicated'}}} for key,uri in inputs],
        OutputDataConfig={'S3OutputPath':'s3://'+c['model_bucket']+'/benchmarks/public/training'},
        ResourceConfig={'InstanceType':'ml.m5.large','InstanceCount':1,'VolumeSizeInGB':10},
        StoppingCondition={'MaxRuntimeInSeconds':600},EnableNetworkIsolation=True)
    result.update(creationConfirmed=True,trainingJobArn=submitted['TrainingJobArn'])
    job=wait_for_job(sm,name)
    result['trainingJobStatus']=job['TrainingJobStatus']
    uri=job['ModelArtifacts']['S3ModelArtifacts'];metrics,digest=read_metrics(s3,c['model_bucket'],uri)
    key='benchmarks/public/evaluations/'+name+'/metrics.json'
    immutable_put(s3,c['model_bucket'],key,json.dumps(metrics,allow_nan=False).encode())
    group=c['model_package_group'] if task=='photo' else c['forecast_model_package_group']
    package=sm.create_model_package(ModelPackageGroupName=group,
        ModelPackageDescription='REAL PUBLIC DATA BENCHMARK: '+('ABO product identity calibration' if task=='photo' else 'historical monthly car-parts sales')+'. Requires workshop validation before any live use.',
        ModelApprovalStatus='PendingManualApproval',
        InferenceSpecification={'Containers':[{'Image':image,'ModelDataUrl':uri}],
            'SupportedContentTypes':['application/json'],'SupportedResponseMIMETypes':['application/json']},
        ModelMetrics={'ModelQuality':{'Statistics':{'ContentType':'application/json',
            'S3Uri':'s3://'+c['model_bucket']+'/'+key}}},
        CustomerMetadataProperties={'syntheticData':'false','benchmarkOnly':'true','dataPurpose':'public_data_benchmark',
            'artifactSha256':digest,'datasetInputSha256':dataset_sha,'sourceLockSha256':source_sha,'trainingJob':name})
    result.update(status='real_public_training_completed',artifactUri=uri,
        modelPackageArn=package['ModelPackageArn'],approval='PendingManualApproval',
        qualityGatePassed=metrics['qualityGatePassed'],metrics=metrics)
    return result


def run(c,task='both'):
    session=boto3.Session(region_name=c['region'])
    config=Config(connect_timeout=5,read_timeout=20,retries={'total_max_attempts':1})
    client=lambda name:session.client(name,config=config)
    if client('sts').get_caller_identity()['Account']!=c['account_id']:raise ValueError('AWS account mismatch')
    overlay=ROOT/'deploy/kubernetes/apps/overlays'/c['environment']
    image=json.loads((overlay/'images.json').read_text())['ml-training']
    if not image.startswith(c['account_id']+'.dkr.ecr.'+c['region']+'.amazonaws.com/') or '@sha256:' not in image:
        raise ValueError('Use the released project ml-training image digest')
    s3=client('s3');sm=client('sagemaker')
    result={'syntheticData':False,'benchmarkOnly':True,'liveReleaseChanged':False,
        'region':c['region'],'results':[]}
    tasks=['photo','forecast'] if task=='both' else [task]
    with tempfile.TemporaryDirectory(prefix='stocklane-public-data-') as temp:
        root=Path(temp)/'dataset'
        result['dataset']=prepare(root,cache=Path(temp)/'cache')
        dataset,dataset_sha=upload_public(root,c['model_bucket'],s3)
        result['datasetUri']=dataset
        encoder=stage(json.loads((overlay/'release.json').read_text()),c['model_bucket'],s3) if 'photo' in tasks else None
        for selected in tasks:
            item={};result['results'].append(item)
            try:train_one(selected,c,sm,s3,image,dataset,encoder,dataset_sha,result['dataset']['sourceLockSha256'],item)
            except Exception as error:
                code=error.response['Error']['Code'] if isinstance(error,ClientError) else type(error).__name__
                item.update(status='failed',errorCode=code,
                    nextCheck='Check the named job and CloudWatch logs. If creation was rejected, check SageMaker training permissions, account restrictions and the ml.m5.large training quota.')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--task',choices=['both','photo','forecast'],default='both')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text())
    try:report=run(config.get('deployment',{}).get('value',config),args.task)
    except Exception as error:
        code=error.response['Error']['Code'] if isinstance(error,ClientError) else type(error).__name__
        report={'status':'input_or_identity_preflight_failed','errorCode':code,
            'syntheticData':False,'benchmarkOnly':True,'liveReleaseChanged':False,'results':[],
            'nextCheck':'Verify AWS identity/deployment outputs, pinned public downloads and the released training image. No successful training job was confirmed.'}
    path=Path('artifacts/public-training-report.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report,indent=2,allow_nan=False))
    if report.get('status')=='input_or_identity_preflight_failed' or any(r['status']=='failed' for r in report['results']):raise SystemExit(1)

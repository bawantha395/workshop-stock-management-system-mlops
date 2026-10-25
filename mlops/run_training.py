"""Bounded SageMaker training -> independent quality gate -> pending Model Registry.
Run manually or from the protected aws-training GitHub environment.
"""
import argparse,hashlib,io,json,tarfile,time
from datetime import datetime,timezone
import boto3

def run(args):
    sm=boto3.client('sagemaker',region_name=args.region);s3=boto3.client('s3',region_name=args.region)
    name=args.name+'-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    sm.create_training_job(TrainingJobName=name,RoleArn=args.role,
        AlgorithmSpecification={'TrainingImage':args.image,'TrainingInputMode':'File'},
        InputDataConfig=[{'ChannelName':channel,'DataSource':{'S3DataSource':{'S3DataType':'S3Prefix','S3Uri':uri,'S3DataDistributionType':'FullyReplicated'}}} for channel,uri in [('dataset',args.dataset),('encoder',args.encoder)]],
        OutputDataConfig={'S3OutputPath':args.output},
        ResourceConfig={'InstanceType':'ml.m5.large','InstanceCount':1,'VolumeSizeInGB':10},
        StoppingCondition={'MaxRuntimeInSeconds':600},EnableNetworkIsolation=True)
    print('Training job:',name,flush=True)
    while True:
        job=sm.describe_training_job(TrainingJobName=name)
        if job['TrainingJobStatus'] in {'Completed','Failed','Stopped'}:break
        time.sleep(15)
    if job['TrainingJobStatus']!='Completed':raise RuntimeError('Training did not complete; inspect its CloudWatch logs')
    uri=job['ModelArtifacts']['S3ModelArtifacts'];bucket,key=uri[5:].split('/',1)
    archive=s3.get_object(Bucket=bucket,Key=key)['Body'].read()
    if len(archive)>40*1024*1024:raise RuntimeError('Unexpectedly large model bundle')
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        metrics=json.load(tar.extractfile('metrics.json'))
    if not metrics.get('qualityGatePassed'):raise RuntimeError('Refusing registration of a failed model')
    package=sm.create_model_package(ModelPackageGroupName=args.group,ModelPackageDescription='Visual encoder and trained pair calibrator; EKS serving; human review remains required',ModelApprovalStatus='PendingManualApproval',
        InferenceSpecification={'Containers':[{'Image':args.image,'ModelDataUrl':uri}],'SupportedContentTypes':['application/json'],'SupportedResponseMIMETypes':['application/json']},
        CustomerMetadataProperties={'datasetSha256':metrics['datasetSha256'],'encoderSha256':metrics['encoderSha256'],'artifactSha256':hashlib.sha256(archive).hexdigest(),'trainingJob':name})
    print(json.dumps({'modelPackageArn':package['ModelPackageArn'],'artifactUri':uri,'metrics':metrics},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['region','name','role','image','dataset','encoder','output','group']:p.add_argument('--'+name,required=True)
    run(p.parse_args())

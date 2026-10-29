import argparse,hashlib,io,json,tarfile
import boto3
from botocore.exceptions import ClientError

def promote(package_arn,region,destination):
    sm=boto3.client('sagemaker',region_name=region);s3=boto3.client('s3',region_name=region)
    package=sm.describe_model_package(ModelPackageName=package_arn)
    if package.get('CustomerMetadataProperties',{}).get('syntheticData')=='true':raise RuntimeError('Synthetic demo packages cannot be promoted to the live application')
    if package.get('CustomerMetadataProperties',{}).get('benchmarkOnly')=='true':raise RuntimeError('Public benchmark packages cannot be promoted as workshop models')
    if package['ModelApprovalStatus']!='Approved':raise RuntimeError('Model Registry approval is required (automatic gate or a reviewer)')
    uri=package['InferenceSpecification']['Containers'][0]['ModelDataUrl'];bucket,key=uri[5:].split('/',1)
    archive=s3.get_object(Bucket=bucket,Key=key)['Body'].read();digest=hashlib.sha256(archive).hexdigest()
    if digest!=package['CustomerMetadataProperties']['artifactSha256']:raise RuntimeError('Registered artifact checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        metrics=json.load(tar.extractfile('metrics.json'));model=json.load(tar.extractfile('model.json'))
    if model.get('syntheticData') or metrics.get('syntheticData'):raise RuntimeError('Synthetic demo artifacts cannot be promoted')
    if model.get('benchmarkOnly') or metrics.get('benchmarkOnly'):raise RuntimeError('Public benchmark artifacts require workshop validation')
    if not metrics.get('qualityGatePassed') or not model.get('workshopCalibrated'):raise RuntimeError('Model test gate was not passed')
    target_bucket,prefix=destination[5:].split('/',1);target_key=prefix.rstrip('/')+'/'+model['version']+'/'+digest+'.tar.gz'
    try:s3.put_object(Bucket=target_bucket,Key=target_key,Body=archive,IfNoneMatch='*')
    except ClientError as error:
        if error.response['Error']['Code'] not in {'PreconditionFailed','412'}:raise
        existing=s3.get_object(Bucket=target_bucket,Key=target_key)['Body'].read()
        if hashlib.sha256(existing).hexdigest()!=digest:raise RuntimeError('Existing promoted artifact checksum mismatch')
    return {'uri':'s3://'+target_bucket+'/'+target_key,'sha256':digest,'version':model['version'],'packageArn':package_arn}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package-arn',required=True);p.add_argument('--region',required=True);p.add_argument('--destination',required=True);a=p.parse_args();print(json.dumps(promote(a.package_arn,a.region,a.destination)))

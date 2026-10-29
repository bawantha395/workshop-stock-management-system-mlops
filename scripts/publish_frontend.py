"""Publish exactly the frontend files approved in the merged GitOps release."""
import argparse,hashlib,json,mimetypes
from pathlib import Path,PurePosixPath
import boto3
parser=argparse.ArgumentParser()
parser.add_argument('--environment',choices=['dev','staging','prod'],default='dev')
a=parser.parse_args()
c=json.loads((Path('deploy/kubernetes/apps/overlays')/a.environment/'frontend_release.json').read_text())
if boto3.client('sts').get_caller_identity()['Account']!=c['accountId']:raise RuntimeError('AWS account mismatch')
s3=boto3.client('s3',region_name=c['region'])
for file in c['files']:
    path=PurePosixPath(file['path'])
    if path.is_absolute() or '..' in path.parts:raise ValueError('Invalid frontend artifact path')
    data=s3.get_object(Bucket=c['sourceBucket'],Key=c['sourcePrefix']+'/'+path.as_posix())['Body'].read()
    if hashlib.sha256(data).hexdigest()!=file['sha256']:raise RuntimeError('Frontend artifact checksum mismatch')
    content=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    s3.put_object(Bucket=c['targetBucket'],Key=path.as_posix(),Body=data,ContentType=content,CacheControl='no-store' if path.name in {'index.html','config.js'} else 'public,max-age=31536000,immutable')
boto3.client('cloudfront').create_invalidation(DistributionId=c['distributionId'],InvalidationBatch={'Paths':{'Quantity':3,'Items':['/','/index.html','/config.js']},'CallerReference':c['release']+'-paths-v2'})
print('Published the reviewed frontend release:',c['release'])

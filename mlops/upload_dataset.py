"""Upload a reviewed local dataset to an immutable, content-addressed S3 prefix."""
import argparse,csv,hashlib,io,json
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from dataset import validate_manifest

def immutable_put(s3,bucket,key,data):
    try:s3.put_object(Bucket=bucket,Key=key,Body=data,IfNoneMatch='*')
    except ClientError as error:
        if error.response['Error']['Code'] not in {'PreconditionFailed','412'}:raise
        if hashlib.sha256(s3.get_object(Bucket=bucket,Key=key)['Body'].read()).digest()!=hashlib.sha256(data).digest():raise ValueError('Existing dataset bytes differ')

def upload(directory,bucket,region,s3=None):
    root=Path(directory).resolve()
    marker=root/'dataset-metadata.json'
    metadata=json.loads(marker.read_text()) if marker.exists() else {}
    if metadata.get('synthetic') is True:
        raise ValueError('Synthetic data cannot be uploaded to the reviewed workshop dataset prefix')
    if metadata.get('benchmarkOnly') is True:
        raise ValueError('Public benchmark data belongs to the public-data workflow, not the workshop dataset prefix')
    manifest=(root/'manifest.csv').read_bytes()
    rows=list(csv.DictReader(io.StringIO(manifest.decode('utf-8-sig'))));validate_manifest(rows)
    files={'manifest.csv':manifest};checks={'manifest.csv':hashlib.sha256(manifest).hexdigest()};seen=set()
    if len(rows)>2000:raise ValueError('Split datasets larger than 2000 images into reviewed training versions')
    for row in rows:
        name=row['file'];p=(root/name).resolve()
        if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:raise ValueError('Dataset paths must be relative without traversal')
        if root not in p.parents or p.suffix.lower() not in {'.jpg','.jpeg','.png'}:raise ValueError('Use JPEG/PNG files inside the dataset directory')
        data=p.read_bytes()
        if len(data)>8*1024*1024:raise ValueError('An image exceeds 8 MiB')
        digest=hashlib.sha256(data).hexdigest()
        if digest in seen:raise ValueError('Duplicate image bytes; use independent capture sessions')
        seen.add(digest);files[name]=p;checks[name]=digest
    index=json.dumps(checks,sort_keys=True).encode();version=hashlib.sha256(index).hexdigest()
    files['dataset-checksums.json']=index;s3=s3 or boto3.client('s3',region_name=region)
    for name,source in files.items():
        data=source.read_bytes() if isinstance(source,Path) else source
        if name in checks and hashlib.sha256(data).hexdigest()!=checks[name]:raise ValueError('A local image changed during upload; create a stable dataset snapshot')
        immutable_put(s3,bucket,'datasets/'+version+'/'+name,data)
    return {'datasetUri':'s3://'+bucket+'/datasets/'+version+'/','datasetVersion':version,'imageCount':len(rows)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--bucket',required=True);p.add_argument('--region',default='ap-southeast-2');a=p.parse_args();print(json.dumps(upload(a.directory,a.bucket,a.region),indent=2))

"""Read an immutable, checksum-bound model bundle. Never extract arbitrary paths."""
import hashlib,io,json,os,tarfile
from pathlib import Path
import boto3

def fetch():
    uri=os.environ['MODEL_URI'];expected=os.environ['MODEL_ARCHIVE_SHA256'];folder=Path(os.environ.get('MODEL_DIR','/models/current'))
    if not uri.startswith('s3://') or len(expected)!=64:raise ValueError('Model URI and archive SHA256 are required')
    bucket,key=uri[5:].split('/',1);data=boto3.client('s3').get_object(Bucket=bucket,Key=key)['Body'].read()
    if len(data)>40*1024*1024 or hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Model bundle checksum mismatch')
    folder.mkdir(parents=True,exist_ok=True)
    allowed={'encoder.onnx','model.json','metrics.json'}
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:
        members=tar.getmembers()
        if any(not m.isfile() or m.name not in allowed or m.size>25*1024*1024 for m in members):raise ValueError('Unexpected model archive contents')
        for member in members:(folder/member.name).write_bytes(tar.extractfile(member).read())
    manifest=json.loads((folder/'model.json').read_text())
    if hashlib.sha256((folder/'encoder.onnx').read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('Encoder checksum mismatch')
    print('Verified model bundle:',manifest['version'])

if __name__=='__main__':fetch()

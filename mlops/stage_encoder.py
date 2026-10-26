"""Stage the checksum-verified encoder of the approved EKS release for training."""
import hashlib,io,json,tarfile
from upload_dataset import immutable_put

def stage(release,bucket,s3):
    model=release['model'];uri=model['uri']
    if not uri.startswith('s3://'+bucket+'/releases/'):raise ValueError('Encoder must come from the project release bucket')
    key=uri[5:].split('/',1)[1];archive=s3.get_object(Bucket=bucket,Key=key)['Body'].read()
    if len(archive)>40*1024*1024 or hashlib.sha256(archive).hexdigest()!=model['sha256']:raise ValueError('Encoder bundle checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        files={name:tar.extractfile(name).read() for name in ['encoder.onnx','model.json']}
    manifest=json.loads(files['model.json']);digest=hashlib.sha256(files['encoder.onnx']).hexdigest()
    if manifest['sha256']!=digest:raise ValueError('Encoder checksum mismatch')
    for name,data in files.items():immutable_put(s3,bucket,'encoders/'+model['sha256']+'/'+name,data)
    return 's3://'+bucket+'/encoders/'+model['sha256']+'/'

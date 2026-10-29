#!/usr/bin/env python3
"""Build immutable container releases and render a GitOps PR payload in CI."""
import argparse,hashlib,io,json,os,re,subprocess,tarfile
from pathlib import Path
import boto3
from render_cloud import render
from helm_utils import HELM, environment
ROOT=Path(__file__).resolve().parents[1]

def reviewed_model(release_dir,bucket,s3=None):
    path=release_dir/'release.json'
    if not path.exists():return None
    value=json.loads(path.read_text())['model']
    if not value['uri'].startswith('s3://'+bucket+'/releases/') or not re.fullmatch(r'[a-f0-9]{64}',value['sha256']):
        raise ValueError('The previous reviewed model has invalid project provenance')
    if s3 is not None:
        # A freshly recreated environment has an empty models bucket: start
        # again from the checksum-pinned baseline instead of a missing bundle.
        try:s3.head_object(Bucket=bucket,Key=value['uri'].split('/',3)[3])
        except Exception as error:
            if getattr(error,'response',{}).get('Error',{}).get('Code') in {'404','NoSuchKey','NotFound'}:
                print('Previous model bundle is gone (new environment); using the baseline model');return None
            raise
    return {**value,'version':'retained-reviewed-model'}

def build(a):
    c=json.loads(Path(a.config).read_text());c=c.get('deployment',{}).get('value',c)
    target,namespace=environment(c);release_dir=HELM/'releases'/target
    region=c['region'];s3=boto3.client('s3',region_name=region)
    if boto3.client('sts').get_caller_identity()['Account']!=c['account_id']:raise RuntimeError('AWS account mismatch')
    commit=subprocess.check_output(['git','rev-parse','HEAD']).decode().strip()
    expected=os.environ.get('STOCKLANE_SOURCE_SHA') or os.environ.get('GITHUB_SHA')
    if expected and expected!=commit:raise RuntimeError('Checked-out source does not match the reviewed commit')
    retained=reviewed_model(release_dir,c['model_bucket'],s3) if not a.model_package else None
    if retained and retained.get('packageArn'):
        description=boto3.client('sagemaker',region_name=region).describe_model_package(ModelPackageName=retained['packageArn'])
        if description['ModelApprovalStatus']!='Approved':raise RuntimeError('The retained model package is no longer approved')
    tag=commit[:12]+'-'+os.environ.get('GITHUB_RUN_ID','local')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
    work=ROOT/'artifacts/release';work.mkdir(parents=True,exist_ok=True);images={}
    mapping={'inventory':'Java','workshop':'Java','vision':'Vision','forecast':'Forecast','operations':'Operations','ml-training':'Training'}
    for name,dockerfile in mapping.items():
        metadata=work/(name+'.json');image=c['ecr'][name]+':'+tag
        args=['docker','buildx','build','--platform','linux/amd64','-f',str(ROOT/'deploy/docker'/(dockerfile+'.Dockerfile')),'--tag',image,'--metadata-file',str(metadata),'--push']
        if name in {'inventory','workshop'}:args+=['--build-arg','SERVICE='+name]
        subprocess.run(args+[str(ROOT)],check=True)
        digest=json.loads(metadata.read_text())['containerimage.digest'];images[name]=c['ecr'][name]+'@'+digest
    if a.model_package:
        import sys
        sys.path.insert(0,str(ROOT/'mlops'));from promote import promote
        model=promote(a.model_package,region,'s3://'+c['model_bucket']+'/releases')
        model['packageArn']=a.model_package
    elif retained:
        model=retained
    else:
        folder=ROOT/'models/baseline';buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as tar:
            for name in ['encoder.onnx','model.json']:tar.add(folder/name,arcname=name)
        data=buffer.getvalue();digest=hashlib.sha256(data).hexdigest();key='releases/baseline/'+digest+'.tar.gz'
        s3.put_object(Bucket=c['model_bucket'],Key=key,Body=data,IfNoneMatch='*')
        model={'uri':'s3://'+c['model_bucket']+'/'+key,'sha256':digest,'version':'baseline-human-review'}
    render(c,images,model['uri'],model['sha256'],platform=True)
    if model.get('packageArn'):
        release_path=release_dir/'release.json';release=json.loads(release_path.read_text())
        release['model']['packageArn']=model['packageArn'];release_path.write_text(json.dumps(release,indent=2)+'\n')
    subprocess.run(['python','scripts/validate_helm.py','--environment',target,'--configured'],cwd=ROOT,check=True)
    # Stage the frontend privately. Publication follows the reviewed GitOps merge.
    public=ROOT/'apps/web/public/config.js';public.write_text((release_dir/'config.js').read_text())
    subprocess.run(['npm','ci'],cwd=ROOT/'apps/web',check=True);subprocess.run(['npm','run','build'],cwd=ROOT/'apps/web',check=True)
    prefix='releases/frontend/'+tag
    files=[]
    for file in sorted((ROOT/'apps/web/dist').rglob('*')):
        if not file.is_file():continue
        relative=file.relative_to(ROOT/'apps/web/dist').as_posix();data=file.read_bytes();checksum=hashlib.sha256(data).hexdigest()
        s3.put_object(Bucket=c['model_bucket'],Key=prefix+'/'+relative,Body=data)
        files.append({'path':relative,'sha256':checksum})
    frontend={'sourceBucket':c['model_bucket'],'sourcePrefix':prefix,'targetBucket':c['web_bucket'],'distributionId':c['cloudfront_distribution_id'],'region':c['region'],'accountId':c['account_id'],'release':tag,'files':files}
    (release_dir/'frontend_release.json').write_text(json.dumps(frontend,indent=2)+'\n')
    (work/'summary.md').write_text('Builds immutable service images and prepares the AWS GitOps values.\n\nModel bundle: '+model['version']+'\n\nValidation: CI checks must pass before merging. Argo CD builds compatible reference vectors before rollout.\n')
    print('Release rendered: images pushed, GitOps values and frontend bundle prepared.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--model-package',default='');build(p.parse_args())

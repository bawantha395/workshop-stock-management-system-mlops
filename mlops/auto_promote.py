"""Automatic Model Registry decision for a newly trained photo model.

A new version is approved only when it passed the quality gate (run_training registers
nothing else) AND it beats the model the environment serves now: higher test F1, at a
test precision of at least 98%. Otherwise it is rejected with the reason, and the served
model stays. Approved versions are then released through GitOps (_release.yml commits the
overlay; Argo CD rolls it out). Every decision is written to the Model Registry.
"""
import argparse,io,json,os,tarfile
from pathlib import Path
import boto3

ROOT=Path(__file__).resolve().parents[1]
MIN_PRECISION=.98


def served_package(environment):
    path=ROOT/'deploy/kubernetes/apps/overlays'/environment/'release.json'
    if not path.exists():return None
    return json.loads(path.read_text()).get('model',{}).get('packageArn')


def package_metrics(sm,s3,arn):
    package=sm.describe_model_package(ModelPackageName=arn)
    uri=package['InferenceSpecification']['Containers'][0]['ModelDataUrl'];bucket,key=uri[5:].split('/',1)
    archive=s3.get_object(Bucket=bucket,Key=key)['Body'].read(40*1024*1024+1)
    if len(archive)>40*1024*1024:raise ValueError('Unexpectedly large model bundle')
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:return json.load(tar.extractfile('metrics.json'))


def better(new,current):
    """True when the new model may replace the current one."""
    if not new.get('qualityGatePassed') or new.get('precision',0)<MIN_PRECISION:return False
    if current is None:return True
    return new.get('f1',0)>current.get('f1',0)+1e-9


def decide(report,environment,region,sm=None,s3=None):
    sm=sm or boto3.client('sagemaker',region_name=region);s3=s3 or boto3.client('s3',region_name=region)
    new_arn=report['modelPackageArn'];new=report['metrics'];current_arn=served_package(environment)
    current=package_metrics(sm,s3,current_arn) if current_arn else None
    against='the baseline model' if current is None else f'the served model (F1 {current.get("f1",0):.3f})'
    if better(new,current):
        reason=f'Automatic approval: passed the quality gate and beat {against} with F1 {new["f1"]:.3f}, precision {new["precision"]:.3f}.'
        sm.update_model_package(ModelPackageArn=new_arn,ModelApprovalStatus='Approved',ApprovalDescription=reason[:1000])
        return {'decision':'approved','modelPackageArn':new_arn,'reason':reason,'replaces':current_arn}
    reason=f'Automatic rejection: F1 {new.get("f1",0):.3f} did not beat {against}; the served model stays.'
    sm.update_model_package(ModelPackageArn=new_arn,ModelApprovalStatus='Rejected',ApprovalDescription=reason[:1000])
    return {'decision':'rejected','modelPackageArn':new_arn,'reason':reason,'replaces':None}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',required=True);p.add_argument('--environment',required=True)
    p.add_argument('--region',default='ap-southeast-2');p.add_argument('--output');a=p.parse_args()
    result=decide(json.loads(Path(a.report).read_text()),a.environment,a.region)
    print(json.dumps(result,indent=2))
    if a.output:Path(a.output).write_text(json.dumps(result,indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('approved='+(result['modelPackageArn'] if result['decision']=='approved' else '')+'\n')

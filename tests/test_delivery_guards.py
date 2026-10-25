from pathlib import Path
import importlib.util
import json
import sys
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from render_cloud import render
from kustomize_utils import build

def config():
    return {'region':'eu-west-1','name':'stocklane-test','account_id':'123456789012','cognito_issuer':'https://cognito-idp.eu-west-1.amazonaws.com/test','cognito_web_client_id':'web-client','cognito_camera_client_id':'camera-client','frontend_url':'https://test.cloudfront.net','stock_queue_url':'https://sqs.eu-west-1.amazonaws.com/123456789012/stock','catalogue_queue_url':'https://sqs.eu-west-1.amazonaws.com/123456789012/catalogue','cache_host':'cache.example.internal','media_bucket':'test-media','database_host':'db.example.internal','database_secrets':{s:'arn:aws:secretsmanager:eu-west-1:123456789012:secret:'+s for s in ['inventory','workshop','vision']},'platform_secret_arn':'arn:aws:secretsmanager:eu-west-1:123456789012:secret:platform','api_domain':'api.example.com','api_certificate_arn':'arn:aws:acm:eu-west-1:123456789012:certificate/test'}

def images():return {s:'123456789012.dkr.ecr.eu-west-1.amazonaws.com/'+s+'@sha256:'+'a'*64 for s in ['inventory','workshop','vision','operations']}

def test_gitops_requires_digests(tmp_path):
    bad=images();bad['vision']='vision:latest'
    with pytest.raises(ValueError,match='immutable'):render(config(),bad,'s3://models/release.tar.gz','f'*64,tmp_path)

def test_gitops_has_tls_auth_and_versioned_model_hooks(tmp_path):
    render(config(),images(),'s3://models/release.tar.gz','f'*64,tmp_path)
    docs=build(tmp_path)
    deployments=[d for d in docs if d['kind']=='Deployment'];assert len(deployments)==3
    assert all(d['spec']['replicas']==3 for d in deployments)
    for d in deployments:
        p=d['spec']['template']['spec'];assert p['securityContext']['runAsNonRoot'];assert p['containers'][0]['securityContext']['readOnlyRootFilesystem']
    ingress=next(d for d in docs if d['kind']=='Ingress');assert 'HTTPS' in ingress['metadata']['annotations']['alb.ingress.kubernetes.io/listen-ports']
    assert all(p['path'].startswith('/api/') for p in ingress['spec']['rules'][0]['http']['paths'])
    assert any(d['kind']=='Job' and d['metadata']['annotations']['argocd.argoproj.io/hook']=='PreSync' for d in docs)
    configmap=next(d for d in docs if d['kind']=='ConfigMap');assert configmap['data']['AUTH_MODE']=='cognito';assert 'PASSWORD' not in json.dumps(configmap)
    assert len([d for d in docs if d['kind']=='ExternalSecret'])==3
    secrets={d['metadata']['name']:d['spec']['target']['template']['data'] for d in docs if d['kind']=='ExternalSecret'}
    assert 'INVENTORY_CONTROL_TOKEN' not in secrets['vision-secrets']
    assert 'INVENTORY_CONTROL_TOKEN' in secrets['workshop-secrets']

def test_no_local_identity_in_cloud_runtime_config(tmp_path):
    render(config(),images(),'s3://models/release.tar.gz','f'*64,tmp_path)
    assert '"authMode": "cognito"' in (tmp_path/'config.js').read_text()

def test_training_session_leakage_is_rejected():
    sys.path.insert(0,str(ROOT/'mlops'))
    from train import validate_manifest
    rows=[{'file':f'{split}-{n}.jpg','sku':f'SKU-{n%3}','session':'same-session','split':split} for split in ['train','validation','test'] for n in range(20)]
    with pytest.raises(ValueError,match='leakage'):validate_manifest(rows)

def test_training_never_passes_an_empty_dataset():
    sys.path.insert(0,str(ROOT/'mlops'))
    from train import validate_manifest
    with pytest.raises(ValueError,match='60'):validate_manifest([])

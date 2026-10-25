"""Exercise the manifests built by real Kustomize, rather than a YAML imitation."""
import importlib.util
import json
import sys
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from kustomize_utils import KUBERNETES, ENVIRONMENTS, build, load_yaml
from render_cloud import render
from validate_kustomize import schemas, validate_apps, validate_objects, verify_upstream

@pytest.fixture(scope='module')
def apps():
    return {env: build(KUBERNETES / 'apps/overlays' / env) for env in ENVIRONMENTS}

@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_environment_services_and_scalers_target_their_own_pods(apps, env):
    docs = apps[env]
    validate_apps(docs, ENVIRONMENTS[env])
    validate_objects(docs, schemas())
    assert all(o['metadata'].get('namespace') == ENVIRONMENTS[env] for o in docs if o['kind'] != 'Namespace')
    pods = {o['metadata']['name']: o for o in docs if o['kind'] == 'Deployment'}
    for hpa in (o for o in docs if o['kind'] == 'HorizontalPodAutoscaler'):
        assert hpa['spec']['minReplicas'] == pods[hpa['metadata']['name']]['spec']['replicas']

@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_argo_applications_reference_projects_and_paths_for_the_same_environment(env):
    docs = build(KUBERNETES / 'argocd/applications/overlays' / env)
    projects = {o['metadata']['name']: o for o in docs if o['kind'] == 'AppProject'}
    children = [o for o in docs if o['kind'] == 'Application']
    assert len(children) == 4
    for app in children:
        assert app['metadata']['name'].endswith('-' + env)
        assert app['spec']['project'] in projects
        assert app['spec']['source']['path'].endswith('/' + env)
    workload = next(o for o in children if o['metadata']['name'].startswith('stocklane-workshop-'))
    assert workload['spec']['destination']['namespace'] == ENVIRONMENTS[env]
    assert int(workload['metadata']['annotations']['argocd.argoproj.io/sync-wave']) > 20

def test_production_monitoring_keeps_persistent_data_and_private_admin_access():
    docs = build(KUBERNETES / 'monitoring/overlays/production')
    validate_objects(docs, schemas())
    assert next(o for o in docs if o['kind']=='Prometheus')['spec']['replicas'] == 2
    assert next(o for o in docs if o['kind']=='Alertmanager')['spec']['replicas'] == 3
    claim = next(o for o in docs if o['kind']=='PersistentVolumeClaim')
    assert claim['spec']['storageClassName'] == 'gp3'
    grafana = next(o for o in docs if o['kind']=='Deployment' and o['metadata']['name']=='grafana')
    assert grafana['spec']['strategy']['type'] == 'Recreate'
    password = next(v for v in grafana['spec']['template']['spec']['containers'][0]['env'] if v['name']=='GF_SECURITY_ADMIN_PASSWORD')
    assert 'secretKeyRef' in password['valueFrom']
    assert not any(o['kind']=='Ingress' or (o['kind']=='Service' and o['spec'].get('type')=='LoadBalancer') for o in docs)

def test_imported_manifests_match_the_reviewed_lock_and_use_one_resource_per_file():
    verify_upstream()
    for path in KUBERNETES.rglob('*.yaml'):
        if path.name in ['kustomization.yaml','kustomizeconfig.yaml']:continue
        docs = list(yaml.load_all(path.read_text(), Loader=getattr(yaml,'CSafeLoader',yaml.SafeLoader)))
        assert len(docs) == 1, str(path)
        assert docs[0].get('apiVersion') and docs[0].get('kind'), str(path)

def config(env='production'):
    return {'environment':env,'region':'eu-west-1','account_id':'123456789012','cognito_issuer':'https://cognito-idp.eu-west-1.amazonaws.com/test','cognito_web_client_id':'web-client','cognito_camera_client_id':'camera-client','frontend_url':'https://test.cloudfront.net','stock_queue_url':'https://sqs.eu-west-1.amazonaws.com/123456789012/stock','catalogue_queue_url':'https://sqs.eu-west-1.amazonaws.com/123456789012/catalogue','cache_host':'cache.example.internal','media_bucket':'test-media','database_host':'db.example.internal','database_secrets':{s:'arn:aws:secretsmanager:eu-west-1:123456789012:secret:'+s for s in ['inventory','workshop','vision']},'platform_secret_arn':'arn:aws:secretsmanager:eu-west-1:123456789012:secret:platform','api_domain':'api.example.com','api_certificate_arn':'arn:aws:acm:eu-west-1:123456789012:certificate/test'}

def test_renderer_preserves_bases_and_rolls_pods_when_the_model_changes(tmp_path):
    before = (KUBERNETES/'apps/base/vision/deployment.yaml').read_bytes()
    images = {s:'123456789012.dkr.ecr.eu-west-1.amazonaws.com/'+s+'@sha256:'+'a'*64 for s in ['inventory','workshop','vision','operations']}
    render(config(),images,'s3://test-models/release.tar.gz','f'*64,tmp_path)
    initial = build(tmp_path)
    validate_apps(initial,'stocklane',configured=True)
    first = next(o for o in initial if o['kind']=='Deployment' and o['metadata']['name']=='vision')['spec']['template']['metadata']['annotations']['stocklane.io/config-sha256']
    render(config(),images,'s3://test-models/next.tar.gz','e'*64,tmp_path)
    updated = build(tmp_path)
    second = next(o for o in updated if o['kind']=='Deployment' and o['metadata']['name']=='vision')['spec']['template']['metadata']['annotations']['stocklane.io/config-sha256']
    assert first != second
    hook = next(o for o in updated if o['kind']=='Job')['spec']['template']['spec']
    for container in hook['containers'] + hook['initContainers']:
        env = {v['name']: v.get('value') for v in container['env']}
        assert env['MODEL_URI'] == 's3://test-models/next.tar.gz'
        assert env['MODEL_ARCHIVE_SHA256'] == 'e'*64
    assert (KUBERNETES/'apps/base/vision/deployment.yaml').read_bytes() == before
    assert not (tmp_path/'resources.yaml').exists()

def test_renderer_rejects_an_environment_namespace_mismatch(tmp_path):
    c=config('dev');c['workload_namespace']='stocklane'
    with pytest.raises(ValueError,match='namespace'):
        render(c,{},'s3://models/release.tar.gz','f'*64,tmp_path)

def test_full_account_render_wires_platform_monitoring_and_bootstrap(tmp_path, monkeypatch):
    import shutil
    import render_cloud as renderer
    import validate_kustomize as validator
    fixture=tmp_path/'kubernetes'
    shutil.copytree(KUBERNETES,fixture)
    monkeypatch.setattr(renderer,'KUBERNETES',fixture)
    monkeypatch.setattr(validator,'KUBERNETES',fixture)
    c=config();c.update({'name':'stocklane-test','github_repository':'bawantha395/workshop-stock-ai-ops','workload_namespace':'stocklane','cluster_name':'stocklane-test','vpc_id':'vpc-0123456789abcdef0','master_secret_arn':'arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds-master','grafana_secret_arn':'arn:aws:secretsmanager:eu-west-1:123456789012:secret:grafana','operations_topic_arn':'arn:aws:sns:eu-west-1:123456789012:stocklane-operations','application_log_group':'/stocklane/test/containers'})
    images={s:'123456789012.dkr.ecr.eu-west-1.amazonaws.com/'+s+'@sha256:'+'a'*64 for s in ['inventory','workshop','vision','operations']}
    renderer.render(c,images,'s3://test-models/release.tar.gz','f'*64,platform=True)
    counts=validator.validate_environment('production',configured=True)
    assert counts['platform']>20 and counts['monitoring']>10 and counts['bootstrap']==3

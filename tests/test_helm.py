"""Exercise the charts rendered by Helm exactly as Argo CD and the bootstrap render them.

CI installs the pinned Helm binary. Without Helm these tests are skipped locally; set
STOCKLANE_REQUIRE_HELM=1 (CI does) to make a missing Helm a failure instead.
"""
import copy
import base64
import json
import os
import re
import shutil
import sys
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from helm_utils import HELM, ENVIRONMENTS, CHARTS, build, load_yaml, helm_binary, template
import render_cloud
from render_cloud import render
from validate_helm import crd_definitions, schemas, validate_apps, validate_environment, validate_objects, verify_upstream

try:
    helm_binary()
except RuntimeError:
    if os.environ.get('STOCKLANE_REQUIRE_HELM'):
        raise
    pytest.skip('Helm is not installed', allow_module_level=True)

IMAGES = {s: '123456789012.dkr.ecr.eu-west-1.amazonaws.com/' + s + '@sha256:' + 'a' * 64
          for s in ['inventory', 'workshop', 'vision', 'forecast', 'operations']}

def config(env='prod', **extra):
    c = {'environment': env, 'region': 'eu-west-1', 'account_id': '123456789012',
         'cognito_issuer': 'https://cognito-idp.eu-west-1.amazonaws.com/test', 'cognito_web_client_id': 'web-client',
         'frontend_url': 'https://test.cloudfront.net',
         'stock_queue_url': 'https://sqs.eu-west-1.amazonaws.com/123456789012/stock',
         'catalogue_queue_url': 'https://sqs.eu-west-1.amazonaws.com/123456789012/catalogue',
         'cache_host': 'cache.example.internal', 'media_bucket': 'test-media', 'model_bucket': 'test-models',
         'database_host': 'db.example.internal',
         'database_secrets': {s: 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:' + s for s in ['inventory', 'workshop', 'vision']},
         'platform_secret_arn': 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:platform',
         'api_domain': 'api.example.com', 'api_certificate_arn': 'arn:aws:acm:eu-west-1:123456789012:certificate/test',
         'name': 'stocklane-' + env, 'github_repository': 'bawantha395/workshop-stock-ai-ops',
         'workload_namespace': 'stocklane-' + env, 'cluster_name': 'stocklane-' + env, 'vpc_id': 'vpc-0123456789abcdef0',
         'master_secret_arn': 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:rds-master',
         'grafana_secret_arn': 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:grafana',
         'operations_topic_arn': 'arn:aws:sns:eu-west-1:123456789012:stocklane-operations',
         'application_log_group': '/stocklane/stocklane-' + env + '/containers'}
    c.update(extra)
    return c

def rendered(tmp_path, env='prod', platform=True, **extra):
    render(config(env, **extra), IMAGES, 's3://test-models/releases/model.tar.gz', 'f' * 64, tmp_path, platform=platform)
    return tmp_path / (env + '.yaml')

def chart(name, env, values):
    return build(name, env, values=values)

# ---------------------------------------------------------------- application chart
@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_environment_services_and_scalers_target_their_own_pods(env):
    docs = build('stocklane', env)
    validate_apps(docs, ENVIRONMENTS[env])
    validate_objects(docs, schemas())
    assert all(o['metadata'].get('namespace') == ENVIRONMENTS[env] for o in docs if o['kind'] != 'Namespace')
    pods = {o['metadata']['name']: o for o in docs if o['kind'] == 'Deployment'}
    for hpa in (o for o in docs if o['kind'] == 'HorizontalPodAutoscaler'):
        assert hpa['spec']['minReplicas'] == pods[hpa['metadata']['name']]['spec']['replicas']

@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_argo_applications_reference_projects_and_charts_for_the_same_environment(env):
    docs = build('argocd-apps', env)
    projects = {o['metadata']['name']: o for o in docs if o['kind'] == 'AppProject'}
    children = [o for o in docs if o['kind'] == 'Application']
    assert len(children) == 4
    for app in children:
        assert app['metadata']['name'].endswith('-' + env)
        assert app['spec']['project'] in projects
        chart_name = app['spec']['source']['path'].rsplit('/', 1)[-1]
        assert app['spec']['source']['path'] == 'deploy/helm/' + chart_name and (HELM / chart_name / 'Chart.yaml').exists()
        assert app['spec']['source']['helm']['valueFiles'] == ['../values/' + env + '.yaml']
        assert (HELM / 'values' / (env + '.yaml')).exists()
    workload = next(o for o in children if o['metadata']['name'].startswith('stocklane-workshop-'))
    assert workload['spec']['destination']['namespace'] == ENVIRONMENTS[env]
    assert int(workload['metadata']['annotations']['argocd.argoproj.io/sync-wave']) > 20
    waves = [int(o['metadata']['annotations']['argocd.argoproj.io/sync-wave']) for o in children]
    assert sorted(waves) == waves or len(set(waves)) == 4  # platform < operator < monitoring < application

@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_root_application_points_at_the_app_of_apps_chart(env):
    root = load_yaml(HELM / 'root' / (env + '.yaml'))
    assert root['spec']['source']['path'] == 'deploy/helm/argocd-apps'
    assert root['spec']['source']['helm']['valueFiles'] == ['../values/' + env + '.yaml']
    assert root['metadata']['name'] == 'stocklane-' + env

def test_renderer_preserves_charts_and_rolls_pods_when_the_model_changes(tmp_path):
    before = (HELM / 'stocklane/templates/services.yaml').read_bytes()
    values = rendered(tmp_path, platform=False)
    initial = chart('stocklane', 'prod', values)
    validate_apps(initial, 'stocklane-prod', configured=True)
    first = next(o for o in initial if o['kind'] == 'Deployment' and o['metadata']['name'] == 'vision')['spec']['template']['metadata']['annotations']['stocklane.io/config-sha256']
    render(config(), IMAGES, 's3://test-models/next.tar.gz', 'e' * 64, tmp_path)
    updated = chart('stocklane', 'prod', values)
    second = next(o for o in updated if o['kind'] == 'Deployment' and o['metadata']['name'] == 'vision')['spec']['template']['metadata']['annotations']['stocklane.io/config-sha256']
    assert first != second
    hook = next(o for o in updated if o['kind'] == 'Job')['spec']['template']['spec']
    for container in hook['containers'] + hook['initContainers']:
        env = {v['name']: v.get('value') for v in container['env']}
        assert env['MODEL_URI'] == 's3://test-models/next.tar.gz'
        assert env['MODEL_ARCHIVE_SHA256'] == 'e' * 64
    assert (HELM / 'stocklane/templates/services.yaml').read_bytes() == before

def test_renderer_rejects_an_environment_namespace_mismatch(tmp_path):
    with pytest.raises(ValueError, match='namespace'):
        render(config('dev', workload_namespace='stocklane'), {}, 's3://models/release.tar.gz', 'f' * 64, tmp_path)

def test_service_network_policy_is_scoped_and_uses_configured_cidr(tmp_path):
    values = rendered(tmp_path, platform=False, service_ipv4_cidr='172.21.0.0/16')
    docs = chart('stocklane', 'prod', values)
    policy = next(d for d in docs if d['kind'] == 'NetworkPolicy' and d['metadata']['name'] == 'workshop-to-inventory-service')
    assert policy['spec']['podSelector'] == {'matchExpressions': [{'key': 'app', 'operator': 'In', 'values': ['workshop', 'vision', 'vision-index', 'forecast']}]}
    assert policy['spec']['policyTypes'] == ['Egress']
    rule = policy['spec']['egress'][0]
    assert rule['ports'] == [{'protocol': 'TCP', 'port': 8081}]
    assert {'podSelector': {'matchLabels': {'app': 'inventory'}}} in rule['to']
    assert {'ipBlock': {'cidr': '172.21.0.0/16'}} in rule['to']
    assert '172.20.147.62' not in str(policy)

def test_external_secrets_keep_their_own_template_expressions_and_use_the_right_arns(tmp_path):
    docs = chart('stocklane', 'prod', rendered(tmp_path, platform=False))
    secrets = {d['metadata']['name']: d for d in docs if d['kind'] == 'ExternalSecret'}
    assert set(secrets) == {'inventory-secrets', 'workshop-secrets', 'vision-secrets', 'forecast-secrets'}
    inventory = secrets['inventory-secrets']['spec']
    assert inventory['target']['template']['data']['DATABASE_USER'] == '{{ .username }}'
    keys = {(e['secretKey'], e['remoteRef']['key']) for e in inventory['data']}
    assert ('username', 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:inventory') in keys
    assert ('INTERNAL_TOKEN', 'arn:aws:secretsmanager:eu-west-1:123456789012:secret:platform') in keys
    assert all('REPLACE_' not in json.dumps(d) for d in secrets.values())

# ---------------------------------------------------------------- vendored third-party charts
def test_imported_manifests_match_the_reviewed_lock_and_use_one_resource_per_file():
    verify_upstream()
    for chart_name in ('argocd', 'monitoring-operator', 'platform', 'monitoring'):
        for sub in ('files', 'crds'):
            for path in (HELM / chart_name / sub).glob('*.yaml'):
                docs = list(yaml.load_all(path.read_text(), Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader)))
                assert len(docs) == 1, str(path)
                assert docs[0].get('apiVersion') and docs[0].get('kind'), str(path)

def test_no_kustomize_files_remain():
    assert not list(ROOT.rglob('kustomization.yaml')) and not (ROOT / 'deploy/kubernetes').exists()

@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_metrics_server_budget_uses_supported_api_and_selects_only_metrics_pods(env):
    docs = build('platform', env)
    validate_objects(docs, schemas())
    pdb = next(o for o in docs if o['kind'] == 'PodDisruptionBudget' and o['metadata']['name'] == 'metrics-server')
    deployment = next(o for o in docs if o['kind'] == 'Deployment' and o['metadata']['name'] == 'metrics-server')
    assert pdb['apiVersion'] == 'policy/v1'
    assert pdb['metadata']['namespace'] == deployment['metadata']['namespace'] == 'kube-system'
    assert pdb['spec']['minAvailable'] == 1
    selector = pdb['spec']['selector']['matchLabels']
    assert selector == {'k8s-app': 'metrics-server'}
    assert all(deployment['spec']['template']['metadata']['labels'].get(k) == v for k, v in selector.items())
    assert deployment['spec']['replicas'] >= 2

def test_removed_budget_api_is_rejected_without_an_optional_schema_tool():
    legacy = load_yaml(HELM / 'platform/files/poddisruptionbudget-kube-system-metrics-server.yaml')
    legacy['apiVersion'] = 'policy/v1beta1'
    with pytest.raises(ValueError, match='must use policy/v1'):
        validate_objects([legacy], schemas())

def test_metrics_api_service_keeps_its_supported_beta_metrics_endpoint():
    docs = build('platform', 'dev')
    api = next(o for o in docs if o['kind'] == 'APIService' and o['metadata']['name'] == 'v1beta1.metrics.k8s.io')
    assert api['apiVersion'] == 'apiregistration.k8s.io/v1'
    assert api['spec']['group'] == 'metrics.k8s.io' and api['spec']['version'] == 'v1beta1'

def test_crds_install_from_the_crds_directory_and_schema_validation_accepts_pinned_specs_only():
    assert len(crd_definitions()) > 40
    rendered_crds = [o for o in build('platform', 'dev') if o['kind'] == 'CustomResourceDefinition']
    assert rendered_crds and len(rendered_crds) == len(list((HELM / 'platform/crds').glob('*.yaml')))
    original = next(iter(crd_definitions().values()))
    metadata_only = copy.deepcopy(original)
    metadata_only['metadata'].setdefault('annotations', {})['argocd.argoproj.io/sync-wave'] = '-20'
    validate_objects([metadata_only], schemas())
    changed = copy.deepcopy(original)
    changed['spec']['scope'] = 'Cluster' if original['spec']['scope'] == 'Namespaced' else 'Namespaced'
    with pytest.raises(ValueError, match='Unpinned or modified CustomResourceDefinition'):
        validate_objects([changed], schemas())
    unknown = copy.deepcopy(original)
    unknown['metadata']['name'] = 'unreviewed.example.com'
    with pytest.raises(ValueError, match='Unpinned or modified CustomResourceDefinition'):
        validate_objects([unknown], schemas())

# ---------------------------------------------------------------- whole account
def test_full_account_render_wires_platform_monitoring_and_bootstrap(tmp_path):
    values = rendered(tmp_path)
    counts = validate_environment('prod', configured=True, values=values)
    assert counts['platform'] > 20 and counts['monitoring'] > 10 and counts['bootstrap'] == 3
    docs = chart('platform', 'prod', values)
    args = next(o for o in docs if o['kind'] == 'Deployment' and o['metadata']['name'] == 'aws-load-balancer-controller')['spec']['template']['spec']['containers'][0]['args']
    assert '--cluster-name=stocklane-prod' in args and '--aws-region=eu-west-1' in args and '--aws-vpc-id=vpc-0123456789abcdef0' in args
    store = next(o for o in docs if o['kind'] == 'ClusterSecretStore')
    assert store['spec']['provider']['aws']['region'] == 'eu-west-1'
    logs = next(o for o in docs if o['kind'] == 'DaemonSet' and o['metadata']['name'] == 'fluent-bit')['spec']['template']['spec']['containers'][0]['env']
    assert {'name': 'LOG_GROUP_NAME', 'value': '/stocklane/stocklane-prod/containers'} in logs
    job = next(o for o in chart('bootstrap', 'prod', values) if o['kind'] == 'ConfigMap')
    assert json.loads(job['data']['DATABASE_SECRETS']) == config()['database_secrets']

def test_unconfigured_charts_are_rejected_before_a_deploy():
    with pytest.raises(AssertionError):
        validate_environment('dev', configured=True, apps_only=False)

# ---------------------------------------------------------------- admin access
def test_admin_ingresses_use_separate_restricted_alb_and_correct_backend_tls(tmp_path):
    values = rendered(tmp_path, 'dev', argocd_domain='argocd-stocklane.example.com', grafana_domain='grafana-stocklane.example.com',
                      admin_allowed_cidrs=['203.0.113.7/32'], admin_certificate_arn='arn:aws:acm:ap-southeast-2:123456789012:certificate/test')
    ingresses = {o['metadata']['name']: o for o in chart('platform', 'dev', values) if o['kind'] == 'Ingress'}
    assert set(ingresses) == {'admin-argocd', 'admin-grafana'}
    for ingress in ingresses.values():
        annotations = ingress['metadata']['annotations']
        assert annotations['alb.ingress.kubernetes.io/group.name'] == 'stocklane-dev-admin'
        assert annotations['alb.ingress.kubernetes.io/inbound-cidrs'] == '203.0.113.7/32'
        assert annotations['alb.ingress.kubernetes.io/listen-ports'] == '[{"HTTPS":443}]'
    assert ingresses['admin-argocd']['metadata']['namespace'] == 'argocd'
    assert ingresses['admin-argocd']['metadata']['annotations']['alb.ingress.kubernetes.io/backend-protocol'] == 'HTTPS'
    assert ingresses['admin-grafana']['metadata']['namespace'] == 'monitoring'
    assert ingresses['admin-grafana']['metadata']['annotations']['alb.ingress.kubernetes.io/backend-protocol'] == 'HTTP'
    grafana = next(o for o in chart('monitoring', 'dev', values) if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    env = grafana['spec']['template']['spec']['containers'][0]['env']
    assert {'name': 'GF_SECURITY_COOKIE_SECURE', 'value': 'true'} in env
    assert {'name': 'GF_SERVER_ROOT_URL', 'value': 'https://grafana-stocklane.example.com/'} in env

def test_admin_pages_are_not_published_without_a_domain(tmp_path):
    values = rendered(tmp_path, 'dev')
    assert not [o for o in chart('platform', 'dev', values) if o['kind'] == 'Ingress']
    grafana = next(o for o in chart('monitoring', 'dev', values) if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    assert not any(e['name'] == 'GF_SERVER_ROOT_URL' for e in grafana['spec']['template']['spec']['containers'][0]['env'])

def test_admin_hosts_cannot_be_rendered_without_access_restriction(tmp_path):
    with pytest.raises(ValueError, match='CIDRs'):
        rendered(tmp_path, 'dev', argocd_domain='argocd.example.com')
    with pytest.raises(ValueError, match='/24 or narrower'):
        rendered(tmp_path, 'dev', argocd_domain='argocd.example.com', admin_allowed_cidrs=['10.0.0.0/8'], admin_certificate_arn='arn:aws:acm:x')

# ---------------------------------------------------------------- monitoring
def grafana_parts(objects):
    deployment = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    pod = deployment['spec']['template']['spec']
    name = next(v for v in pod['volumes'] if v['name'] == 'datasources')['configMap']['name']
    return deployment, pod, next(o for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['name'] == name)

@pytest.mark.parametrize('env', ENVIRONMENTS)
def test_every_environment_provisions_the_datasource_referenced_by_its_panels(env, tmp_path):
    objects = chart('monitoring', env, rendered(tmp_path, env))
    deployment, pod, configmap = grafana_parts(objects)
    assert configmap['metadata']['name'] == 'grafana-datasources'
    assert re.fullmatch('[a-f0-9]{64}', deployment['spec']['template']['metadata']['annotations']['stocklane.io/provisioning-sha256'])
    datasource = yaml.safe_load(configmap['data']['datasources.yaml'])['datasources'][0]
    assert datasource['uid'] == 'prometheus' and datasource['orgId'] == 1
    assert datasource['url'] == 'http://prometheus.monitoring.svc.cluster.local:9090'
    grafana = next(c for c in pod['containers'] if c['name'] == 'grafana')
    assert {'name': 'GF_PATHS_PROVISIONING', 'value': '/etc/grafana/provisioning'} in grafana['env']
    assert next(v for v in grafana['volumeMounts'] if v['name'] == 'datasources')['mountPath'] == '/etc/grafana/provisioning/datasources'
    dashboard = next(o for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'stocklane-dashboards')
    for panel in json.loads(dashboard['data']['stocklane.json'])['panels']:
        assert panel['datasource']['uid'] == datasource['uid']

def test_prod_monitoring_keeps_persistent_data_and_private_admin_access(tmp_path):
    docs = chart('monitoring', 'prod', rendered(tmp_path, 'prod'))
    validate_objects(docs, schemas())
    assert next(o for o in docs if o['kind'] == 'Prometheus')['spec']['replicas'] == 2
    assert next(o for o in docs if o['kind'] == 'Alertmanager')['spec']['replicas'] == 3
    pdbs = {o['metadata']['name']: o['spec']['minAvailable'] for o in docs if o['kind'] == 'PodDisruptionBudget'}
    assert pdbs == {'stocklane-prometheus': 1, 'stocklane-alertmanager': 2}
    claim = next(o for o in docs if o['kind'] == 'PersistentVolumeClaim')
    assert claim['spec']['storageClassName'] == 'gp3'
    grafana = next(o for o in docs if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    assert grafana['spec']['strategy']['type'] == 'Recreate'
    password = next(v for v in grafana['spec']['template']['spec']['containers'][0]['env'] if v['name'] == 'GF_SECURITY_ADMIN_PASSWORD')
    assert 'secretKeyRef' in password['valueFrom']
    assert not any(o['kind'] == 'Ingress' or (o['kind'] == 'Service' and o['spec'].get('type') == 'LoadBalancer') for o in docs)

def test_alertmanager_sends_every_alert_to_the_operations_topic(tmp_path):
    docs = chart('monitoring', 'dev', rendered(tmp_path, 'dev'))
    secret = next(o for o in docs if o['kind'] == 'Secret' and o['metadata']['name'] == 'alertmanager-stocklane')
    settings = yaml.safe_load(base64.b64decode(secret['data']['alertmanager.yaml']))
    assert settings['route']['receiver'] == 'operations'
    receiver = settings['receivers'][0]['sns_configs'][0]
    assert receiver['topic_arn'] == 'arn:aws:sns:eu-west-1:123456789012:stocklane-operations'
    assert receiver['sigv4'] == {'region': 'eu-west-1'} and receiver['send_resolved'] is True

def test_datasource_changes_roll_grafana_and_rollback_restores_the_pod_template(tmp_path):
    values = rendered(tmp_path, 'dev')
    copy_root = tmp_path / 'charts'
    shutil.copytree(HELM / 'monitoring', copy_root / 'monitoring')
    def grafana():
        docs = template('monitoring', 'dev', values=values, root=copy_root)
        return next(o for o in docs if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    first = grafana()
    source = copy_root / 'monitoring/files/configmap-monitoring-grafana-datasources.yaml'
    original = source.read_text()
    source.write_text(original.replace('prometheus.monitoring.svc.cluster.local', 'prometheus-new.monitoring.svc.cluster.local'))
    second = grafana()
    assert second['spec']['template'] != first['spec']['template']
    source.write_text(original)
    assert grafana()['spec']['template'] == first['spec']['template']

# ---------------------------------------------------------------- charts as a whole
@pytest.mark.parametrize('name', CHARTS)
def test_every_chart_renders_with_its_defaults_and_placeholder_values(name):
    for env in ENVIRONMENTS:
        docs = build(name, env)
        assert docs and all(d.get('apiVersion') and d.get('kind') for d in docs)

def test_templates_only_use_functions_that_exist_in_helm():
    """The charts must stay renderable by real Helm: only sprig/Helm functions on this list may be used."""
    allowed = {'include', 'toYaml', 'toJson', 'nindent', 'indent', 'default', 'required', 'quote', 'sha256sum', 'join', 'list',
               'dict', 'index', 'max', 'sub', 'int', 'b64enc', 'print', 'printf', 'range', 'if', 'else', 'end', 'with', 'define',
               'template', 'not', 'and', 'or', 'eq', 'ne', 'len', 'hasKey', 'lower', 'upper', 'trunc', 'replace'}
    found = set()
    for path in HELM.glob('*/templates/*'):
        text = re.sub(r'\{\{-?\s*/\*.*?\*/\s*-?\}\}', '', path.read_text(), flags=re.S)
        for action in re.findall(r'\{\{-?(.*?)-?\}\}', text, flags=re.S):
            action = re.sub(r'"[^"]*"|`[^`]*`', '', action)
            for word in re.findall(r'(?<![\w.$])([a-zA-Z][\w]*)(?![\w:])', action):
                if word[0].islower() and word not in {'true', 'false', 'nil'}:
                    found.add(word)
    unknown = {w for w in found if w not in allowed}
    assert not unknown, 'Template functions not on the reviewed list: ' + ', '.join(sorted(unknown))

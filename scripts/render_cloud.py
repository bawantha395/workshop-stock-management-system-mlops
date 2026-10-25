#!/usr/bin/env python3
"""Write account-specific Kustomize patches; reviewed base YAML stays unchanged.
Only public configuration, secret ARNs, image digests and artifact checksums are
written. Kubernetes Secrets are populated inside EKS by External Secrets.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from kustomize_utils import ROOT, KUBERNETES, PROFILES, environment, load_yaml, write_yaml

SERVICES = ('inventory', 'workshop', 'vision')

def patch(api, kind, name, **body):
    return {'apiVersion': api, 'kind': kind, 'metadata': {'name': name}, **body}

def render(config, images, model_uri, model_sha, destination=None, *, platform=False):
    c = config.get('deployment', {}).get('value', config)
    env, namespace = environment(c)
    for service in (*SERVICES, 'operations'):
        if not re.fullmatch(r'.+@sha256:[a-f0-9]{64}', images[service]):
            raise ValueError('Every image must use an immutable digest: ' + service)
    if not model_uri.startswith('s3://') or not re.fullmatch('[a-f0-9]{64}', model_sha):
        raise ValueError('A checksum-bound S3 model bundle is required')
    if urlparse(c['frontend_url']).scheme != 'https' or urlparse(c['cognito_issuer']).scheme != 'https':
        raise ValueError('Cloud frontend and Cognito URLs require HTTPS')
    if not re.fullmatch(r'[a-z0-9.-]+', c['api_domain']):
        raise ValueError('API domain must be a hostname')
    replicas = int(c.get('application_replicas', PROFILES[env][0]))
    maximum = max(PROFILES[env][1], replicas)
    if not 1 <= replicas <= 6:
        raise ValueError('Application replicas must be between one and six')
    dest = Path(destination) if destination else KUBERNETES / 'apps/overlays' / env
    dest.mkdir(parents=True, exist_ok=True)
    base = KUBERNETES / 'apps/base'
    common = copy.deepcopy(load_yaml(base / 'shared/configmap.yaml')['data'])
    common.update({
        'AWS_REGION': c['region'], 'DEPLOYMENT_ENVIRONMENT': env,
        'COGNITO_ISSUER': c['cognito_issuer'],
        'COGNITO_CLIENT_IDS': c['cognito_web_client_id'] + ',' + c['cognito_camera_client_id'],
        'APP_WEB_ORIGIN': c['frontend_url'], 'WEB_ORIGIN': c['frontend_url'],
        'STOCK_QUEUE_URL': c['stock_queue_url'], 'CATALOGUE_QUEUE_URL': c['catalogue_queue_url'],
        'REDIS_HOST': c['cache_host'], 'MEDIA_BUCKET': c['media_bucket'],
        'MODEL_URI': model_uri, 'MODEL_ARCHIVE_SHA256': model_sha,
        'BEDROCK_MODEL_ID': c.get('bedrock_model_id', ''),
    })
    patches = []
    def save(name, obj):
        path = 'patches/' + name + '.yaml'
        write_yaml(dest / path, obj)
        patches.append({'path': path})
    write_yaml(dest / 'namespace.yaml', {
        'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': namespace, 'labels': {
            'pod-security.kubernetes.io/enforce': 'restricted',
            'stocklane.io/environment': env, 'stocklane.io/monitoring': 'enabled'}}})
    save('configmap', patch('v1', 'ConfigMap', 'platform-config', data=common))
    checksum = hashlib.sha256(json.dumps(common, sort_keys=True).encode()).hexdigest()
    for service in SERVICES:
        save(service + '-deployment', patch('apps/v1', 'Deployment', service, spec={
            'replicas': replicas, 'template': {'metadata': {'annotations': {'stocklane.io/config-sha256': checksum}}}}))
        save(service + '-hpa', patch('autoscaling/v2', 'HorizontalPodAutoscaler', service,
                                    spec={'minReplicas': replicas, 'maxReplicas': maximum}))
        save(service + '-pdb', patch('policy/v1', 'PodDisruptionBudget', service,
                                    spec={'minAvailable': max(0, replicas - 1)}))
        spec = load_yaml(base / service / 'external-secret.yaml')['spec']
        data = copy.deepcopy(spec['data'])
        for entry in data:
            key = entry['remoteRef']['key']
            entry['remoteRef']['key'] = c['platform_secret_arn'] if key == 'REPLACE_PLATFORM_SECRET_ARN' else c['database_secrets'][service]
        save(service + '-external-secret', patch('external-secrets.io/v1', 'ExternalSecret', service + '-secrets', spec={'data': data}))
    ingress = copy.deepcopy(load_yaml(base / 'shared/ingress.yaml'))
    ingress['spec']['rules'][0]['host'] = c['api_domain']
    ingress['metadata']['annotations']['alb.ingress.kubernetes.io/certificate-arn'] = c['api_certificate_arn']
    save('ingress', ingress)
    # PreSync runs before the new shared ConfigMap is applied. Bind the hook
    # directly to this release's public configuration so it indexes the new
    # encoder, rather than reading the previous release's model URI.
    hook_env = [{'name': key, 'value': value} for key, value in common.items()]
    worker_env = hook_env + [
        {'name': 'DATABASE_SCHEMA', 'value': 'vision'},
        {'name': 'PYTHONPATH', 'value': '/app'},
        {'name': 'REDIS_URL', 'value': 'rediss://:$(REDIS_PASSWORD)@$(REDIS_HOST):6379/0?ssl_cert_reqs=required&ssl_check_hostname=true'},
    ]
    save('model-index-job', patch('batch/v1', 'Job', 'prepare-model-index', spec={
        'template': {'spec': {
            'initContainers': [{'name': 'fetch-model', 'env': hook_env}],
            'containers': [{'name': 'vision', 'env': worker_env}],
        }},
    }))
    image_rules = []
    for service in (*SERVICES, 'operations'):
        name, digest = images[service].rsplit('@', 1)
        image_rules.append({'name': 'stocklane/' + service, 'newName': name, 'digest': digest})
    write_yaml(dest / 'kustomization.yaml', {
        'apiVersion': 'kustomize.config.k8s.io/v1beta1', 'kind': 'Kustomization',
        'namespace': namespace, 'resources': [os.path.relpath(base, dest), 'namespace.yaml'],
        'patches': patches, 'images': image_rules,
        'labels': [{'pairs': {'stocklane.io/environment': env}, 'includeSelectors': False}],
    })
    (dest / 'images.json').write_text(json.dumps(images, indent=2) + '\n')
    (dest / 'release.json').write_text(json.dumps({'schemaVersion': 2, 'environment': env, 'namespace': namespace,
        'model': {'uri': model_uri, 'sha256': model_sha}}, indent=2) + '\n')
    runtime = {'authMode': 'cognito', 'authority': c['cognito_issuer'], 'clientId': c['cognito_web_client_id'],
        'scope': 'openid email profile', 'apiBase': 'https://' + c['api_domain'],
        'logoutUrl': c.get('cognito_token_url', '').replace('/oauth2/token', '/logout')}
    (dest / 'config.js').write_text('window.STOCKLANE_CONFIG = ' + json.dumps(runtime) + ';\n')
    if platform:
        render_platform(c, images, env, namespace)
    print('Rendered separate Kustomize patches:', dest)
    return dest

def render_platform(c, images, env, namespace):
    folder = KUBERNETES / 'platform/overlays' / env
    alb = load_yaml(folder / 'alb-deployment-patch.yaml')
    args = alb['spec']['template']['spec']['containers'][0]['args']
    values = {'--cluster-name=': c['cluster_name'], '--aws-region=': c['region'], '--aws-vpc-id=': c['vpc_id']}
    for i, arg in enumerate(args):
        for prefix, value in values.items():
            if arg.startswith(prefix): args[i] = prefix + value
    write_yaml(folder / 'alb-deployment-patch.yaml', alb)
    store = load_yaml(folder / 'secretstore-patch.yaml'); store['spec']['provider']['aws']['region'] = c['region']
    write_yaml(folder / 'secretstore-patch.yaml', store)
    logs = load_yaml(folder / 'fluent-bit-patch.yaml')
    for entry in logs['spec']['template']['spec']['containers'][0]['env']:
        entry['value'] = c['region'] if entry['name'] == 'AWS_REGION' else c['application_log_group']
    write_yaml(folder / 'fluent-bit-patch.yaml', logs)
    folder = KUBERNETES / 'monitoring/overlays' / env
    grafana = copy.deepcopy(load_yaml(KUBERNETES / 'monitoring/base/grafana/external-secret.yaml'))
    for item in grafana['spec']['data']:item['remoteRef']['key'] = c['grafana_secret_arn']
    write_yaml(folder / 'grafana-secret-patch.yaml', grafana)
    config = {'global': {'resolve_timeout': '5m'}, 'route': {'receiver': 'operations',
        'group_by': ['namespace', 'alertname'], 'group_wait': '30s', 'group_interval': '5m', 'repeat_interval': '4h'},
        'receivers': [{'name': 'operations', 'sns_configs': [{'topic_arn': c['operations_topic_arn'],
            'sigv4': {'region': c['region']}, 'send_resolved': True}]}]}
    encoded = base64.b64encode(__import__('yaml').safe_dump(config, sort_keys=False).encode()).decode()
    write_yaml(folder / 'alertmanager-secret-patch.yaml', patch('v1', 'Secret', 'alertmanager-stocklane', data={'alertmanager.yaml': encoded}))
    k = load_yaml(folder / 'kustomization.yaml')
    for name in ['grafana-secret-patch.yaml', 'alertmanager-secret-patch.yaml']:
        if {'path': name} not in k['patches']:k['patches'].append({'path': name})
    write_yaml(folder / 'kustomization.yaml', k)
    repository = 'https://github.com/' + c.get('github_repository', 'bawantha395/workshop-stock-management-system-mlops') + '.git'
    apps = KUBERNETES / 'argocd/applications/overlays' / env
    for name in ['platform', 'monitoring-operator', 'monitoring', 'workshop']:
        obj = load_yaml(apps / (name + '-patch.yaml')); obj['spec']['source']['repoURL'] = repository
        write_yaml(apps / (name + '-patch.yaml'), obj)
    k = load_yaml(apps / 'kustomization.yaml')
    for name in ['platform', 'app']:
        obj = patch('argoproj.io/v1alpha1', 'AppProject', 'stocklane-' + name, spec={'sourceRepos': [repository]})
        obj['metadata']['namespace'] = 'argocd'
        filename = name + '-repository-patch.yaml'; write_yaml(apps / filename, obj)
        if {'path': filename} not in k['patches']:k['patches'].append({'path': filename})
    write_yaml(apps / 'kustomization.yaml', k)
    root = KUBERNETES / 'argocd/root' / (env + '.yaml')
    obj = load_yaml(root); obj['spec']['source']['repoURL'] = repository; write_yaml(root, obj)
    # Initial database bootstrap is an operator action, using the reviewed operations image.
    folder = KUBERNETES / 'bootstrap/overlays' / env
    values = {'AWS_REGION': c['region'], 'DATABASE_HOST': c['database_host'],
        'MASTER_SECRET_ARN': c['master_secret_arn'], 'DATABASE_SECRETS': json.dumps(c['database_secrets'])}
    write_yaml(folder / 'configmap.yaml', patch('v1', 'ConfigMap', 'database-bootstrap-config', data=values))
    image, digest = images['operations'].rsplit('@', 1)
    write_yaml(folder / 'kustomization.yaml', {'apiVersion': 'kustomize.config.k8s.io/v1beta1', 'kind': 'Kustomization',
        'namespace': namespace, 'resources': ['../../base', 'configmap.yaml'],
        'images': [{'name': 'stocklane/operations', 'newName': image, 'digest': digest}]})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True); parser.add_argument('--images', required=True)
    parser.add_argument('--model-uri', required=True); parser.add_argument('--model-sha256', required=True)
    parser.add_argument('--destination'); parser.add_argument('--platform', action='store_true')
    a = parser.parse_args()
    render(json.loads(Path(a.config).read_text()), json.loads(Path(a.images).read_text()), a.model_uri,
           a.model_sha256, a.destination, platform=a.platform)

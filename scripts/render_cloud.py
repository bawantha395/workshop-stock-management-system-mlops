#!/usr/bin/env python3
"""Write the account-specific Helm values of one environment; the reviewed charts stay unchanged.

Only public configuration, secret ARNs, image digests and artifact checksums are written to
deploy/helm/values/<environment>.yaml. Kubernetes Secrets are populated inside EKS by External Secrets.
Every chart reads this one file (Argo CD passes it with helm.valueFiles).
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from helm_utils import ROOT, HELM, PROFILES, environment, write_yaml

SERVICES = ('inventory', 'workshop', 'vision', 'forecast')
REPOSITORY = 'bawantha395/workshop-stock-management-system-mlops'

def render(config, images, model_uri, model_sha, destination=None, *, platform=False):
    """Write <environment>.yaml (values) plus images.json, release.json and config.js.

    destination=None writes into deploy/helm/values and deploy/helm/releases/<environment>; a directory
    writes everything there (used by tests). platform=True also writes the sections only the cluster
    bootstrap needs: controllers, monitoring, database initialisation and the GitOps applications.
    """
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
    values_dir = Path(destination) if destination else HELM / 'values'
    release_dir = Path(destination) if destination else HELM / 'releases' / env
    values_dir.mkdir(parents=True, exist_ok=True); release_dir.mkdir(parents=True, exist_ok=True)

    values = {
        'environment': env,
        'images': {service: images[service] for service in SERVICES},
        'replicas': {'min': replicas, 'max': maximum},
        # Egress can be evaluated before Service DNAT: permit the declared Service range as well as Inventory pods.
        'serviceCidr': str(ipaddress.IPv4Network(c.get('service_ipv4_cidr', '172.20.0.0/16'))),
        'ingress': {'host': c['api_domain'], 'certificateArn': c['api_certificate_arn']},
        'secrets': {'platform': c['platform_secret_arn'],
                    'database': {s: c['database_secrets'][s] for s in ('inventory', 'workshop', 'vision')}},
        'config': {
            'AWS_REGION': c['region'], 'DEPLOYMENT_ENVIRONMENT': env,
            'COGNITO_ISSUER': c['cognito_issuer'], 'COGNITO_CLIENT_IDS': c['cognito_web_client_id'],
            'APP_WEB_ORIGIN': c['frontend_url'], 'WEB_ORIGIN': c['frontend_url'],
            'STOCK_QUEUE_URL': c['stock_queue_url'], 'CATALOGUE_QUEUE_URL': c['catalogue_queue_url'],
            'REDIS_HOST': c['cache_host'], 'MEDIA_BUCKET': c['media_bucket'],
            'MODEL_BUCKET': c.get('model_bucket', ''),
            'MODEL_URI': model_uri, 'MODEL_ARCHIVE_SHA256': model_sha,
            'BEDROCK_MODEL_ID': c.get('bedrock_model_id', ''),
            'BEDROCK_REGION': c.get('bedrock_region', ''),
            'BEDROCK_DAILY_REQUEST_LIMIT': str(c.get('bedrock_daily_request_limit', 50)),
        },
    }
    if platform:
        values.update(platform_values(c, images, env, namespace))
    write_yaml(values_dir / (env + '.yaml'), values)
    (release_dir / 'images.json').write_text(json.dumps(images, indent=2) + '\n')
    (release_dir / 'release.json').write_text(json.dumps({'schemaVersion': 3, 'environment': env, 'namespace': namespace,
        'model': {'uri': model_uri, 'sha256': model_sha}}, indent=2) + '\n')
    runtime = {'authMode': 'cognito', 'authority': c['cognito_issuer'], 'clientId': c['cognito_web_client_id'],
        'scope': 'openid email profile', 'apiBase': 'https://' + c['api_domain'],
        'logoutUrl': c.get('cognito_token_url', '').replace('/oauth2/token', '/logout')}
    (release_dir / 'config.js').write_text('window.STOCKLANE_CONFIG = ' + json.dumps(runtime) + ';\n')
    if platform and not destination:
        write_root_application(c, env)
    print('Rendered Helm values:', values_dir / (env + '.yaml'))
    return values_dir

def platform_values(c, images, env, namespace):
    repository = 'https://github.com/' + c.get('github_repository', REPOSITORY) + '.git'
    ranges = c.get('admin_allowed_cidrs', [])
    hosts = {name: c.get(name + '_domain', '') for name in ('argocd', 'grafana')}
    if any(hosts.values()):
        if not ranges or not c.get('admin_certificate_arn'):
            raise ValueError('Admin domains require allowed public CIDRs and a validated regional certificate')
        for network in ranges:
            if ipaddress.IPv4Network(network, strict=False).prefixlen < 24:
                raise ValueError('Admin network ranges must be /24 or narrower')
    production = env == 'prod'
    return {
        'platform': {
            'name': c['name'], 'clusterName': c['cluster_name'], 'region': c['region'], 'vpcId': c['vpc_id'],
            'logGroup': c['application_log_group'],
            'admin': {'hosts': hosts, 'certificateArn': c.get('admin_certificate_arn', ''), 'allowedCidrs': ranges},
        },
        'monitoring': {
            'region': c['region'], 'operationsTopicArn': c['operations_topic_arn'],
            'grafanaSecretArn': c['grafana_secret_arn'], 'grafanaDomain': c.get('grafana_domain', ''),
            'prometheus': {'replicas': 2 if production else 1, 'minAvailable': 1 if production else 0},
            'alertmanager': {'replicas': 3 if production else 1, 'minAvailable': 2 if production else 0},
        },
        'bootstrap': {
            'image': images['operations'], 'region': c['region'], 'databaseHost': c['database_host'],
            'masterSecretArn': c['master_secret_arn'], 'databaseSecrets': json.dumps(c['database_secrets']),
        },
        'gitops': {'repoURL': repository, 'targetRevision': 'main', 'namespace': namespace},
    }

def write_root_application(c, env):
    """The one object the operator creates; Argo CD then creates the projects and applications from the chart."""
    repository = 'https://github.com/' + c.get('github_repository', REPOSITORY) + '.git'
    write_yaml(HELM / 'root' / (env + '.yaml'), {
        'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
        'metadata': {'name': 'stocklane-' + env, 'namespace': 'argocd'},
        'spec': {
            'project': 'default',
            'source': {'repoURL': repository, 'targetRevision': 'main', 'path': 'deploy/helm/argocd-apps',
                       'helm': {'valueFiles': ['../values/' + env + '.yaml']}},
            'destination': {'server': 'https://kubernetes.default.svc', 'namespace': 'argocd'},
            'syncPolicy': {'automated': {'prune': False, 'selfHeal': True}, 'syncOptions': ['ServerSideApply=true']},
        },
    })

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True); parser.add_argument('--images', required=True)
    parser.add_argument('--model-uri', required=True); parser.add_argument('--model-sha256', required=True)
    parser.add_argument('--destination'); parser.add_argument('--platform', action='store_true')
    a = parser.parse_args()
    render(json.loads(Path(a.config).read_text()), json.loads(Path(a.images).read_text()), a.model_uri,
           a.model_sha256, a.destination, platform=a.platform)

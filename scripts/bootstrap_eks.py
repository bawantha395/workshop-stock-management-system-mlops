#!/usr/bin/env python3
"""Initial operator bootstrap using only kubectl + Kustomize, then Argo CD.
Requires reviewed Terraform outputs and a merged, configured release overlay.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
import yaml
from kustomize_utils import ROOT, KUBERNETES, build, environment

# bcrypt hash of the password "admin" (a public value, not a secret). Used only when
# the environment sets demo_admin_credentials (dev and staging), never for prod.
DEMO_ADMIN_PASSWORD_HASH = '$2a$10$WUNS8hj1oO465/z9/ebc0.h4u8m1PKQTSkuOljKTnXhr1bnVR1ClK'

def demo_admin_patch(now=None):
    """Strategic-merge patch that sets the Argo CD admin password to "admin"."""
    stamp = now or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    return {'stringData': {'admin.password': DEMO_ADMIN_PASSWORD_HASH, 'admin.passwordMtime': stamp}}

def bootstrap(a):
    config = json.loads(Path(a.config).read_text())
    c = config.get('deployment', {}).get('value', config)
    target, namespace = environment(c)
    directory = ROOT / 'deploy/generated'; directory.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy(); env['KUBECONFIG'] = str(directory / 'kubeconfig')
    def run(args, **kw): return subprocess.run(args, env=env, check=True, **kw)
    actual = json.loads(subprocess.check_output(['aws', 'sts', 'get-caller-identity'], env=env))['Account']
    if actual != c['account_id']: raise RuntimeError('AWS account does not match Terraform outputs')
    overlay = KUBERNETES / 'apps/overlays' / target
    # Validate platform/controller manifests as well as application configuration
    # before contacting Kubernetes, including when invoked directly in CodeBuild.
    run(['python3', str(ROOT / 'scripts/validate_kustomize.py'), '--environment', target, '--configured'])
    run(['aws', 'eks', 'update-kubeconfig', '--region', c['region'], '--name', c['cluster_name'], '--kubeconfig', env['KUBECONFIG']])
    def apply(docs):
        if docs: run(['kubectl', 'apply', '--server-side', '--field-manager=argocd-controller', '-f', '-'], input=yaml.safe_dump_all(docs).encode())
    def crds(docs):
        for doc in docs:
            if doc['kind'] == 'CustomResourceDefinition': run(['kubectl', 'wait', '--for=condition=Established', 'crd/' + doc['metadata']['name'], '--timeout=180s'])
    def rollout(docs):
        for doc in docs:
            if doc['kind'] in ['Deployment', 'StatefulSet']:
                kind = doc['kind'].lower(); ns = doc['metadata'].get('namespace', 'default')
                run(['kubectl', '-n', ns, 'rollout', 'status', kind + '/' + doc['metadata']['name'], '--timeout=300s'])
    core = build(KUBERNETES / 'platform/overlays' / target)
    apply([d for d in core if d['kind'] == 'Namespace'])
    apply([d for d in core if d['kind'] == 'CustomResourceDefinition']); crds(core)
    deferred = {'Certificate', 'Issuer', 'ClusterIssuer', 'ClusterSecretStore'}
    apply([d for d in core if d['kind'] not in deferred | {'Namespace', 'CustomResourceDefinition', 'Ingress'}])
    rollout([d for d in core if d['kind'] == 'Deployment' and d['metadata'].get('namespace') == 'cert-manager'])
    apply([d for d in core if d['kind'] in {'Issuer', 'ClusterIssuer', 'Certificate'}])
    rollout([d for d in core if d['kind'] == 'Deployment' and d['metadata'].get('namespace') != 'cert-manager'])
    apply([d for d in core if d['kind'] == 'ClusterSecretStore'])
    run(['kubectl', 'wait', '--for=condition=Ready', 'clustersecretstore/aws-secrets', '--timeout=180s'])
    argo = build(KUBERNETES / 'argocd/base')
    apply([d for d in argo if d['kind'] in {'Namespace', 'CustomResourceDefinition'}]); crds(argo)
    apply([d for d in argo if d['kind'] not in {'Namespace', 'CustomResourceDefinition'}]); rollout(argo)
    if c.get('demo_admin_credentials') is True and target != 'prod':
        # Argo CD reads this secret live; the first-start password in argocd-initial-admin-secret is replaced.
        run(['kubectl', '-n', 'argocd', 'patch', 'secret', 'argocd-secret', '--type=merge', '-p', json.dumps(demo_admin_patch())])
        subprocess.run(['kubectl', '-n', 'argocd', 'delete', 'secret', 'argocd-initial-admin-secret', '--ignore-not-found'], env=env, check=False)
        print('Argo CD admin password set to the demo value (admin)')
    operator = build(KUBERNETES / 'monitoring-operator/overlays' / target)
    apply([d for d in operator if d['kind'] in {'Namespace', 'CustomResourceDefinition'}]); crds(operator)
    apply([d for d in operator if d['kind'] not in {'Namespace', 'CustomResourceDefinition'}]); rollout(operator)
    monitoring = build(KUBERNETES / 'monitoring/overlays' / target); apply(monitoring)
    run(['kubectl', '-n', 'monitoring', 'wait', '--for=condition=Ready', 'externalsecret/grafana-admin', '--timeout=180s'])
    rollout([d for d in monitoring if d['kind'] == 'Deployment'])
    if c.get('demo_admin_credentials') is True and target != 'prod':
        # Grafana reads its admin password only when it first creates its database, so an
        # existing Grafana keeps the old one; reset it explicitly (best effort, safe to repeat).
        reset = subprocess.run(['kubectl', '-n', 'monitoring', 'exec', 'deploy/grafana', '--', 'grafana', 'cli', 'admin', 'reset-admin-password', 'admin'], env=env, capture_output=True, text=True)
        print('Grafana admin password set to the demo value (admin)' if reset.returncode == 0 else 'Could not reset the Grafana admin password: ' + (reset.stderr or reset.stdout).strip()[-300:])
    # Admin namespaces exist only after Argo CD and monitoring bootstrap.
    apply([d for d in core if d['kind'] == 'Ingress'])
    resources = build(overlay)
    apply([d for d in resources if d['kind'] in {'Namespace', 'ServiceAccount', 'ConfigMap', 'ExternalSecret', 'NetworkPolicy'}])
    for name in ['inventory', 'workshop', 'vision', 'forecast']:
        run(['kubectl', '-n', namespace, 'wait', '--for=condition=Ready', 'externalsecret/' + name + '-secrets', '--timeout=180s'])
    jobs = build(KUBERNETES / 'bootstrap/overlays' / target)
    # A completed initialisation is retained; password rotation is a separate operator procedure.
    existing = subprocess.run(['kubectl', '-n', namespace, 'get', 'job/database-bootstrap', '-o', 'json'], env=env, capture_output=True)
    if existing.returncode:
        apply(jobs)
        run(['kubectl', '-n', namespace, 'wait', '--for=condition=Complete', 'job/database-bootstrap', '--timeout=300s'])
    elif not json.loads(existing.stdout).get('status', {}).get('succeeded'):
        raise RuntimeError('A previous database-bootstrap job exists but did not complete. Inspect it before retrying.')
    apply([yaml.safe_load((KUBERNETES / 'argocd/root' / (target + '.yaml')).read_text())])
    print('Argo CD root application created for', target)
    print('Kubeconfig:', env['KUBECONFIG'])
    print('After the API ingress is ready, run scripts/configure_api_dns.py.')

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--config', required=True)
    bootstrap(p.parse_args())

#!/usr/bin/env python3
"""Render every chart for the selected environments, verify pinned imports and deployment invariants.
Custom resources are validated against the CRD schemas vendored in this repo.
--configured additionally rejects placeholder runtime configuration.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
import jsonschema
import yaml
from helm_utils import ROOT, HELM, CHARTS, ENVIRONMENTS, build, helm_binary, load_yaml, values_file

GROUPS = {'apps': 'stocklane', 'platform': 'platform', 'monitoring-operator': 'monitoring-operator',
          'monitoring': 'monitoring', 'bootstrap': 'bootstrap'}

def verify_upstream():
    """Every vendored file committed in a chart must match the reviewed lock."""
    lock = json.loads((HELM / 'upstream.lock.json').read_text())
    for chart, files in lock['charts'].items():
        committed = {path.relative_to(HELM / chart).as_posix() for sub in ('files', 'crds') for path in (HELM / chart / sub).glob('*.yaml')}
        if committed != set(files):
            raise ValueError('Vendored files of chart ' + chart + ' differ from the lock: ' + ', '.join(sorted(committed ^ set(files))[:5]))
        for filename, expected in files.items():
            path = HELM / chart / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Pinned upstream resource changed: ' + str(path))

@lru_cache(maxsize=1)
def crd_definitions():
    result = {}
    for path in HELM.glob('*/crds/customresourcedefinition-*.yaml'):
        obj = load_yaml(path)
        result[obj['metadata']['name']] = obj
    return result

@lru_cache(maxsize=1)
def schemas():
    result = {}
    for obj in crd_definitions().values():
        for version in obj['spec']['versions']:
            schema = version.get('schema', {}).get('openAPIV3Schema')
            if schema is not None and version.get('served'):
                result[(obj['spec']['group'] + '/' + version['name'], obj['spec']['names']['kind'])] = schema
    return result

def validate_objects(objects, custom_schemas):
    identities = set()
    for obj in objects:
        # Always check this, including private builds without kubeconform.
        # policy/v1beta1 PDBs have not been served since Kubernetes 1.25.
        if obj['kind'] == 'PodDisruptionBudget' and obj['apiVersion'] != 'policy/v1':
            raise ValueError('PodDisruptionBudget ' + obj['metadata']['name']
                             + ' must use policy/v1 for Kubernetes 1.35; found ' + obj['apiVersion'])
        if obj['kind'] == 'CustomResourceDefinition':
            # The public built-in schema catalog omits CRD definitions. Require
            # their API and complete spec to match our checksum-pinned imports;
            # metadata changes such as sync-wave annotations remain supported.
            expected = crd_definitions().get(obj['metadata']['name'])
            if not expected or obj['apiVersion'] != expected['apiVersion'] or obj['spec'] != expected['spec']:
                raise ValueError('Unpinned or modified CustomResourceDefinition: ' + obj['metadata']['name'])
        identity = (obj['apiVersion'], obj['kind'], obj['metadata'].get('namespace', ''), obj['metadata']['name'])
        if identity in identities:raise ValueError('Duplicate Kubernetes resource: ' + str(identity))
        identities.add(identity)
        schema = custom_schemas.get((obj['apiVersion'], obj['kind']))
        if schema:jsonschema.Draft7Validator(schema).validate(obj)
        if obj['kind'] == 'Secret' and (obj.get('data') or obj.get('stringData')):
            if obj['metadata']['name'] != 'alertmanager-stocklane':
                raise ValueError('A committed Secret contains values: ' + obj['metadata']['name'])
    return identities

def validate_apps(objects, namespace, configured=False):
    deployments = {d['metadata']['name']: d for d in objects if d['kind'] == 'Deployment'}
    services = {d['metadata']['name']: d for d in objects if d['kind'] == 'Service'}
    assert set(deployments) == {'inventory', 'workshop', 'vision', 'forecast'}
    for name, deployment in deployments.items():
        assert deployment['metadata']['namespace'] == namespace
        pod = deployment['spec']['template']
        assert all(pod['metadata']['labels'].get(k) == v for k, v in services[name]['spec']['selector'].items())
        assert pod['spec']['securityContext']['runAsNonRoot']
        for container in pod['spec']['containers'] + pod['spec'].get('initContainers', []):
            assert container['securityContext']['readOnlyRootFilesystem']
            assert container['securityContext']['allowPrivilegeEscalation'] is False
            if configured:assert '@sha256:' in container['image']
    for hpa in (o for o in objects if o['kind'] == 'HorizontalPodAutoscaler'):
        assert hpa['spec']['scaleTargetRef']['name'] in deployments
        assert hpa['spec']['minReplicas'] <= hpa['spec']['maxReplicas']
    for obj in objects:
        if obj['kind'] == 'ConfigMap':
            assert 'PASSWORD' not in json.dumps(obj.get('data', {}))
        if obj['kind'] == 'Ingress':
            assert 'HTTPS' in obj['metadata']['annotations']['alb.ingress.kubernetes.io/listen-ports']
        if configured and obj['kind'] != 'CustomResourceDefinition':
            assert 'REPLACE_' not in json.dumps(obj), 'Unconfigured resource: ' + obj['metadata']['name']
    return deployments

def validate_environment(env, binary=None, configured=False, apps_only=False, values=None, root=None):
    namespace = ENVIRONMENTS[env]
    definitions = schemas()
    counts = {}
    schema_objects = []
    for group, chart in ((('apps', 'stocklane'),) if apps_only else GROUPS.items()):
        objects = build(chart, env, binary=binary, values=values, root=root); validate_objects(objects, definitions)
        schema_objects.extend(objects)
        if group == 'apps':
            validate_apps(objects, namespace, configured)
            if configured:
                release = json.loads(((Path(values).parent if values else HELM / 'releases' / env) / 'release.json').read_text())
                assert release['environment'] == env and release['namespace'] == namespace
                cm = next(o for o in objects if o['kind']=='ConfigMap' and o['metadata']['name']=='platform-config')
                assert cm['data']['MODEL_ARCHIVE_SHA256'] == release['model']['sha256']
                assert cm['data']['MODEL_URI'] == release['model']['uri']
        elif configured:
            for obj in objects:
                if obj['kind'] == 'CustomResourceDefinition':continue
                assert 'REPLACE_' not in json.dumps(obj), 'Unconfigured ' + group + ': ' + obj['metadata']['name']
                if obj['kind'] == 'Secret' and obj['metadata']['name'] == 'alertmanager-stocklane':
                    assert 'REPLACE_' not in base64.b64decode(obj['data']['alertmanager.yaml']).decode()
        counts[group] = len(objects)
    if not apps_only:
        objects = build('argocd-apps', env, binary=binary, values=values, root=root)
        validate_objects(objects, definitions)
        schema_objects.extend(objects)
        projects = {o['metadata']['name'] for o in objects if o['kind']=='AppProject'}
        for app in (o for o in objects if o['kind']=='Application'):
            assert app['spec']['project'] in projects
            chart = app['spec']['source']['path'].rsplit('/', 1)[-1]
            assert app['spec']['source']['path'] == 'deploy/helm/' + chart and (HELM / chart / 'Chart.yaml').exists()
            assert app['spec']['source']['helm']['valueFiles'] == ['../values/' + env + '.yaml']
            assert app['metadata']['name'].endswith('-' + env)
            if configured: assert 'REPLACE_' not in json.dumps(app), 'Unconfigured application: ' + app['metadata']['name']
        counts['argocd-applications'] = len(objects)
    if shutil.which('kubeconform'):
        # Custom resources have already passed their served CRD schemas above.
        # Every remaining object must have a built-in schema: missing schemas
        # may indicate a removed API and must fail rather than be skipped.
        builtins = [obj for obj in schema_objects
                    if obj['kind'] != 'CustomResourceDefinition'
                    and (obj['apiVersion'], obj['kind']) not in definitions]
        result = subprocess.run(['kubeconform', '-strict', '-kubernetes-version', '1.35.0', '-summary', '-'], input=yaml.safe_dump_all(builtins), text=True, capture_output=True)
        if result.returncode:raise ValueError('Kubernetes schema check failed: ' + result.stdout + result.stderr)
        print(result.stdout.strip(), flush=True)
    print(env + ': ' + ', '.join(f'{k}={v}' for k,v in counts.items()), flush=True)
    return counts

def lint(binary=None):
    """helm lint every chart with the placeholder values of every environment."""
    for chart in CHARTS:
        for env in ENVIRONMENTS:
            result = subprocess.run([helm_binary(binary), 'lint', str(HELM / chart), '-f', str(values_file(env))], capture_output=True, text=True)
            if result.returncode:raise ValueError('helm lint failed for ' + chart + ' (' + env + '): ' + (result.stdout + result.stderr)[-800:])

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--environment',choices=ENVIRONMENTS)
    p.add_argument('--helm');p.add_argument('--configured',action='store_true');p.add_argument('--apps-only',action='store_true')
    a=p.parse_args();verify_upstream()
    for env in ([a.environment] if a.environment else ENVIRONMENTS):validate_environment(env,a.helm,a.configured,a.apps_only)
    if not a.apps_only:
        validate_objects(build('argocd','dev',binary=a.helm),schemas())
        lint(a.helm)
    print('Helm charts, pinned imports, CRD schemas and deployment safeguards passed.')

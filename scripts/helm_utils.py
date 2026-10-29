"""Shared YAML and Helm helpers. No AWS calls or credentials are required."""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path
import yaml
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
# Upstream CRDs contain the YAML 1.2 plain scalar "=". PyYAML 1.1 tags it as value.
SAFE_LOADER.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))

ROOT = Path(__file__).resolve().parents[1]
HELM = ROOT / 'deploy/helm'
# Same names and namespaces as infra/terraform/environments/<env>.
ENVIRONMENTS = {'dev': 'stocklane-dev', 'staging': 'stocklane-staging', 'prod': 'stocklane-prod'}
# (minimum, maximum) application replicas per environment.
PROFILES = {'dev': (1, 2), 'staging': (2, 4), 'prod': (3, 6)}
# Every chart, and the namespace its release is installed into (None: the environment's workload namespace).
CHARTS = {'platform': 'kube-system', 'argocd': 'argocd', 'monitoring-operator': 'monitoring', 'monitoring': 'monitoring',
          'stocklane': None, 'bootstrap': None, 'argocd-apps': 'argocd'}

class BlockDumper(yaml.SafeDumper):
    pass

BlockDumper.add_representer(str, lambda d, s: d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None))

def load_yaml(path):
    return yaml.load(Path(path).read_text(), Loader=SAFE_LOADER)

def write_yaml(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(value, Dumper=BlockDumper, sort_keys=False, width=120))

def helm_binary(binary=None):
    found = binary or os.environ.get('HELM_BIN') or shutil.which('helm')
    if not found:
        raise RuntimeError('Install Helm with python scripts/install_helm.py or set HELM_BIN.')
    return str(found)

def values_file(env, directory=None):
    return Path(directory) / (env + '.yaml') if directory else HELM / 'values' / (env + '.yaml')

def environment(config):
    name = config.get('environment', 'prod')
    if name not in ENVIRONMENTS:
        raise ValueError('Environment must be dev, staging or prod')
    namespace = config.get('workload_namespace', ENVIRONMENTS[name])
    if namespace != ENVIRONMENTS[name]:
        raise ValueError('Workload namespace does not match the selected environment')
    return name, namespace

def template(chart, env, *, values=None, binary=None, root=None):
    """Render one chart for one environment exactly as Argo CD does, including CRDs."""
    chart_dir = (Path(root) if root else HELM) / chart
    namespace = CHARTS[chart] or ENVIRONMENTS[env]
    command = [helm_binary(binary), 'template', 'stocklane-' + chart + '-' + env, str(chart_dir), '--namespace', namespace,
               '-f', str(values or values_file(env)), '--include-crds']
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('helm template failed for ' + chart + ': ' + result.stderr.strip()[-800:])
    return [obj for obj in yaml.load_all(result.stdout, Loader=SAFE_LOADER) if obj]

def build(chart, env, **kwargs):
    return template(chart, env, **kwargs)

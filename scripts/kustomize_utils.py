"""Shared YAML and Kustomize helpers. No AWS calls or credentials are required."""
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
KUBERNETES = ROOT / 'deploy/kubernetes'
# Same names and namespaces as infra/terraform/environments/<env>.
ENVIRONMENTS = {'dev': 'stocklane-dev', 'staging': 'stocklane-staging', 'prod': 'stocklane-prod'}
# (minimum, maximum) application replicas per environment.
PROFILES = {'dev': (1, 2), 'staging': (2, 4), 'prod': (3, 6)}

class BlockDumper(yaml.SafeDumper):
    pass

BlockDumper.add_representer(str, lambda d, s: d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None))

def load_yaml(path):
    return yaml.load(Path(path).read_text(), Loader=SAFE_LOADER)

def write_yaml(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(value, Dumper=BlockDumper, sort_keys=False, width=120))

def kustomize_command(binary=None):
    binary = binary or os.environ.get('KUSTOMIZE_BIN') or shutil.which('kustomize')
    if binary:
        return [str(binary), 'build']
    kubectl = shutil.which('kubectl')
    if kubectl:
        return [kubectl, 'kustomize']
    raise RuntimeError('Install Kustomize with python scripts/install_kustomize.py or provide KUSTOMIZE_BIN.')

def build(path, binary=None):
    result = subprocess.run(kustomize_command(binary) + [str(path)], check=True, capture_output=True, text=True)
    return [obj for obj in yaml.load_all(result.stdout, Loader=SAFE_LOADER) if obj]

def environment(config):
    name = config.get('environment', 'prod')
    if name not in ENVIRONMENTS:
        raise ValueError('Environment must be dev, staging or prod')
    namespace = config.get('workload_namespace', ENVIRONMENTS[name])
    if namespace != ENVIRONMENTS[name]:
        raise ValueError('Workload namespace does not match the selected environment')
    return name, namespace

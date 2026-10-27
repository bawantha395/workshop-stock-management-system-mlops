"""Exercise rendered Grafana rollouts and the provisioning contract."""
import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from kustomize_utils import build
import render_cloud


def datasource_mount(objects):
    deployment = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    pod = deployment['spec']['template']['spec']
    name = next(v for v in pod['volumes'] if v['name'] == 'datasources')['configMap']['name']
    configmap = next(o for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['name'] == name)
    return pod, name, configmap


@pytest.mark.parametrize('environment', ['dev', 'test', 'uat', 'production'])
def test_every_overlay_provisions_the_datasource_referenced_by_its_panels(environment):
    objects = build(ROOT / 'deploy/kubernetes/monitoring/overlays' / environment)
    pod, name, configmap = datasource_mount(objects)
    assert name == 'grafana-datasources'
    deployment = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    assert re.fullmatch('[a-f0-9]{64}', deployment['spec']['template']['metadata']['annotations']['stocklane.io/provisioning-sha256'])
    datasource = yaml.safe_load(configmap['data']['datasources.yaml'])['datasources'][0]
    assert datasource['uid'] == 'prometheus'
    assert datasource['orgId'] == 1
    assert datasource['url'] == 'http://prometheus.monitoring.svc.cluster.local:9090'
    grafana = next(c for c in pod['containers'] if c['name'] == 'grafana')
    assert {'name': 'GF_PATHS_PROVISIONING', 'value': '/etc/grafana/provisioning'} in grafana['env']
    assert next(v for v in grafana['volumeMounts'] if v['name'] == 'datasources')['mountPath'] == '/etc/grafana/provisioning/datasources'
    dashboard = next(o for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'stocklane-dashboards')
    for panel in json.loads(dashboard['data']['stocklane.json'])['panels']:
        assert panel['datasource']['uid'] == datasource['uid']


def test_datasource_changes_roll_grafana_and_rollback_restores_the_pod_template(tmp_path, monkeypatch):
    fixture = tmp_path / 'kubernetes'
    shutil.copytree(ROOT / 'deploy/kubernetes', fixture)
    monkeypatch.setattr(render_cloud, 'KUBERNETES', fixture)
    overlay = fixture / 'monitoring/overlays/dev'
    first_hash = render_cloud.render_grafana_provisioning('dev')
    first = next(o for o in build(overlay) if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    source = fixture / 'monitoring/base/grafana/datasources-configmap.yaml'
    original = source.read_text()
    source.write_text(original.replace('prometheus.monitoring.svc.cluster.local', 'prometheus-new.monitoring.svc.cluster.local'))
    second_hash = render_cloud.render_grafana_provisioning('dev')
    second = next(o for o in build(overlay) if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    assert second_hash != first_hash
    assert second['spec']['template'] != first['spec']['template']
    source.write_text(original)
    assert render_cloud.render_grafana_provisioning('dev') == first_hash
    restored = next(o for o in build(overlay) if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grafana')
    assert restored['spec']['template'] == first['spec']['template']

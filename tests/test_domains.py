import sys,copy
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from kustomize_utils import load_yaml,build
import render_cloud

def test_admin_ingresses_use_separate_restricted_alb_and_correct_backend_tls(tmp_path,monkeypatch):
    import shutil
    k=tmp_path/'kubernetes'
    shutil.copytree(ROOT/'deploy/kubernetes',k)
    monkeypatch.setattr(render_cloud,'KUBERNETES',k)
    config={'name':'stocklane-dev','argocd_domain':'argocd-stocklane.example.com','grafana_domain':'grafana-stocklane.example.com','admin_allowed_cidrs':['203.0.113.7/32'],'admin_certificate_arn':'arn:aws:acm:ap-southeast-2:123456789012:certificate/test'}
    render_cloud.render_admin_access(config,'dev')
    folder=k/'platform/overlays/dev'
    argo=load_yaml(folder/'admin-argocd-ingress.yaml');grafana=load_yaml(folder/'admin-grafana-ingress.yaml')
    for ingress in [argo,grafana]:
        annotations=ingress['metadata']['annotations']
        assert annotations['alb.ingress.kubernetes.io/group.name']=='stocklane-dev-admin'
        assert annotations['alb.ingress.kubernetes.io/inbound-cidrs']=='203.0.113.7/32'
        assert annotations['alb.ingress.kubernetes.io/listen-ports']=='[{"HTTPS":443}]'
    docs=build(folder)
    assert {d['metadata']['namespace'] for d in docs if d['kind']=='Ingress' and d['metadata']['name'].startswith('admin-')}=={'argocd','monitoring'}
    assert argo['metadata']['namespace']=='argocd'
    assert argo['metadata']['annotations']['alb.ingress.kubernetes.io/backend-protocol']=='HTTPS'
    assert grafana['metadata']['namespace']=='monitoring'
    assert grafana['metadata']['annotations']['alb.ingress.kubernetes.io/backend-protocol']=='HTTP'
    deployment=load_yaml(k/'monitoring/overlays/dev/grafana-domain-patch.yaml')
    env=deployment['spec']['template']['spec']['containers'][0]['env']
    assert {'name':'GF_SECURITY_COOKIE_SECURE','value':'true'} in env
    assert {'name':'GF_SERVER_ROOT_URL','value':'https://grafana-stocklane.example.com/'} in env
    built=build(k/'monitoring/overlays/dev')
    runtime=next(d for d in built if d['kind']=='Deployment' and d['metadata']['name']=='grafana')
    assert {'name':'GF_SECURITY_COOKIE_SECURE','value':'true'} in runtime['spec']['template']['spec']['containers'][0]['env']

def test_admin_hosts_cannot_be_rendered_without_access_restriction(tmp_path,monkeypatch):
    import shutil
    k=tmp_path/'kubernetes';shutil.copytree(ROOT/'deploy/kubernetes/platform',k/'platform')
    monkeypatch.setattr(render_cloud,'KUBERNETES',k)
    with pytest.raises(ValueError,match='CIDRs'):
        render_cloud.render_admin_access({'name':'test','argocd_domain':'argocd.example.com'},'dev')

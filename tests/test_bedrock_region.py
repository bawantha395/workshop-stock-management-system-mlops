import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'services/vision'))

from render_cloud import render  # noqa: E402
from app import bedrock  # noqa: E402
from test_delivery_guards import config, images  # noqa: E402


def capture_client(monkeypatch):
    regions = []
    class Client:
        def converse(self, **kw):
            return {'output': {'message': {'content': [{'text': json.dumps({'name': 'Filter'})}]}}, 'usage': {}}
    def client(service, region_name=None, **kw):
        regions.append(region_name)
        return Client()
    monkeypatch.setattr(bedrock.boto3, 'client', client)
    return regions


def test_bedrock_calls_use_the_separate_bedrock_region(monkeypatch):
    regions = capture_client(monkeypatch)
    settings = SimpleNamespace(bedrock_model_id='amazon.nova-lite-v1:0', aws_region='ap-southeast-2', bedrock_region='us-east-1')
    assert bedrock.propose(settings, b'image') == ({'name': 'Filter'}, 'bedrock')
    assert regions == ['us-east-1']


def test_empty_bedrock_region_keeps_the_application_region(monkeypatch):
    regions = capture_client(monkeypatch)
    bedrock.propose(SimpleNamespace(bedrock_model_id='amazon.nova-lite-v1:0', aws_region='ap-southeast-2', bedrock_region=''), b'image')
    bedrock.propose(SimpleNamespace(bedrock_model_id='amazon.nova-lite-v1:0', aws_region='ap-southeast-2'), b'image')
    assert regions == ['ap-southeast-2', 'ap-southeast-2']


def test_renderer_publishes_bedrock_region_without_changing_aws_region(tmp_path):
    c = config()
    c.update(bedrock_model_id='amazon.nova-lite-v1:0', bedrock_region='us-east-1')
    render(c, images(), 's3://test-models/release.tar.gz', 'f' * 64, tmp_path)
    data = yaml.safe_load((tmp_path / 'patches/configmap.yaml').read_text())['data']
    assert data['BEDROCK_REGION'] == 'us-east-1'
    assert data['AWS_REGION'] == 'eu-west-1'
    job = yaml.safe_load((tmp_path / 'patches/model-index-job.yaml').read_text())
    env = {v['name']: v['value'] for v in job['spec']['template']['spec']['containers'][0]['env']}
    assert env['BEDROCK_REGION'] == 'us-east-1'


def test_renderer_defaults_bedrock_region_to_empty(tmp_path):
    render(config(), images(), 's3://test-models/release.tar.gz', 'f' * 64, tmp_path)
    data = yaml.safe_load((tmp_path / 'patches/configmap.yaml').read_text())['data']
    assert data['BEDROCK_REGION'] == ''


def test_terraform_scopes_invoke_permission_to_the_bedrock_region():
    source = (ROOT / 'infra/aws/ai-config.tf').read_text()
    assert 'bedrock:${local.bedrock_region}::foundation-model/${var.bedrock_model_id}' in source
    assert re.search(r'bedrock_region\s+=\s+var\.bedrock_region != "" \? var\.bedrock_region : var\.region', source)
    assert 'bedrock_region               = local.bedrock_region' in (ROOT / 'infra/aws/outputs.tf').read_text()


def test_workload_boundary_allows_only_foundation_model_invoke_outside_home_region():
    template = json.loads((ROOT / 'infra/ci/identity.json').read_text())
    statements = template['Resources']['WorkloadBoundary']['Properties']['PolicyDocument']['Statement']
    cross = next(s for s in statements if s['Sid'] == 'FoundationModelInvokeAnyRegion')
    assert cross['Effect'] == 'Allow' and cross['Action'] == ['bedrock:InvokeModel']
    assert cross['Resource'] == {'Fn::Sub': 'arn:${AWS::Partition}:bedrock:*::foundation-model/*'}
    assert 'Condition' not in cross

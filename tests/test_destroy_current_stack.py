import json
import sys
from pathlib import Path

import boto3
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import destroy_current_stack as teardown  # noqa: E402

REGION = 'ap-southeast-2'
CLUSTER = 'stocklane-dev'


def test_override_only_relaxes_provider_side_protections():
    text = teardown.OVERRIDE_TF
    for line in ['force_destroy = true', 'force_delete = true', 'deletion_protection = false',
                 'skip_final_snapshot = true', 'recovery_window_in_days = 0']:
        assert line in text
    assert teardown.OVERRIDE.name.endswith('_override.tf')
    for target in teardown.PROTECTION_TARGETS:
        kind, name = target.split('.')
        assert f'resource "{kind}" "{name}"' in text


def test_override_and_tfvars_are_git_ignored():
    ignored = (ROOT / '.gitignore').read_text()
    assert 'infra/aws/*_override.tf' in ignored and '*.tfvars.json' in ignored


def test_protection_step_refuses_plans_that_create_or_delete(monkeypatch, tmp_path):
    monkeypatch.setattr(teardown, 'PLAN', tmp_path / 'plan')
    def fake_tf(*args, capture=False, check=True):
        if args[0] == 'show':
            return json.dumps({'resource_changes': [
                {'address': 'aws_db_instance.main', 'change': {'actions': ['update']}},
                {'address': 'aws_s3_bucket.private["web"]', 'change': {'actions': ['delete', 'create']}}]})
        if args[0] == 'apply':
            raise AssertionError('must not apply an unsafe plan')
        return 0
    with pytest.raises(SystemExit, match='aws_s3_bucket.private'):
        teardown.relax_protections(fake_tf)


def test_protection_step_applies_in_place_updates(monkeypatch, tmp_path):
    monkeypatch.setattr(teardown, 'PLAN', tmp_path / 'plan')
    calls = []
    def fake_tf(*args, capture=False, check=True):
        calls.append(args[0])
        if args[0] == 'show':
            return json.dumps({'resource_changes': [
                {'address': 'aws_db_instance.main', 'change': {'actions': ['update']}},
                {'address': 'aws_kms_key.main', 'change': {'actions': ['no-op']}}]})
        return 0
    teardown.relax_protections(fake_tf)
    assert calls == ['plan', 'show', 'apply']


@pytest.fixture
def aws(monkeypatch):
    moto = pytest.importorskip('moto')
    for key, value in {'AWS_ACCESS_KEY_ID': 'testing', 'AWS_SECRET_ACCESS_KEY': 'testing',
                       'AWS_DEFAULT_REGION': REGION}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(teardown.time, 'sleep', lambda _: None)
    with moto.mock_aws():
        yield


def build_leftovers():
    ec2 = boto3.client('ec2', region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16', TagSpecifications=[{'ResourceType': 'vpc', 'Tags': [
        {'Key': 'Project', 'Value': CLUSTER}]}])['Vpc']['VpcId']
    subnets = [ec2.create_subnet(VpcId=vpc, CidrBlock=f'10.0.{i}.0/24', AvailabilityZone=REGION + z)['Subnet']['SubnetId']
               for i, z in enumerate('ab')]
    cluster_tag = [{'Key': 'elbv2.k8s.aws/cluster', 'Value': CLUSTER}]
    lb_sg = ec2.create_security_group(GroupName='k8s-stocklane-api', Description='controller', VpcId=vpc,
        TagSpecifications=[{'ResourceType': 'security-group', 'Tags': cluster_tag}])['GroupId']
    node_sg = ec2.create_security_group(GroupName='stocklane-nodes', Description='terraform', VpcId=vpc,
        TagSpecifications=[{'ResourceType': 'security-group', 'Tags': cluster_tag + [
            {'Key': 'ManagedBy', 'Value': 'Terraform'}]}])['GroupId']
    ec2.authorize_security_group_ingress(GroupId=node_sg, IpPermissions=[{'IpProtocol': 'tcp', 'FromPort': 8080,
        'ToPort': 8080, 'UserIdGroupPairs': [{'GroupId': lb_sg}]}])
    elb = boto3.client('elbv2', region_name=REGION)
    k8s_lb = elb.create_load_balancer(Name='k8s-stocklane-api', Subnets=subnets, SecurityGroups=[lb_sg],
                                      Tags=cluster_tag)['LoadBalancers'][0]
    other_lb = elb.create_load_balancer(Name='someone-else', Subnets=subnets)['LoadBalancers'][0]
    elb.create_target_group(Name='k8s-stocklane-tg', Protocol='HTTP', Port=80, VpcId=vpc, Tags=cluster_tag)
    elb.create_target_group(Name='other-tg', Protocol='HTTP', Port=80, VpcId=vpc)
    volume = ec2.create_volume(AvailabilityZone=REGION + 'a', Size=10, TagSpecifications=[{
        'ResourceType': 'volume', 'Tags': [{'Key': 'kubernetes.io/cluster/' + CLUSTER, 'Value': 'owned'}]}])['VolumeId']
    keep_volume = ec2.create_volume(AvailabilityZone=REGION + 'a', Size=10)['VolumeId']
    route53 = boto3.client('route53')
    zone = route53.create_hosted_zone(Name='example.tech', CallerReference='x')['HostedZone']['Id'].split('/')[-1]
    for name, target in [('api.example.tech', k8s_lb['DNSName']), ('www.example.tech', other_lb['DNSName'])]:
        route53.change_resource_record_sets(HostedZoneId=zone, ChangeBatch={'Changes': [{'Action': 'CREATE',
            'ResourceRecordSet': {'Name': name, 'Type': 'A', 'AliasTarget': {
                'HostedZoneId': k8s_lb['CanonicalHostedZoneId'], 'DNSName': target, 'EvaluateTargetHealth': False}}}]})
    return dict(ec2=ec2, elb=elb, route53=route53, zone=zone, lb_sg=lb_sg, node_sg=node_sg, other_lb=other_lb,
                volume=volume, keep_volume=keep_volume)


def test_sweep_removes_only_kubernetes_created_resources(aws):
    s = build_leftovers()
    teardown.sweep(CLUSTER, CLUSTER, REGION, ['api.example.tech', None, ''], s['zone'])
    names = [lb['LoadBalancerName'] for lb in s['elb'].describe_load_balancers()['LoadBalancers']]
    assert names == ['someone-else']
    assert [t['TargetGroupName'] for t in s['elb'].describe_target_groups()['TargetGroups']] == ['other-tg']
    groups = {g['GroupId'] for g in s['ec2'].describe_security_groups()['SecurityGroups']}
    assert s['lb_sg'] not in groups and s['node_sg'] in groups
    node = s['ec2'].describe_security_groups(GroupIds=[s['node_sg']])['SecurityGroups'][0]
    assert node['IpPermissions'] == []
    volumes = {v['VolumeId'] for v in s['ec2'].describe_volumes()['Volumes']}
    assert s['volume'] not in volumes and s['keep_volume'] in volumes
    records = {r['Name'] for r in s['route53'].list_resource_record_sets(HostedZoneId=s['zone'])['ResourceRecordSets']
               if r['Type'] == 'A'}
    assert records == {'www.example.tech.'}


def test_final_cleanup_force_deletes_project_secrets_and_reports_vpc(aws):
    secrets = boto3.client('secretsmanager', region_name=REGION)
    secrets.create_secret(Name=CLUSTER + '/platform', SecretString='x')
    secrets.create_secret(Name='other/keep', SecretString='x')
    secrets.delete_secret(SecretId=CLUSTER + '/platform', RecoveryWindowInDays=7)
    logs = boto3.client('logs', region_name=REGION)
    logs.create_log_group(logGroupName=f'/aws/rds/instance/{CLUSTER}/postgresql')
    assert teardown.leftovers(CLUSTER, REGION) is True
    remaining = [s['Name'] for s in secrets.list_secrets(IncludePlannedDeletion=True)['SecretList']]
    assert remaining == ['other/keep']
    assert logs.describe_log_groups(logGroupNamePrefix='/aws/rds/')['logGroups'] == []
    boto3.client('ec2', region_name=REGION).create_vpc(CidrBlock='10.1.0.0/16', TagSpecifications=[{
        'ResourceType': 'vpc', 'Tags': [{'Key': 'Project', 'Value': CLUSTER}]}])
    assert teardown.leftovers(CLUSTER, REGION) is False

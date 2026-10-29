"""The Destroy workflow's clean-up only touches what Kubernetes made for this environment."""
import sys
from pathlib import Path

import boto3
import pytest

moto = pytest.importorskip("moto")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import teardown_environment as teardown  # noqa: E402

REGION = "ap-southeast-2"
PROJECT = "stocklane-dev"


@pytest.fixture
def aws(monkeypatch):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with moto.mock_aws():
        yield


def load_balancer(elb, ec2, subnets, name, cluster):
    arn = elb.create_load_balancer(Name=name, Subnets=subnets, Tags=[
        {"Key": "elbv2.k8s.aws/cluster", "Value": cluster}])["LoadBalancers"][0]["LoadBalancerArn"]
    return arn


def test_sweep_removes_only_this_environments_kubernetes_resources(aws):
    ec2 = boto3.client("ec2", region_name=REGION)
    elb = boto3.client("elbv2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16", TagSpecifications=[
        {"ResourceType": "vpc", "Tags": [{"Key": "Project", "Value": PROJECT}]}])["Vpc"]["VpcId"]
    subnets = [ec2.create_subnet(VpcId=vpc, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=REGION + z)["Subnet"]["SubnetId"]
               for i, z in enumerate("ab")]
    mine = load_balancer(elb, ec2, subnets, "k8s-mine", PROJECT)
    other = load_balancer(elb, ec2, subnets, "k8s-other", "stocklane-prod")
    volume = ec2.create_volume(AvailabilityZone=REGION + "a", Size=1, TagSpecifications=[
        {"ResourceType": "volume", "Tags": [{"Key": "kubernetes.io/cluster/" + PROJECT, "Value": "owned"}]}])["VolumeId"]
    kept = ec2.create_volume(AvailabilityZone=REGION + "a", Size=1)["VolumeId"]
    route53 = boto3.client("route53")
    zone = route53.create_hosted_zone(Name="example.com", CallerReference="1")["HostedZone"]["Id"].split("/")[-1]
    alias = {"HostedZoneId": "Z1GM3OXH4ZPM65", "DNSName": "k8s-mine.ap-southeast-2.elb.amazonaws.com.",
             "EvaluateTargetHealth": False}
    route53.change_resource_record_sets(HostedZoneId=zone, ChangeBatch={"Changes": [
        {"Action": "CREATE", "ResourceRecordSet": {"Name": name, "Type": "A", "AliasTarget": alias}}
        for name in ("api.stocklane.example.com", "www.example.com")]})

    teardown.sweep(PROJECT, REGION, ["api.stocklane.example.com", ""], zone, sleep=lambda _: None)

    remaining = [lb["LoadBalancerArn"] for lb in elb.describe_load_balancers()["LoadBalancers"]]
    assert mine not in remaining and other in remaining
    volumes = [v["VolumeId"] for v in ec2.describe_volumes()["Volumes"]]
    assert volume not in volumes and kept in volumes
    names = [r["Name"] for r in route53.list_resource_record_sets(HostedZoneId=zone)["ResourceRecordSets"]]
    assert "api.stocklane.example.com." not in names and "www.example.com." in names


def test_check_reports_leftovers_until_the_vpc_is_gone(aws, capsys):
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16", TagSpecifications=[
        {"ResourceType": "vpc", "Tags": [{"Key": "Project", "Value": PROJECT}]}])["Vpc"]["VpcId"]
    assert teardown.leftovers(PROJECT, REGION) is False
    assert "VPCs: " + vpc in capsys.readouterr().out
    ec2.delete_vpc(VpcId=vpc)
    assert teardown.leftovers(PROJECT, REGION) is True

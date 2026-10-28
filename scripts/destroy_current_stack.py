"""One-time teardown of the current Stocklane environment, run from AWS CloudShell.

Removes everything in the Terraform state for one environment, plus the AWS
resources Kubernetes created outside Terraform (load balancers, their security
groups and target groups, EBS volumes, DNS aliases and leftover network
interfaces).

Kept on purpose: the Terraform state bucket, the CI identity CloudFormation
stack, the Route 53 hosted zone and the EKS node-group service-linked role.

Usage, from the repository root in CloudShell (Sydney):

    python3 scripts/destroy_current_stack.py --tfvars ~/stocklane-tfvars.json

The script stops for a typed confirmation before it changes anything.
"""
import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_common import ROOT, settings, terraform_inputs, write_private  # noqa: E402

TF_DIR = ROOT / "infra/aws"
TF_VERSION = "1.13.5"
OVERRIDE = TF_DIR / "destroy_override.tf"
TFVARS = TF_DIR / "destroy.auto.tfvars.json"
BACKEND = ROOT / "artifacts/destroy/backend.hcl"
PLAN = ROOT / "artifacts/destroy/protection.plan"
# CloudShell keeps only 1 GB in $HOME; the AWS provider alone is several hundred MB.
SCRATCH = Path("/tmp/stocklane-destroy")

# Provider-side flags only. Applying them changes no AWS resource except the
# RDS deletion-protection setting, and lets Terraform delete non-empty buckets,
# ECR repositories with images, the database without a final snapshot, and
# secrets immediately so the same names can be reused on the next deploy.
OVERRIDE_TF = """# Temporary file written by scripts/destroy_current_stack.py. Never commit.
resource "aws_s3_bucket" "automation" {
  force_destroy = true
}
resource "aws_s3_bucket" "private" {
  force_destroy = true
}
resource "aws_ecr_repository" "services" {
  force_delete = true
}
resource "aws_db_instance" "main" {
  deletion_protection = false
  skip_final_snapshot = true
}
resource "aws_secretsmanager_secret" "grafana" {
  recovery_window_in_days = 0
}
resource "aws_secretsmanager_secret" "database" {
  recovery_window_in_days = 0
}
resource "aws_secretsmanager_secret" "shared" {
  recovery_window_in_days = 0
}
"""
PROTECTION_TARGETS = ["aws_s3_bucket.automation", "aws_s3_bucket.private", "aws_ecr_repository.services",
                      "aws_db_instance.main", "aws_secretsmanager_secret.grafana",
                      "aws_secretsmanager_secret.database", "aws_secretsmanager_secret.shared"]


def say(*parts):
    print("\n==>", *parts, flush=True)


def terraform_binary():
    found = shutil.which("terraform")
    if found:
        version = subprocess.run([found, "version", "-json"], capture_output=True, text=True)
        if version.returncode == 0 and json.loads(version.stdout)["terraform_version"].startswith("1."):
            return found
    target = SCRATCH / "bin/terraform"
    if target.exists():
        return str(target)
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    url = f"https://releases.hashicorp.com/terraform/{TF_VERSION}/terraform_{TF_VERSION}_linux_{arch}.zip"
    say("Installing Terraform", TF_VERSION, "into", target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / "terraform.zip"
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extract("terraform", target.parent)
    archive.unlink()
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return str(target)


def github_identity(repository):
    if os.environ.get("GITHUB_REPOSITORY_ID") and os.environ.get("GITHUB_REPOSITORY_OWNER_ID"):
        return
    with urllib.request.urlopen("https://api.github.com/repos/" + repository, timeout=20) as response:
        data = json.load(response)
    os.environ["GITHUB_REPOSITORY"] = repository
    os.environ["GITHUB_REPOSITORY_ID"] = str(data["id"])
    os.environ["GITHUB_REPOSITORY_OWNER_ID"] = str(data["owner"]["id"])


class Terraform:
    def __init__(self, binary):
        self.binary = binary

    def __call__(self, *args, capture=False, check=True):
        command = [self.binary, "-chdir=" + str(TF_DIR), *args]
        print("$ terraform", " ".join(args), flush=True)
        env = dict(os.environ, TF_DATA_DIR=str(SCRATCH / "tf-data"), TF_IN_AUTOMATION="1")
        if capture:
            return subprocess.run(command, check=check, capture_output=True, text=True, env=env).stdout
        return subprocess.run(command, check=check, env=env).returncode


def prepare(tf, c, tfvars_path):
    raw = Path(tfvars_path).expanduser().read_text()
    data = terraform_inputs(c, raw)
    write_private(TFVARS, data)
    BACKEND.parent.mkdir(parents=True, exist_ok=True)
    BACKEND.write_text("\n".join([
        "bucket = " + json.dumps(c["bucket"]), "key = " + json.dumps(c["key"]),
        "region = " + json.dumps(c["region"]), "encrypt = true", "use_lockfile = true", ""]))
    OVERRIDE.write_text(OVERRIDE_TF)
    tf("init", "-input=false", "-reconfigure", "-backend-config=" + str(BACKEND))
    return data


def cleanup_local_files():
    for path in [OVERRIDE, TFVARS, PLAN]:
        if path.exists():
            path.unlink()


def inventory(tf):
    resources = tf("state", "list", capture=True, check=False).split()
    return resources


def relax_protections(tf):
    say("Step 1/6  Turn off delete protections (RDS deletion protection, buckets, ECR, secrets)")
    args = ["plan", "-input=false", "-lock-timeout=300s", "-out=" + str(PLAN)]
    for target in PROTECTION_TARGETS:
        args.append("-target=" + target)
    tf(*args)
    document = json.loads(tf("show", "-json", str(PLAN), capture=True))
    unsafe = [change["address"] for change in document.get("resource_changes", [])
              if set(change["change"]["actions"]) - {"no-op", "update", "read"}]
    if unsafe:
        raise SystemExit("Refusing: the protection step would create or delete resources: " + ", ".join(unsafe))
    tf("apply", "-input=false", "-lock-timeout=300s", str(PLAN))


def kubernetes_cleanup(cluster, region):
    say("Step 2/6  Kubernetes cleanup (best effort): stop Argo CD, delete ingresses, LB services and volumes")
    try:
        subprocess.run(["aws", "eks", "update-kubeconfig", "--name", cluster, "--region", region],
                       check=True, capture_output=True, timeout=60)
        subprocess.run(["kubectl", "version", "--request-timeout=15s"], check=True, capture_output=True, timeout=30)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Cluster API not reachable from this CloudShell (its IP may not be in the EKS allow list).")
        print("Continuing: the AWS-side sweep after removing the workers handles the same resources.")
        return
    commands = [
        ["kubectl", "-n", "argocd", "scale", "statefulset", "argocd-application-controller", "--replicas=0"],
        ["kubectl", "delete", "ingress", "--all", "-A", "--wait=false"],
        ["kubectl", "delete", "pvc", "--all", "-A", "--wait=false"],
    ]
    for command in commands:
        subprocess.run(command + ["--request-timeout=60s"], timeout=120)
    services = subprocess.run(["kubectl", "get", "svc", "-A", "-o", "json", "--request-timeout=60s"],
                              capture_output=True, text=True, timeout=120)
    if services.returncode == 0:
        for item in json.loads(services.stdout)["items"]:
            if item["spec"].get("type") == "LoadBalancer":
                subprocess.run(["kubectl", "-n", item["metadata"]["namespace"], "delete", "svc",
                                item["metadata"]["name"], "--wait=false", "--request-timeout=60s"], timeout=120)
    print("Waiting up to 5 minutes for the load balancer controller to remove ALBs...")
    elb = boto3.client("elbv2", region_name=region)
    for _ in range(30):
        if not cluster_load_balancers(elb, cluster):
            print("Kubernetes load balancers removed.")
            return
        time.sleep(10)
    print("Some load balancers remain; the sweep will delete them.")


def tags_match(tags, cluster):
    keys = {t["Key"]: t["Value"] for t in tags}
    return (keys.get("elbv2.k8s.aws/cluster") == cluster or "kubernetes.io/cluster/" + cluster in keys
            or keys.get("KubernetesCluster") == cluster or keys.get("eks:cluster-name") == cluster)


def cluster_load_balancers(elb, cluster):
    found = []
    for page in elb.get_paginator("describe_load_balancers").paginate():
        arns = [lb["LoadBalancerArn"] for lb in page["LoadBalancers"]]
        for start in range(0, len(arns), 20):
            for description in elb.describe_tags(ResourceArns=arns[start:start + 20])["TagDescriptions"]:
                if tags_match(description["Tags"], cluster):
                    found.append(description["ResourceArn"])
    return found


def remove_workers(tf):
    say("Step 3/6  Remove the EKS worker nodes so nothing recreates load balancers during the sweep")
    tf("destroy", "-input=false", "-lock-timeout=300s", "-auto-approve", "-target=aws_eks_node_group.main")


def project_vpcs(ec2, project):
    return [v["VpcId"] for v in ec2.describe_vpcs(Filters=[{"Name": "tag:Project", "Values": [project]}])["Vpcs"]]


def sweep(project, cluster, region, domains, zone_id):
    say("Step 4/6  Sweep AWS resources created by Kubernetes outside Terraform")
    elb = boto3.client("elbv2", region_name=region)
    ec2 = boto3.client("ec2", region_name=region)
    for arn in cluster_load_balancers(elb, cluster):
        try:
            elb.modify_load_balancer_attributes(LoadBalancerArn=arn, Attributes=[
                {"Key": "deletion_protection.enabled", "Value": "false"}])
        except ClientError:
            pass
        elb.delete_load_balancer(LoadBalancerArn=arn)
        print("Deleted load balancer", arn.rsplit("/", 2)[-2])
    for _ in range(30):
        if not cluster_load_balancers(elb, cluster):
            break
        time.sleep(10)
    groups = []
    for page in elb.get_paginator("describe_target_groups").paginate():
        groups += [g["TargetGroupArn"] for g in page["TargetGroups"]]
    for start in range(0, len(groups), 20):
        for description in elb.describe_tags(ResourceArns=groups[start:start + 20])["TagDescriptions"]:
            if tags_match(description["Tags"], cluster):
                elb.delete_target_group(TargetGroupArn=description["ResourceArn"])
                print("Deleted target group", description["ResourceArn"].rsplit("/", 2)[-2])
    vpcs = project_vpcs(ec2, project)
    if vpcs:
        controller_groups = [g for g in ec2.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": vpcs}])["SecurityGroups"] if tags_match(g.get("Tags", []), cluster)
            and g["GroupName"] != "default" and "ManagedBy" not in {t["Key"] for t in g.get("Tags", [])}]
        for group in controller_groups:
            for other in ec2.describe_security_groups(Filters=[
                    {"Name": "ip-permission.group-id", "Values": [group["GroupId"]]}])["SecurityGroups"]:
                rules = [p for p in other["IpPermissions"]
                         if any(pair.get("GroupId") == group["GroupId"] for pair in p.get("UserIdGroupPairs", []))]
                if rules:
                    ec2.revoke_security_group_ingress(GroupId=other["GroupId"], IpPermissions=rules)
        for group in controller_groups:
            for attempt in range(12):
                try:
                    ec2.delete_security_group(GroupId=group["GroupId"])
                    print("Deleted security group", group["GroupId"], group["GroupName"])
                    break
                except ClientError as error:
                    if error.response["Error"]["Code"] != "DependencyViolation" or attempt == 11:
                        print("Could not delete", group["GroupId"], error.response["Error"]["Code"])
                        break
                    time.sleep(10)
        for interface in ec2.describe_network_interfaces(Filters=[
                {"Name": "vpc-id", "Values": vpcs}, {"Name": "status", "Values": ["available"]}])["NetworkInterfaces"]:
            if interface.get("Description", "").startswith(("aws-K8S", "Amazon EKS")):
                try:
                    ec2.delete_network_interface(NetworkInterfaceId=interface["NetworkInterfaceId"])
                    print("Deleted leftover network interface", interface["NetworkInterfaceId"])
                except ClientError:
                    pass
    for page in ec2.get_paginator("describe_volumes").paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
            if tags_match(volume.get("Tags", []), cluster):
                ec2.delete_volume(VolumeId=volume["VolumeId"])
                print("Deleted Kubernetes volume", volume["VolumeId"])
    route53 = boto3.client("route53")
    wanted = {d.rstrip(".") + "." for d in domains if d}
    changes = []
    for page in route53.get_paginator("list_resource_record_sets").paginate(HostedZoneId=zone_id):
        for record in page["ResourceRecordSets"]:
            target = record.get("AliasTarget", {}).get("DNSName", "")
            if record["Name"] in wanted and record["Type"] in {"A", "AAAA"} and "elb.amazonaws.com" in target:
                changes.append({"Action": "DELETE", "ResourceRecordSet": record})
    if changes:
        route53.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch={
            "Comment": "Stocklane teardown", "Changes": changes})
        for change in changes:
            print("Deleted DNS alias", change["ResourceRecordSet"]["Name"])


def destroy_all(tf, project, cluster, region, domains, zone_id):
    say("Step 5/6  Terraform destroy (CloudFront and EKS make this take 20-30 minutes)")
    if tf("destroy", "-input=false", "-lock-timeout=300s", "-auto-approve", check=False) == 0:
        return
    print("Destroy stopped on a dependency. Sweeping again and retrying once...")
    sweep(project, cluster, region, domains, zone_id)
    tf("destroy", "-input=false", "-lock-timeout=300s", "-auto-approve")


def leftovers(project, region):
    say("Step 6/6  Final cleanup and billing check")
    secrets = boto3.client("secretsmanager", region_name=region)
    for page in secrets.get_paginator("list_secrets").paginate(IncludePlannedDeletion=True,
            Filters=[{"Key": "name", "Values": [project + "/"]}]):
        for secret in page["SecretList"]:
            secrets.delete_secret(SecretId=secret["ARN"], ForceDeleteWithoutRecovery=True)
            print("Removed secret", secret["Name"])
    logs = boto3.client("logs", region_name=region)
    for prefix in [f"/aws/rds/instance/{project}/", f"/aws/eks/{project}/", f"/aws/containerinsights/{project}/"]:
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
            for group in page["logGroups"]:
                logs.delete_log_group(logGroupName=group["logGroupName"])
                print("Deleted log group", group["logGroupName"])
    ec2 = boto3.client("ec2", region_name=region)
    tagged = [{"Name": "tag:Project", "Values": [project]}]
    remaining = {
        "EKS clusters": [n for n in boto3.client("eks", region_name=region).list_clusters()["clusters"] if n == project],
        "RDS instances": [d["DBInstanceIdentifier"] for d in boto3.client("rds", region_name=region)
                          .describe_db_instances()["DBInstances"] if d["DBInstanceIdentifier"] == project],
        "ElastiCache": [g["ReplicationGroupId"] for g in boto3.client("elasticache", region_name=region)
                        .describe_replication_groups()["ReplicationGroups"] if g["ReplicationGroupId"] == project],
        "NAT gateways": [n["NatGatewayId"] for n in ec2.describe_nat_gateways(Filters=tagged)["NatGateways"]
                         if n["State"] not in {"deleted", "deleting"}],
        "Elastic IPs": [a.get("AllocationId") for a in ec2.describe_addresses(Filters=tagged)["Addresses"]],
        "VPCs": project_vpcs(ec2, project),
        "Load balancers": cluster_load_balancers(boto3.client("elbv2", region_name=region), project),
    }
    billable = {k: v for k, v in remaining.items() if v}
    if billable:
        print("Still present (check these in the console):")
        for kind, items in billable.items():
            print(" -", kind + ":", ", ".join(items))
        return False
    print("No billable Stocklane environment resources remain.")
    print("Kept: Terraform state bucket, CI identity stack, Route 53 hosted zone.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tfvars", required=True, help="Your saved TFVARS_JSON content as a file")
    parser.add_argument("--repository", default="bawantha395/workshop-stock-management-system-mlops")
    parser.add_argument("--project", default="stocklane-dev")
    parser.add_argument("--environment", default="dev")
    parser.add_argument("--account", default="721274598579")
    parser.add_argument("--auth-mode", default="access-key")
    args = parser.parse_args()
    os.environ.setdefault("AWS_ACCOUNT_ID", args.account)
    os.environ.setdefault("PROJECT_NAME", args.project)
    os.environ.setdefault("TF_ENVIRONMENT", args.environment)
    os.environ.setdefault("AWS_AUTH_MODE", args.auth_mode)
    os.environ.setdefault("AWS_REGION", "ap-southeast-2")
    c = settings()
    caller = boto3.client("sts", region_name=c["region"]).get_caller_identity()
    if caller["Account"] != c["account"]:
        raise SystemExit("These credentials belong to another AWS account")
    github_identity(args.repository)
    tf = Terraform(terraform_binary())
    try:
        data = prepare(tf, c, args.tfvars)
        resources = inventory(tf)
        if not resources:
            raise SystemExit("The Terraform state is empty; nothing to destroy.")
        print(f"\nThis permanently deletes {len(resources)} Terraform resources in {c['account']} "
              f"({c['region']}) for {c['project']}, including the EKS cluster, the PostgreSQL database "
              "and its data, Redis, S3 buckets with their contents, ECR images and CloudFront.")
        print("Kept: Terraform state bucket, CI identity stack, Route 53 hosted zone.")
        if input(f"Type {c['project']} to continue: ").strip() != c["project"]:
            raise SystemExit("Cancelled. Nothing was changed.")
        domains = [data.get("api_domain"), data.get("argocd_domain"), data.get("grafana_domain")]
        relax_protections(tf)
        if "aws_eks_cluster.main" in resources:
            kubernetes_cleanup(c["project"], c["region"])
        if "aws_eks_node_group.main" in resources:
            remove_workers(tf)
        sweep(c["project"], c["project"], c["region"], domains, data["route53_zone_id"])
        destroy_all(tf, c["project"], c["project"], c["region"], domains, data["route53_zone_id"])
        clean = leftovers(c["project"], c["region"])
    finally:
        cleanup_local_files()
    say("Done." if clean else "Done, with items to check above.")
    print("Your saved TFVARS JSON is still needed for the next deploy; keep it safe.")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()

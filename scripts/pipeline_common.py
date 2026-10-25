"""Shared configuration and identity checks for the AWS delivery workflows."""
import argparse
import ipaddress
import json
import os
import re
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
REGION = "ap-southeast-2"
ENVIRONMENTS = {"dev", "test", "uat", "production"}
EKS_NODEGROUP_ROLE = "AWSServiceRoleForAmazonEKSNodegroup"


def verify_eks_nodegroup_role(iam, account):
    expected = f"arn:aws:iam::{account}:role/aws-service-role/eks-nodegroup.amazonaws.com/{EKS_NODEGROUP_ROLE}"
    actual = iam.get_role(RoleName=EKS_NODEGROUP_ROLE)["Role"]["Arn"]
    if actual != expected:
        raise RuntimeError("Unexpected EKS node-group service-linked role ARN")
    return actual


def check_eks_nodegroup_role(c):
    try:
        arn = verify_eks_nodegroup_role(client("iam", c), c["account"])
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code == "NoSuchEntity":
            raise RuntimeError("EKS node-group service-linked role is missing. Run the updated CloudShell bootstrap with --execute, then request a new plan.") from error
        if code in {"AccessDenied", "AccessDeniedException"}:
            raise RuntimeError("The current workflow role cannot read the EKS node-group service-linked role. Verify ReadEksNodegroupServiceLinkedRole in the deployed trust-stack policy and inspect any account-level deny before applying.") from error
        raise
    print("Verified EKS service-linked role with current workflow credentials:", arn)


def settings():
    account = os.environ.get("AWS_ACCOUNT_ID", "")
    project = os.environ.get("PROJECT_NAME", "")
    environment = os.environ.get("TF_ENVIRONMENT", "dev")
    region = os.environ.get("AWS_REGION", REGION)
    auth_mode = os.environ.get("AWS_AUTH_MODE", "oidc")
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("Set the AWS_ACCOUNT_ID repository variable")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,19}", project):
        raise ValueError("PROJECT_NAME must have 3-20 lowercase letters/digits/hyphens")
    if region != REGION:
        raise ValueError("This account's pipeline is restricted to Sydney: ap-southeast-2")
    if environment not in ENVIRONMENTS:
        raise ValueError("Invalid TF_ENVIRONMENT")
    if auth_mode not in {"oidc", "access-key"}:
        raise ValueError("AWS_AUTH_MODE must be oidc or access-key")
    bucket = os.environ.get("TF_STATE_BUCKET") or f"{project}-tfstate-{account}-{region}"
    if len(bucket) > 63 or not re.fullmatch(r"[a-z0-9][a-z0-9.-]+[a-z0-9]", bucket):
        raise ValueError("Invalid TF_STATE_BUCKET")
    return {"account": account, "project": project, "environment": environment, "auth_mode": auth_mode,
            "region": region, "bucket": bucket, "key": f"state/{environment}/terraform.tfstate",
            "automation_bucket": f"{project}-automation-{account}"}


def check_account(c):
    if boto3.client("sts", region_name=c["region"]).get_caller_identity()["Account"] != c["account"]:
        raise RuntimeError("AWS credentials do not belong to AWS_ACCOUNT_ID")


def client(service, c):
    return boto3.client(service, region_name=c["region"])


def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open with private permissions, including when replacing an existing file.
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def terraform_inputs(c, raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("TFVARS_JSON must be an object")
    declared = set()
    for source in (ROOT / "infra/aws").glob("*.tf"):
        declared.update(re.findall(r'variable\s+"([A-Za-z0-9_]+)"\s*\{', source.read_text()))
    unknown = set(data) - declared
    if unknown:
        raise ValueError("Unknown Terraform input(s): " + ", ".join(sorted(unknown)))
    required = {"administrator_arn", "operator_cidrs", "api_domain", "route53_zone_id", "budget_email"}
    if not required <= data.keys():
        raise ValueError("TFVARS_JSON is missing: " + ", ".join(sorted(required - data.keys())))
    arn = data["administrator_arn"]
    if not re.fullmatch(rf"arn:aws:iam::{c['account']}:(role|user)/[A-Za-z0-9+=,.@_/-]+", arn):
        raise ValueError("administrator_arn must be an IAM role/user in this account, including its path")
    if not data["operator_cidrs"]:
        raise ValueError("Supply restricted operator_cidrs")
    for value in data["operator_cidrs"]:
        network = ipaddress.ip_network(value, strict=True)
        if network.prefixlen == 0:
            raise ValueError("The EKS public endpoint must not allow the entire internet")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", data["api_domain"]) or "." not in data["api_domain"]:
        raise ValueError("Invalid api_domain")
    if not re.fullmatch(r"Z[A-Z0-9]+", data["route53_zone_id"]):
        raise ValueError("Invalid route53_zone_id")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", data["budget_email"]) or "REPLACE" in data["budget_email"]:
        raise ValueError("Set a real budget_email in TFVARS_JSON")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner_id = os.environ.get("GITHUB_REPOSITORY_OWNER_ID", "")
    repository_id = os.environ.get("GITHUB_REPOSITORY_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Missing GitHub repository identity")
    if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in [owner_id, repository_id]):
        raise ValueError("Missing immutable GitHub repository/owner IDs")
    authoritative = {
        "region": c["region"], "name": c["project"], "environment": c["environment"],
        "github_repository": repository, "github_owner_id": owner_id,
        "github_repository_id": repository_id,
        "github_auth_mode": c["auth_mode"],
        "github_ci_user_arn": f"arn:aws:iam::{c['account']}:user/{c['project']}-github-ci" if c["auth_mode"] == "access-key" else None,
        "github_oidc_provider_arn": f"arn:aws:iam::{c['account']}:oidc-provider/token.actions.githubusercontent.com" if c["auth_mode"] == "oidc" else "",
        "workload_permissions_boundary_arn": f"arn:aws:iam::{c['account']}:policy/{c['project']}-workload-boundary",
    }
    for key, value in authoritative.items():
        if key in data and data[key] != value:
            raise ValueError(f"TFVARS_JSON {key} conflicts with the configured workflow identity")
    data.update(authoritative)
    data.setdefault("github_oidc_subject_style", os.environ.get("OIDC_SUBJECT_STYLE", "immutable"))
    return data


def load_deployment(c):
    check_account(c)
    response = client("s3", c).get_object(
        Bucket=c["automation_bucket"], Key=f"outputs/{c['environment']}/current.json")
    envelope = json.loads(response["Body"].read())
    deployment = envelope.get("deployment", {}).get("value", {})
    checks = {"account_id": c["account"], "region": c["region"],
              "name": c["project"], "environment": c["environment"]}
    if any(deployment.get(key) != value for key, value in checks.items()):
        raise RuntimeError("Stored deployment outputs do not match this account/project/environment")
    if deployment.get("github_repository") != os.environ.get("GITHUB_REPOSITORY"):
        raise RuntimeError("Stored deployment outputs belong to a different GitHub repository")
    return envelope


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    write_private(args.output, load_deployment(settings()))
    print("Loaded deployment configuration from private S3")


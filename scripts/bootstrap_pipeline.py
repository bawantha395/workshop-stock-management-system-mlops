"""One-time, operator-authenticated GitHub pipeline bootstrap.
Default: prepare a reviewable CloudFormation change set only.
--execute: execute the change set prepared by this invocation and wait.
Access-key mode creates a key only with --create-access-key; its secret is
written privately outside CloudFormation outputs and Terraform state.
"""
import argparse
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from pipeline_common import EKS_NODEGROUP_ROLE, REGION, ROOT, verify_eks_nodegroup_role, write_private


def ensure_eks_nodegroup_role(iam, account):
    try:
        arn = verify_eks_nodegroup_role(iam, account)
    except ClientError as error:
        if error.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_service_linked_role(AWSServiceName="eks-nodegroup.amazonaws.com")
        iam.get_waiter("role_exists").wait(RoleName=EKS_NODEGROUP_ROLE,
                                          WaiterConfig={"Delay": 2, "MaxAttempts": 15})
        arn = verify_eks_nodegroup_role(iam, account)
    print("EKS node-group service-linked role is ready:", arn)


def discover_oidc_provider(iam):
    try:
        items = iam.list_open_id_connect_providers()["OpenIDConnectProviderList"]
        for item in items:
            arn = item["Arn"]
            if arn.endswith(":oidc-provider/token.actions.githubusercontent.com"):
                if "sts.amazonaws.com" not in iam.get_open_id_connect_provider(OpenIDConnectProviderArn=arn)["ClientIDList"]:
                    raise RuntimeError("Existing GitHub OIDC provider lacks the sts.amazonaws.com audience")
                return arn
        return ""
    except ClientError as error:
        if error.response["Error"]["Code"] in {"AccessDenied", "AccessDeniedException"}:
            raise RuntimeError("AWS denied IAM OIDC provider access. The Free project plan blocks iam:*Provider*. Use the documented --auth-mode access-key option when IAM users and role assumption are permitted; do not retry OIDC creation or change the SCP.") from None
        raise


def create_ci_access_key(iam, username, output):
    output = Path(output)
    if output.exists():
        raise RuntimeError("The private access-key handoff file already exists; reuse its GitHub settings or rotate the key explicitly")
    if iam.list_access_keys(UserName=username)["AccessKeyMetadata"]:
        raise RuntimeError("The CI user already has an access key. Reuse its GitHub secret or rotate it explicitly; no new key was created")
    key = iam.create_access_key(UserName=username)["AccessKey"]
    try:
        write_private(output, {"iam_user": username, "repository_secrets": {
            "AWS_ACCESS_KEY_ID": key["AccessKeyId"], "AWS_SECRET_ACCESS_KEY": key["SecretAccessKey"]}})
    except BaseException:
        # Do not leave a live key with a lost secret if local handoff fails.
        iam.delete_access_key(UserName=username, AccessKeyId=key["AccessKeyId"])
        raise
    print("CI access key saved privately to", output)
    print("Copy repository_secrets into GitHub Actions secrets. Key values are never printed by this helper.")


def github_get(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "stocklane-oidc-bootstrap"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    request = urllib.request.Request("https://api.github.com/" + path, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def github_repository(name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        raise ValueError("Use owner/repository")
    return github_get("repos/" + name)


ENVIRONMENTS = ["aws-bootstrap", "aws-infrastructure-plan", "aws-infrastructure-apply",
                "aws-platform", "aws-release", "aws-training"]


def check_environments(repository):
    for name in ENVIRONMENTS:
        prefix = "repos/" + repository + "/environments/" + name
        metadata = github_get(prefix)
        policy = metadata.get("deployment_branch_policy") or {}
        branches = github_get(prefix + "/deployment-branch-policies").get("branch_policies", [])
        if not policy.get("custom_branch_policies") or len(branches) != 1 or branches[0].get("name") != "main" or branches[0].get("type", "branch") != "branch":
            raise RuntimeError("Set environment " + name + " to Selected branches and tags, with one Branch rule: main")


def bootstrap(args):
    if args.create_access_key and (args.auth_mode != "access-key" or not args.execute):
        raise ValueError("--create-access-key requires --auth-mode access-key and --execute")
    if args.region != REGION:
        raise ValueError("Use the account's allowed Sydney Region, ap-southeast-2")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,19}", args.project_name):
        raise ValueError("Project name must have 3-20 lowercase letters/digits/hyphens")
    session = boto3.Session(region_name=args.region)
    identity = session.client("sts").get_caller_identity()
    account = identity["Account"]
    if args.expected_account and account != args.expected_account:
        raise RuntimeError("Signed in to a different AWS account")
    iam = session.client("iam")
    if ":assumed-role/" in identity["Arn"]:
        role_name = identity["Arn"].split("/")[-2]
        operator_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
    elif ":user/" in identity["Arn"]:
        operator_arn = identity["Arn"]
    else:
        raise RuntimeError("Use an IAM role/user operator session, not root")
    zone = session.client("route53").get_hosted_zone(Id=args.hosted_zone_id)["HostedZone"]
    if zone["Config"]["PrivateZone"] or not args.api_domain.endswith("." + zone["Name"].rstrip(".")):
        raise ValueError("API hostname must belong to the selected public hosted zone")
    repo = github_repository(args.repository)
    if repo["default_branch"] != "main":
        raise ValueError("The supplied workflows require a main default branch")
    args.repository = repo["full_name"]
    check_environments(args.repository)
    style = args.oidc_style
    if style == "auto":
        style = "immutable" if repo["created_at"] >= "2026-07-15T00:00:00Z" else "legacy"
    provider = discover_oidc_provider(iam) if args.auth_mode == "oidc" else ""
    bucket = f"{args.project_name}-tfstate-{account}-{args.region}"
    stack = args.project_name + "-github-trust"
    params = {"ProjectName": args.project_name, "Environment": args.environment, "AuthMode": args.auth_mode,
        "GitHubRepository": args.repository, "GitHubOwnerId": str(repo["owner"]["id"]),
        "GitHubRepositoryId": str(repo["id"]), "OidcSubjectStyle": style,
        "ExistingOidcProviderArn": provider, "StateBucketName": bucket,
        "HostedZoneId": args.hosted_zone_id, "ApiDomain": args.api_domain,
        "PublicZoneName": zone["Name"].rstrip(".")}
    cfn = session.client("cloudformation")
    action = "CREATE"
    try:
        status = cfn.describe_stacks(StackName=stack)["Stacks"][0]["StackStatus"]
        if status != "REVIEW_IN_PROGRESS":
            action = "UPDATE"
    except ClientError as error:
        if error.response["Error"]["Code"] != "ValidationError":
            raise
    # Preserve stack ownership when rerunning this helper: its original provider
    # must remain managed by the stack instead of being reclassified as external.
    if action == "UPDATE":
        current = cfn.describe_stacks(StackName=stack)["Stacks"][0]
        old = {p["ParameterKey"]: p["ParameterValue"] for p in current["Parameters"]}
        if old.get("AuthMode", "oidc") != args.auth_mode:
            raise RuntimeError("The existing trust stack uses a different authentication mode; review an explicit migration before changing it")
        if old.get("ExistingOidcProviderArn") == "":
            params["ExistingOidcProviderArn"] = ""
    change = cfn.create_change_set(StackName=stack,
        ChangeSetName="github-trust-" + str(int(time.time())), ChangeSetType=action,
        TemplateBody=json.dumps(json.loads((ROOT / "infra/ci/identity.json").read_text()), separators=(",", ":")),
        Capabilities=["CAPABILITY_NAMED_IAM"],
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in params.items()],
        Tags=[{"Key": "Project", "Value": args.project_name}])
    try:
        cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=change["Id"])
    except Exception:
        description = cfn.describe_change_set(ChangeSetName=change["Id"])
        if "didn't contain changes" not in description.get("StatusReason", ""):
            raise
        print("GitHub trust stack already matches the template")
        change = None
    if change:
        description = cfn.describe_change_set(ChangeSetName=change["Id"])
        for item in description.get("Changes", []):
            resource = item["ResourceChange"]
            print(resource["Action"], resource["ResourceType"], resource["LogicalResourceId"])
        print("Reviewable change set:", change["Id"])
        if args.execute:
            cfn.execute_change_set(ChangeSetName=change["Id"])
            waiter = "stack_create_complete" if action == "CREATE" else "stack_update_complete"
            cfn.get_waiter(waiter).wait(StackName=stack)
            print("AWS trust is ready")
        else:
            print("No IAM resources were provisioned. Review the change set and execute it in CloudFormation.")
    if args.execute:
        # Account-wide AWS-managed prerequisite, reused across EKS clusters.
        # Do not rely on EKS's automatic creation during a restricted CI session.
        ensure_eks_nodegroup_role(iam, account)
    if args.operator_cidr:
        cidr = args.operator_cidr
    else:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=20) as response:
            cidr = response.read().decode().strip() + "/32"
    ipaddress.ip_network(cidr, strict=True)
    email = args.budget_email or input("Email for AWS budget alerts: ").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Invalid budget email")
    # Account-specific values only. Sizes and deletion protection are reviewed
    # code in infra/terraform/environments/<env>/terraform.tfvars.
    inputs = {"administrator_arn": operator_arn, "operator_cidrs": [cidr],
        "api_domain": args.api_domain, "route53_zone_id": args.hosted_zone_id,
        "budget_email": email, "github_oidc_subject_style": style,
        "github_auth_mode": args.auth_mode}
    variables = {"AWS_ACCOUNT_ID": account, "AWS_REGION": args.region,
        "PROJECT_NAME": args.project_name, "TF_ENVIRONMENT": args.environment,
        "TF_STATE_BUCKET": bucket, "OIDC_SUBJECT_STYLE": style, "AWS_AUTH_MODE": args.auth_mode}
    output = ROOT / "deploy/generated/github-setup.json"
    write_private(output, {"repository_variables": variables,
        "repository_secret": {"name": "TFVARS_JSON", "value": inputs},
        "environments_main_only": ["aws-bootstrap", "aws-infrastructure-plan",
            "aws-infrastructure-apply", "aws-platform", "aws-release", "aws-training"]})
    print("GitHub settings saved privately to", output)
    print("Copy repository_variables into GitHub Actions variables, and repository_secret.value into the TFVARS_JSON secret.")
    print("Restrict every listed environment to the main branch before running AWS workflows.")
    if args.create_access_key:
        create_ci_access_key(iam, args.project_name + "-github-ci", ROOT / "deploy/generated/github-credentials.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--project-name", default="stocklane-dev")
    parser.add_argument("--environment", choices=["dev", "staging", "prod"], default="dev")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--expected-account", default="")
    parser.add_argument("--hosted-zone-id", required=True)
    parser.add_argument("--api-domain", required=True)
    parser.add_argument("--operator-cidr")
    parser.add_argument("--budget-email")
    parser.add_argument("--oidc-style", choices=["auto", "immutable", "legacy"], default="auto")
    parser.add_argument("--auth-mode", choices=["oidc", "access-key"], default="oidc")
    parser.add_argument("--create-access-key", action="store_true")
    parser.add_argument("--execute", action="store_true")
    bootstrap(parser.parse_args())


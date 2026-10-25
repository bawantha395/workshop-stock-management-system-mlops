"""Backend bootstrap, immutable private plans, and explicit reviewed applies."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from botocore.exceptions import ClientError
from pipeline_common import ROOT, check_account, check_eks_nodegroup_role, client, settings, terraform_inputs, write_private

WORK = ROOT / "artifacts" / "terraform"
MAX_PLAN_AGE = 6 * 60 * 60


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def tf(*args, capture=False):
    command = ["terraform", "-chdir=infra/aws", *args]
    if capture:
        return subprocess.check_output(command, cwd=ROOT)
    run(command)


def backend_ready(c):
    s3 = client("s3", c)
    location = s3.get_bucket_location(Bucket=c["bucket"], ExpectedBucketOwner=c["account"])["LocationConstraint"] or "us-east-1"
    if location != c["region"]:
        raise RuntimeError("Terraform state bucket is in a different region")
    if s3.get_bucket_versioning(Bucket=c["bucket"], ExpectedBucketOwner=c["account"]).get("Status") != "Enabled":
        raise RuntimeError("Terraform state bucket versioning is not enabled")
    block = s3.get_public_access_block(Bucket=c["bucket"], ExpectedBucketOwner=c["account"])["PublicAccessBlockConfiguration"]
    if not all(block.get(k) for k in ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"]):
        raise RuntimeError("Terraform state bucket must block all public access")
    rules = s3.get_bucket_encryption(Bucket=c["bucket"], ExpectedBucketOwner=c["account"])["ServerSideEncryptionConfiguration"]["Rules"]
    if not any(r["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256" for r in rules):
        raise RuntimeError("Expected AES256 state bucket encryption")


def seed_state(c):
    # Terraform's S3 backend may initialize a missing state. Seed it here so the
    # plan role never needs permission to overwrite authoritative state.
    s3 = client("s3", c)
    try:
        s3.head_object(Bucket=c["bucket"], Key=c["key"])
        print("Existing Terraform state preserved")
        return
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"NoSuchKey", "NotFound", "404"}:
            raise
    history = s3.list_object_versions(Bucket=c["bucket"], Prefix=c["key"], MaxKeys=10)
    if any(item["Key"] == c["key"] for group in ["Versions", "DeleteMarkers"] for item in history.get(group, [])):
        raise RuntimeError("State history exists but current state is missing; restore the previous version instead of reseeding")
    state = {"version": 4, "terraform_version": "1.13.5", "serial": 0,
             "lineage": str(uuid.uuid4()), "outputs": {}, "resources": [], "check_results": None}
    try:
        s3.put_object(Bucket=c["bucket"], Key=c["key"],
            Body=json.dumps(state).encode(), ServerSideEncryption="AES256", IfNoneMatch="*")
        print("Initialized empty remote Terraform state")
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
            raise
        print("Existing Terraform state preserved")


def bootstrap(c):
    stack = c["project"] + "-terraform-backend"
    run(["aws", "cloudformation", "deploy", "--region", c["region"], "--stack-name", stack,
         "--template-file", "infra/ci/state.json", "--no-fail-on-empty-changeset",
         "--parameter-overrides", "BucketName=" + c["bucket"], "ProjectName=" + c["project"]])
    backend_ready(c)
    seed_state(c)
    print("Private backend ready:", c["bucket"])


def prepare(c, readonly_lock=False):
    check_account(c)
    check_eks_nodegroup_role(c)
    backend_ready(c)
    WORK.mkdir(parents=True, exist_ok=True)
    data = terraform_inputs(c, os.environ["TFVARS_JSON"])
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for value in [data["budget_email"], *data["operator_cidrs"]]:
            escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print("::add-mask::" + escaped, flush=True)
    write_private(ROOT / "infra/aws/pipeline.auto.tfvars.json", data)
    backend = WORK / "backend.hcl"
    backend.write_text("\n".join([
        "bucket = " + json.dumps(c["bucket"]), "key = " + json.dumps(c["key"]),
        "region = " + json.dumps(c["region"]), "encrypt = true", "use_lockfile = true", ""]))
    backend.chmod(0o600)
    options = ["init", "-input=false", "-reconfigure", "-backend-config=" + str(backend)]
    if readonly_lock:
        options.append("-lockfile=readonly")
    tf(*options)
    tf("validate", "-no-color")
    return data


def assert_main_current(sha):
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Infrastructure operations require a reviewed main commit")
    current = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/main"], cwd=ROOT).decode().split()[0]
    if current != sha:
        raise RuntimeError("main changed after this workflow started; generate a fresh plan")


def public_summary(document):
    actions = {"create": 0, "update": 0, "delete": 0, "read": 0}
    resources = []
    for change in document.get("resource_changes", []):
        operations = change["change"]["actions"]
        if operations == ["no-op"]:
            continue
        for action in operations:
            if action in actions:
                actions[action] += 1
        resources.append({"address": change["address"], "actions": operations})
    return {"actions": actions, "resources": resources}


def plan(c):
    sha = os.environ["GITHUB_SHA"]
    assert_main_current(sha)
    inputs = prepare(c)
    tf("plan", "-input=false", "-lock-timeout=300s", "-out=" + str(WORK / "plan.bin"), "-no-color")
    document = json.loads(tf("show", "-json", str(WORK / "plan.bin"), capture=True))
    summary = public_summary(document)
    plan_id = os.environ["GITHUB_RUN_ID"] + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    prefix = f"plans/{c['environment']}/{plan_id}"
    payload = (WORK / "plan.bin").read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    response = client("s3", c).put_object(Bucket=c["bucket"], Key=prefix + "/plan.bin",
        Body=payload, ServerSideEncryption="AES256", IfNoneMatch="*")
    version = response.get("VersionId")
    if not version or version == "null":
        raise RuntimeError("Saved plans require S3 versioning")
    provider_lock = (ROOT / "infra/aws/.terraform.lock.hcl").read_bytes()
    lock_response = client("s3", c).put_object(Bucket=c["bucket"], Key=prefix + "/terraform.lock.hcl",
        Body=provider_lock, ServerSideEncryption="AES256", IfNoneMatch="*")
    if not lock_response.get("VersionId") or lock_response["VersionId"] == "null":
        raise RuntimeError("Provider lock requires S3 versioning")
    metadata = {"schema": 1, "plan_id": plan_id, "sha": sha, "created_at": int(time.time()),
        "sha256": digest, "version": version, "account": c["account"], "region": c["region"],
        "lock_sha256": hashlib.sha256(provider_lock).hexdigest(), "lock_version": lock_response["VersionId"],
        "project": c["project"], "environment": c["environment"], "key": c["key"],
        "inputs_sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        "summary": summary}
    client("s3", c).put_object(Bucket=c["bucket"], Key=prefix + "/metadata.json",
        Body=json.dumps(metadata).encode(), ServerSideEncryption="AES256", IfNoneMatch="*")
    report = ("## Terraform plan\n\n"
        + f"Plan ID: `{plan_id}`\n\nCommit: `{sha}`\n\nSHA256: `{digest}`\n\n"
        + "Run **Apply reviewed Terraform plan** with that Plan ID and SHA256 after review.\n\n"
        + "Full binary plans and state remain in private encrypted S3.\n\n"
        + "```json\n" + json.dumps(summary, indent=2) + "\n```\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(report)
    print("Plan ID:", plan_id)
    print("Plan SHA256:", digest)


def verified_plan(c, plan_id, expected_sha256, now=None):
    if not re.fullmatch(r"[0-9]+-[0-9]+", plan_id) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Supply the Plan ID and SHA256 from the plan workflow summary")
    prefix = f"plans/{c['environment']}/{plan_id}"
    s3 = client("s3", c)
    metadata = json.loads(s3.get_object(Bucket=c["bucket"], Key=prefix + "/metadata.json")["Body"].read())
    for key in ["account", "region", "project", "environment", "key"]:
        if metadata.get(key) != c[key]:
            raise RuntimeError("Saved plan belongs to another deployment")
    age = (time.time() if now is None else now) - metadata["created_at"]
    if metadata.get("plan_id") != plan_id or metadata.get("schema") != 1 or not 0 <= age <= MAX_PLAN_AGE:
        raise RuntimeError("Saved plan is invalid or older than six hours; generate a new plan")
    if (metadata.get("sha256") != expected_sha256 or not metadata.get("version") or metadata["version"] == "null"
            or not re.fullmatch(r"[0-9a-f]{64}", metadata.get("lock_sha256", ""))
            or not metadata.get("lock_version") or metadata["lock_version"] == "null"):
        raise RuntimeError("Saved plan metadata does not match the approved SHA256/version")
    payload = s3.get_object(Bucket=c["bucket"], Key=prefix + "/plan.bin", VersionId=metadata["version"])["Body"].read()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("Saved plan checksum mismatch")
    return metadata, payload


def apply(c, args):
    check_account(c)
    metadata, payload = verified_plan(c, args.plan_id, args.sha256)
    assert_main_current(metadata["sha"])
    if metadata["sha"] != os.environ["GITHUB_SHA"]:
        raise RuntimeError("Apply workflow must run from the same main commit as the plan")
    prefix = f"plans/{c['environment']}/{args.plan_id}"
    lock = client("s3", c).get_object(Bucket=c["bucket"], Key=prefix + "/terraform.lock.hcl",
        VersionId=metadata["lock_version"])["Body"].read()
    if hashlib.sha256(lock).hexdigest() != metadata["lock_sha256"]:
        raise RuntimeError("Provider lock checksum mismatch")
    lock_path = ROOT / "infra/aws/.terraform.lock.hcl"
    lock_path.write_bytes(lock)
    inputs = prepare(c, readonly_lock=True)
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    if digest != metadata["inputs_sha256"]:
        raise RuntimeError("Terraform inputs changed after planning; generate a fresh plan")
    if metadata["summary"]["actions"]["delete"] and not args.allow_deletions:
        raise RuntimeError("Plan includes deletes/replacements; explicitly approve them or re-plan")
    path = WORK / "approved-plan.bin"
    path.write_bytes(payload)
    path.chmod(0o600)
    tf("apply", "-input=false", "-lock-timeout=300s", str(path))
    outputs = json.loads(tf("output", "-json", capture=True))
    data = outputs["deployment"]["value"]
    if data["account_id"] != c["account"] or data["region"] != c["region"]:
        raise RuntimeError("Terraform outputs do not match the reviewed account/region")
    target = data["automation_bucket"]
    output_data = json.dumps(outputs).encode()
    s3 = client("s3", c)
    s3.put_object(Bucket=target, Key=f"outputs/{c['environment']}/{metadata['sha']}-{args.plan_id}.json",
                  Body=output_data, ServerSideEncryption="AES256", IfNoneMatch="*")
    s3.put_object(Bucket=target, Key=f"outputs/{c['environment']}/current.json",
                  Body=output_data, ServerSideEncryption="AES256")
    print("Applied reviewed plan and published non-secret deployment outputs to private S3")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["bootstrap", "plan", "apply"])
    parser.add_argument("--plan-id")
    parser.add_argument("--sha256")
    parser.add_argument("--allow-deletions", action="store_true")
    args = parser.parse_args()
    config = settings()
    check_account(config)
    {"bootstrap": lambda: bootstrap(config), "plan": lambda: plan(config),
     "apply": lambda: apply(config, args)}[args.operation]()


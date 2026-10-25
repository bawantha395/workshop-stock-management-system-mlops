import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import boto3
import pytest
import yaml
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap_pipeline
import pipeline_common as common
import pipeline_platform as platform
import pipeline_terraform as delivery


@pytest.fixture
def config(monkeypatch):
    values = {"AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "ap-southeast-2",
              "PROJECT_NAME": "stocklane-dev", "TF_ENVIRONMENT": "dev",
              "GITHUB_REPOSITORY": "example/workshop", "GITHUB_REPOSITORY_OWNER_ID": "123",
              "GITHUB_REPOSITORY_ID": "456"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("TF_STATE_BUCKET", raising=False)
    return common.settings()


def inputs():
    return {"administrator_arn": "arn:aws:iam::123456789012:role/managed/AccountFullAccessRole",
            "operator_cidrs": ["203.0.113.10/32"], "api_domain": "api.example.com",
            "route53_zone_id": "Z123EXAMPLE", "budget_email": "owner@example.com",
            "node_min_size": 2, "node_desired_size": 2, "node_max_size": 2}


def s3_client():
    return boto3.client("s3", region_name="ap-southeast-2",
                        aws_access_key_id="test", aws_secret_access_key="test")


def body(data):
    encoded = json.dumps(data).encode() if isinstance(data, dict) else data
    return StreamingBody(io.BytesIO(encoded), len(encoded))


def test_region_guard(config, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    with pytest.raises(ValueError, match="Sydney"):
        common.settings()


def test_inputs_preserve_managed_operator_path_and_bind_repository(config):
    result = common.terraform_inputs(config, json.dumps(inputs()))
    assert result["administrator_arn"].endswith("/managed/AccountFullAccessRole")
    assert result["github_repository_id"] == "456"
    assert result["github_owner_id"] == "123"
    assert result["region"] == "ap-southeast-2"
    assert result["github_oidc_provider_arn"].startswith("arn:aws:iam::123456789012:")


@pytest.mark.parametrize("key,value", [
    ("administrator_arn", "arn:aws:sts::123456789012:assumed-role/Admin/session"),
    ("administrator_arn", "arn:aws:iam::999999999999:role/Admin"),
    ("operator_cidrs", ["0.0.0.0/0"]), ("operator_cidrs", ["::/0"]),
    ("region", "us-east-1"), ("github_repository", "attacker/repository"),
    ("budget_email", "REPLACE_WITH_YOUR_EMAIL"), ("node_desird_size", 2),
])
def test_invalid_or_conflicting_inputs_are_rejected(config, key, value):
    data = inputs()
    data[key] = value
    with pytest.raises(ValueError):
        common.terraform_inputs(config, json.dumps(data))


def test_private_config_replaces_permissive_file(tmp_path):
    target = tmp_path / "config.json"
    target.write_text("{}")
    target.chmod(0o644)
    common.write_private(target, {"ok": True})
    assert target.stat().st_mode & 0o777 == 0o600


def test_seed_cannot_overwrite_existing_state(config, monkeypatch):
    client = s3_client()
    with Stubber(client) as stub:
        stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
        stub.add_response("list_object_versions", {})
        stub.add_client_error("put_object", service_error_code="PreconditionFailed",
            http_status_code=412, expected_params={"Bucket": config["bucket"], "Key": config["key"],
                "Body": ANY, "ServerSideEncryption": "AES256", "IfNoneMatch": "*"})
        monkeypatch.setattr(delivery, "client", lambda *args: client)
        delivery.seed_state(config)
        stub.assert_no_pending_responses()


def test_new_state_is_valid_empty_state_and_conditional(config, monkeypatch):
    captured = {}
    class Storage:
        def head_object(self, **kwargs):
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        def list_object_versions(self, **kwargs):
            return {}
        def put_object(self, **kwargs):
            captured.update(kwargs)
            return {"VersionId": "1"}
    monkeypatch.setattr(delivery, "client", lambda *args: Storage())
    delivery.seed_state(config)
    assert captured["IfNoneMatch"] == "*"
    data = json.loads(captured["Body"])
    assert data["version"] == 4 and data["serial"] == 0 and data["resources"] == []
    assert re.fullmatch(r"[a-f0-9-]{36}", data["lineage"])


def metadata(config, payload=b"approved plan", now=1000):
    return {**{k: config[k] for k in ["account", "region", "project", "environment", "key"]},
            "schema": 1, "plan_id": "10-1", "created_at": now, "sha": "a" * 40,
            "sha256": hashlib.sha256(payload).hexdigest(), "version": "pinned-version",
            "lock_sha256": hashlib.sha256(b"lock").hexdigest(), "lock_version": "lock-version"}


def test_plan_downloads_exact_s3_version_and_checks_checksum(config, monkeypatch):
    payload = b"approved plan"
    data = metadata(config, payload)
    client = s3_client()
    prefix = f"plans/{config['environment']}/10-1/"
    with Stubber(client) as stub:
        stub.add_response("get_object", {"Body": body(data)},
            {"Bucket": config["bucket"], "Key": prefix + "metadata.json"})
        stub.add_response("get_object", {"Body": body(payload)},
            {"Bucket": config["bucket"], "Key": prefix + "plan.bin", "VersionId": "pinned-version"})
        monkeypatch.setattr(delivery, "client", lambda *args: client)
        result, binary = delivery.verified_plan(config, "10-1", data["sha256"], now=1100)
        assert binary == payload and result["version"] == "pinned-version"
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("field,value", [
    ("account", "999999999999"), ("region", "us-east-1"), ("environment", "production"),
    ("created_at", -100000), ("created_at", 2000), ("version", "null"), ("sha256", "f" * 64),
])
def test_invalid_plan_metadata_stops_before_binary_download(config, monkeypatch, field, value):
    data = metadata(config)
    approved_hash = data["sha256"]
    data[field] = value
    client = s3_client()
    with Stubber(client) as stub:
        stub.add_response("get_object", {"Body": body(data)},
            {"Bucket": config["bucket"], "Key": "plans/dev/10-1/metadata.json"})
        monkeypatch.setattr(delivery, "client", lambda *args: client)
        with pytest.raises(RuntimeError):
            delivery.verified_plan(config, "10-1", approved_hash, now=1100)
        stub.assert_no_pending_responses()


def test_changed_plan_binary_is_rejected(config, monkeypatch):
    data = metadata(config)
    client = s3_client()
    with Stubber(client) as stub:
        stub.add_response("get_object", {"Body": body(data)})
        stub.add_response("get_object", {"Body": body(b"tampered plan")})
        monkeypatch.setattr(delivery, "client", lambda *args: client)
        with pytest.raises(RuntimeError, match="checksum"):
            delivery.verified_plan(config, "10-1", data["sha256"], now=1100)


def test_summary_never_includes_plan_values():
    document = {"planned_values": {"password": "SENSITIVE_SENTINEL"},
                "resource_changes": [{"address": "aws_db_instance.main",
                    "change": {"actions": ["delete", "create"], "after": {"password": "SENSITIVE_SENTINEL"}}}]}
    summary = delivery.public_summary(document)
    assert "SENSITIVE_SENTINEL" not in json.dumps(summary)
    assert summary["actions"]["delete"] == 1 and summary["actions"]["create"] == 1


def test_stale_main_commit_is_rejected(monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(delivery.subprocess, "check_output", lambda *a, **k: ("b" * 40 + "\trefs/heads/main").encode())
    with pytest.raises(RuntimeError, match="main changed"):
        delivery.assert_main_current("a" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    with pytest.raises(RuntimeError, match="reviewed main"):
        delivery.assert_main_current("a" * 40)


def test_environment_check_rejects_open_branch_rules(monkeypatch):
    def get(path):
        if path.endswith("deployment-branch-policies"):
            return {"branch_policies": [{"name": "*", "type": "branch"}]}
        return {"deployment_branch_policy": {"custom_branch_policies": True}}
    monkeypatch.setattr(bootstrap_pipeline, "github_get", get)
    with pytest.raises(RuntimeError, match="one Branch rule: main"):
        bootstrap_pipeline.check_environments("example/workshop")


def test_environment_check_accepts_main_only(monkeypatch):
    def get(path):
        if path.endswith("deployment-branch-policies"):
            return {"branch_policies": [{"name": "main", "type": "branch"}]}
        return {"deployment_branch_policy": {"custom_branch_policies": True}}
    monkeypatch.setattr(bootstrap_pipeline, "github_get", get)
    bootstrap_pipeline.check_environments("example/workshop")


def test_source_archive_excludes_state_credentials_builds_and_models(config, tmp_path, monkeypatch):
    files = {"scripts/app.py": "print('approved')", ".env": "PRIVATE_SENTINEL",
             "infra/aws/terraform.tfstate.backup": "PRIVATE_SENTINEL",
             "infra/aws/pipeline.auto.tfvars.json": "PRIVATE_SENTINEL",
             "node_modules/x.js": "PRIVATE_SENTINEL", "models/encoder.onnx": "PRIVATE_SENTINEL",
             ".env.example": "SAFE_EXAMPLE"}
    for relative, data in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    monkeypatch.setattr(platform, "ROOT", tmp_path)
    monkeypatch.setattr(platform.subprocess, "check_output", lambda *a, **k: "\0".join(files).encode())
    source = platform.source_archive({"deployment": {"value": {"region": "ap-southeast-2"}}}, "a" * 40)
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        assert "scripts/app.py" in archive.namelist() and ".env.example" in archive.namelist()
        assert "deploy/generated/aws.outputs.json" in archive.namelist()
        assert all(b"PRIVATE_SENTINEL" not in archive.read(name) for name in archive.namelist())


def test_privileged_workflows_require_main_and_manual_apply():
    for name, environment in [("aws-backend.yml", "aws-bootstrap"),
                              ("terraform-plan.yml", "aws-infrastructure-plan"),
                              ("terraform-apply.yml", "aws-infrastructure-apply"),
                              ("platform.yml", "aws-platform")]:
        workflow = yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)
        assert "pull_request" not in workflow["on"] and "pull_request_target" not in workflow["on"]
        privileged = [job for job in workflow["jobs"].values() if job.get("environment") == environment]
        assert len(privileged) == 1
        assert "github.ref == 'refs/heads/main'" in privileged[0]["if"]
        assert privileged[0]["permissions"]["id-token"] == "write"
        assert "upload-artifact" not in (ROOT / ".github/workflows" / name).read_text()
    apply = yaml.load((ROOT / ".github/workflows/terraform-apply.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(apply["on"]) == {"workflow_dispatch"}
    assert {"plan_id", "plan_sha256"} <= apply["on"]["workflow_dispatch"]["inputs"].keys()


def test_tf_oidc_claims_use_real_terraform_evaluation(tmp_path):
    binary = shutil.which("terraform")
    assert binary, "Install the pinned Terraform CLI to run automation checks"
    shutil.copy(ROOT / "infra/aws/github-oidc.tf", tmp_path / "github-oidc.tf")
    (tmp_path / "repository.tf").write_text('variable "github_repository" { type = string }\n')
    base = [binary, "console", "-no-color", "-var=github_repository=example/workshop"]
    expression = "jsonencode([local.github_release_subject,local.github_training_subject,local.github_platform_subject])\n"
    new = subprocess.run(base + ["-var=github_owner_id=123", "-var=github_repository_id=456"],
                         input=expression, text=True, capture_output=True, cwd=tmp_path)
    assert new.returncode == 0, new.stderr
    claims = json.loads(json.loads(new.stdout))
    assert claims == [f"repo:example@123/workshop@456:environment:{name}" for name in ["aws-release", "aws-training", "aws-platform"]]
    old = subprocess.run(base + ["-var=github_oidc_subject_style=legacy"],
                         input=expression, text=True, capture_output=True, cwd=tmp_path)
    assert old.returncode == 0, old.stderr
    assert json.loads(json.loads(old.stdout))[0] == "repo:example/workshop:environment:aws-release"
    missing = subprocess.run([binary, "plan", "-input=false", "-no-color",
                              "-var=github_repository=example/workshop"],
                             text=True, capture_output=True, cwd=tmp_path)
    assert missing.returncode != 0 and "Immutable subjects require" in missing.stderr


def test_codebuild_uses_private_subnets_and_no_privileged_docker():
    source = (ROOT / "infra/aws/automation.tf").read_text()
    assert 'subnets            = aws_subnet.private[*].id' in source
    assert "privileged_mode = false" in source
    assert 'referenced_security_group_id = aws_security_group.platform_bootstrap.id' in source
    assert 'principal_arn = aws_iam_role.platform_bootstrap.arn' in source


def resolve(value, params):
    if isinstance(value, list):
        return [resolve(v, params) for v in value]
    if not isinstance(value, dict):
        return value
    if "Ref" in value:
        return params[value["Ref"]]
    if "Fn::Sub" in value:
        data = value["Fn::Sub"]
        text, local = (data, {}) if isinstance(data, str) else (data[0], data[1])
        mapping = {**params, **{k: resolve(v, params) for k, v in local.items()}}
        return re.sub(r"\$\{([^}]+)\}", lambda match: str(mapping[match.group(1)]), text)
    if "Fn::If" in value:
        condition, yes, no = value["Fn::If"]
        truth = params["OidcSubjectStyle"] == "immutable" if condition == "ImmutableSubject" else not params["ExistingOidcProviderArn"]
        return resolve(yes if truth else no, params)
    if "Fn::Select" in value:
        index, values = value["Fn::Select"]
        return resolve(values, params)[int(index)]
    if "Fn::Split" in value:
        delimiter, data = value["Fn::Split"]
        return resolve(data, params).split(delimiter)
    return {k: resolve(v, params) for k, v in value.items()}


def test_bootstrap_policies_bind_environment_and_preserve_state_history():
    template = json.loads((ROOT / "infra/ci/identity.json").read_text())
    params = {"ProjectName": "x" * 20, "Environment": "production",
              "GitHubRepository": "example/workshop", "GitHubOwnerId": "123", "GitHubRepositoryId": "456",
              "OidcSubjectStyle": "immutable", "ExistingOidcProviderArn": "",
              "GitHubProvider": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com",
              "StateBucketName": "s" * 63, "HostedZoneId": "Z123EXAMPLE",
              "ApiDomain": "api.example.com", "WorkloadBoundary": "arn:aws:iam::123456789012:policy/" + "x"*20 + "-workload-boundary", "AWS::AccountId": "123456789012",
              "AWS::Region": "ap-southeast-2", "AWS::Partition": "aws"}
    for name, env in [("Bootstrap", "aws-bootstrap"), ("Plan", "aws-infrastructure-plan"), ("Apply", "aws-infrastructure-apply")]:
        properties = template["Resources"][name + "Role"]["Properties"]
        trust = resolve(properties["AssumeRolePolicyDocument"], params)
        condition = trust["Statement"][0]["Condition"]["StringEquals"]
        assert condition["token.actions.githubusercontent.com:sub"] == f"repo:example@123/workshop@456:environment:{env}"
        assert condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
        size = sum(len(json.dumps(resolve(p["PolicyDocument"], params), separators=(",", ":"))) for p in properties["Policies"])
        assert size <= 10240, (name, size)
    apply = template["Resources"]["ApplyRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert any(s["Sid"] == "ProtectPipelineTrust" and s["Effect"] == "Deny" for s in apply)
    assert any(s["Sid"] == "ProtectStateHistory" and s["Effect"] == "Deny" for s in apply)
    history = next(s for s in apply if s["Sid"] == "ProtectStateHistory")
    # Protect state versions while still allowing Terraform to delete its lock.
    assert history["Resource"] == {"Fn::Sub": "arn:${AWS::Partition}:s3:::${StateBucketName}/state/${Environment}/terraform.tfstate"}
    boundary = resolve(template["Resources"]["WorkloadBoundary"]["Properties"]["PolicyDocument"], params)
    assert len(json.dumps(boundary, separators=(",", ":"))) <= 6144
    plan = template["Resources"]["PlanRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert not any("s3:PutObject" in s["Action"] and "terraform.tfstate" == str(s["Resource"]).split("/")[-1].rstrip("'}") for s in plan)
    conditional = next(s for s in plan if s["Sid"] == "WriteNewSavedPlansOnly")
    assert conditional["Condition"]["StringEquals"]["s3:if-none-match"] == "*"



def test_delivery_filters_avoid_recursive_or_early_releases():
    from workflow_eligibility import eligible
    assert eligible("application", ["services/inventory/App.java"])
    assert not eligible("application", ["deploy/kubernetes/apps/overlays/dev/release.json"])
    assert not eligible("application", ["services/inventory/App.java", "infra/aws/data.tf"])
    assert not eligible("application", ["apps/web/src/main.tsx"], current=False)
    assert eligible("application", [], manual=True)
    assert eligible("platform", ["deploy/kubernetes/apps/overlays/dev/release.json"])
    assert not eligible("platform", ["README.md"])


def test_workflow_run_consumers_require_successful_own_main_push():
    for name in ["release.yml", "platform.yml"]:
        workflow = yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)
        assert workflow["on"]["workflow_run"]["branches"] == ["main"]
        guard = workflow["jobs"]["eligibility"]["if"]
        assert "workflow_run.event == 'push'" in guard
        assert "workflow_run.conclusion == 'success'" in guard
        assert "workflow_run.head_repository.full_name == github.repository" in guard


def test_application_releases_preserve_reviewed_model(tmp_path):
    from build_release import reviewed_model
    assert reviewed_model(tmp_path, "project-models") is None
    model = {"uri": "s3://project-models/releases/trained/artifact.tar.gz", "sha256": "a" * 64,
             "packageArn": "arn:aws:sagemaker:ap-southeast-2:123456789012:model-package/example/1"}
    (tmp_path / "release.json").write_text(json.dumps({"model": model}))
    retained = reviewed_model(tmp_path, "project-models")
    assert retained["uri"] == model["uri"] and retained["packageArn"] == model["packageArn"]
    with pytest.raises(ValueError, match="provenance"):
        reviewed_model(tmp_path, "another-project-models")


def test_deleted_state_is_not_silently_reinitialized(config, monkeypatch):
    client = s3_client()
    with Stubber(client) as stub:
        stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
        stub.add_response("list_object_versions", {"DeleteMarkers": [{"Key": config["key"], "VersionId": "deleted"}]})
        monkeypatch.setattr(delivery, "client", lambda *args: client)
        with pytest.raises(RuntimeError, match="restore the previous version"):
            delivery.seed_state(config)
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("corrupt", [False, True])
def test_repeated_model_promotion_verifies_existing_artifact(monkeypatch, corrupt):
    import tarfile
    from botocore.exceptions import ClientError
    sys.path.insert(0, str(ROOT / "mlops"))
    import promote
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, value in [("metrics.json", {"qualityGatePassed": True}),
                            ("model.json", {"workshopCalibrated": True, "version": "reviewed-v1"})]:
            data = json.dumps(value).encode()
            info = tarfile.TarInfo(name); info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    payload = stream.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    class Models:
        def describe_model_package(self, **kwargs):
            return {"ModelApprovalStatus": "Approved",
                    "InferenceSpecification": {"Containers": [{"ModelDataUrl": "s3://source/trained.tar.gz"}]},
                    "CustomerMetadataProperties": {"artifactSha256": digest}}
    class Storage:
        def get_object(self, **kwargs):
            value = b"corrupt" if corrupt and kwargs["Bucket"] == "target" else payload
            return {"Body": io.BytesIO(value)}
        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
    monkeypatch.setattr(promote.boto3, "client", lambda name, **kw: Models() if name == "sagemaker" else Storage())
    if corrupt:
        with pytest.raises(RuntimeError, match="Existing promoted artifact checksum mismatch"):
            promote.promote("approved-package", "ap-southeast-2", "s3://target/releases")
    else:
        assert promote.promote("approved-package", "ap-southeast-2", "s3://target/releases")["sha256"] == digest


def test_provisioned_roles_cannot_escape_workload_boundary():
    template = json.loads((ROOT / "infra/ci/identity.json").read_text())
    statements = template["Resources"]["ApplyRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    create = next(s for s in statements if s["Sid"] == "CreateOnlyBoundedProjectRoles")
    assert create["Condition"]["ArnEquals"]["iam:PermissionsBoundary"] == {"Ref": "WorkloadBoundary"}
    actions = template["Resources"]["WorkloadBoundary"]["Properties"]["PolicyDocument"]["Statement"]
    assert not any("iam:*" in s["Action"] or "iam:PutRolePolicy" in s["Action"] for s in actions)
    for source in (ROOT / "infra/aws").glob("*.tf"):
        for block in re.findall(r'resource "aws_iam_role" "[^"]+" \{\n([^\n]+)', source.read_text()):
            assert "permissions_boundary" in block

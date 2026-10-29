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
import pipeline_nodegroup as nodegroup


@pytest.fixture
def config(monkeypatch):
    values = {"AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "ap-southeast-2", "AWS_AUTH_MODE": "oidc",
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
             "infra/terraform/environments/dev/terraform.tfstate.backup": "PRIVATE_SENTINEL",
             "infra/terraform/environments/dev/pipeline.auto.tfvars.json": "PRIVATE_SENTINEL",
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


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


REUSABLE_ENVIRONMENTS = {
    "_terraform.yml": {"aws-bootstrap", "aws-infrastructure-plan", "aws-infrastructure-apply"},
    "_release.yml": {"aws-release"},
    "_platform.yml": {"aws-platform"},
    "_frontend.yml": {"aws-release"},
    "_cleanup.yml": {"aws-infrastructure-apply"},
}


def test_privileged_workflows_require_main_and_manual_apply():
    for name, environments in REUSABLE_ENVIRONMENTS.items():
        reusable = workflow(name)
        # Only callable from the two master pipelines; never from pull requests.
        assert set(reusable["on"]) == {"workflow_call"}, name
        jobs = [job for job in reusable["jobs"].values() if "environment" in job]
        assert {job["environment"] for job in jobs} == environments, name
        for job in jobs:
            assert "github.ref == 'refs/heads/main'" in job["if"], name
            assert job["permissions"]["id-token"] == "write", name
        assert "upload-artifact" not in (ROOT / ".github/workflows" / name).read_text()
    terraform = workflow("_terraform.yml")
    assert {"plan_id", "sha256", "allow_deletions"} <= terraform["on"]["workflow_call"]["inputs"].keys()
    for name in ("deploy.yml", "destroy.yml"):
        assert set(workflow(name)["on"]) == {"workflow_dispatch"}, name


def terraform_blocks(path, kind, names):
    """Copy named top-level blocks (variable/locals) from a Terraform file."""
    source = Path(path).read_text()
    blocks = []
    for name in names:
        header = f'{kind} "{name}" {{' if name else kind + " {"
        start = source.index(header)
        depth, index = 0, start
        while True:
            depth += {"{": 1, "}": -1}.get(source[index], 0)
            index += 1
            if depth == 0 and source[index - 1] == "}":
                break
        blocks.append(source[start:index])
    return "\n".join(blocks) + "\n"


ENVIRONMENT_ROOT = ROOT / "infra/terraform/environments/dev"
MODULES = ROOT / "infra/terraform/modules"


def test_tf_oidc_claims_use_real_terraform_evaluation(tmp_path):
    binary = shutil.which("terraform")
    assert binary, "Install the pinned Terraform CLI to run automation checks"
    variables = terraform_blocks(ENVIRONMENT_ROOT / "variables.tf", "variable",
                                 ["github_repository", "github_owner_id", "github_repository_id", "github_oidc_subject_style"])
    cicd = (MODULES / "cicd/main.tf").read_text()
    repository = cicd.split("github_oidc_repository = ", 1)[1].split("\n  oidc_provider_arn", 1)[0]
    (tmp_path / "main.tf").write_text(variables + "locals {\n  github_oidc_repository = " + repository + "\n  subjects = [for e in [\"aws-release\", \"aws-training\", \"aws-platform\"] : \"repo:${local.github_oidc_repository}:environment:${e}\"]\n}\n")
    base = [binary, "console", "-no-color", "-var=github_repository=example/workshop"]
    expression = "jsonencode(local.subjects)\n"
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
    source = (MODULES / "cicd/main.tf").read_text()
    assert 'subnets            = var.private_subnet_ids' in source
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
        mode = params.get("AuthMode", "oidc")
        truth = {"ImmutableSubject": params["OidcSubjectStyle"] == "immutable",
                 "UseOidcAuth": mode == "oidc", "UseAccessKeyAuth": mode == "access-key",
                 "CreateOidcProvider": mode == "oidc" and not params["ExistingOidcProviderArn"]}[condition]
        return resolve(yes if truth else no, params)
    if "Fn::GetAtt" in value:
        return params[".".join(value["Fn::GetAtt"])]
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
              "ApiDomain": "api.example.com", "PublicZoneName": "example.com", "WorkloadBoundary": "arn:aws:iam::123456789012:policy/" + "x"*20 + "-workload-boundary", "AWS::AccountId": "123456789012",
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



def test_master_pipelines_run_every_stage_in_order():
    deploy = workflow("deploy.yml")["jobs"]
    order = ["test", "plan", "apply", "release", "platform", "frontend"]
    for before, after in zip(order, order[1:]):
        needs = deploy[after]["needs"]
        assert before in (needs if isinstance(needs, list) else [needs]), after
    assert deploy["test"]["uses"] == "./.github/workflows/ci.yml"
    assert deploy["apply"]["with"]["plan_id"] == "${{ needs.plan.outputs.plan_id }}"
    assert deploy["platform"]["with"]["ref"] == "${{ needs.release.outputs.sha }}"
    assert "workflow_call" in workflow("ci.yml")["on"]
    destroy = workflow("destroy.yml")
    assert destroy["on"]["workflow_dispatch"]["inputs"]["confirm"]["required"] == "true"
    jobs = destroy["jobs"]
    assert jobs["platform-teardown"]["with"]["operation"] == "teardown"
    assert jobs["destroy-plan"]["with"]["operation"] == "destroy-plan"
    assert jobs["destroy"]["with"]["allow_deletions"] == "true"
    for name, job in jobs.items():
        if name != "confirm":
            assert "confirm" in str(job.get("needs")) or name == "destroy", name
    # No workflow starts AWS work on its own from another workflow's result.
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        assert "workflow_run" not in yaml.load(path.read_text(), Loader=yaml.BaseLoader)["on"], path.name


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
    roles = 0
    for source in (ROOT / "infra/terraform").rglob("*.tf"):
        for block in re.findall(r'resource "aws_iam_role" "[^"]+" \{\n([^\n]+)', source.read_text()):
            roles += 1
            assert "permissions_boundary" in block, source
    assert roles >= 10


def test_access_key_inputs_do_not_reference_an_oidc_provider(config, monkeypatch):
    monkeypatch.setenv("AWS_AUTH_MODE", "access-key")
    result = common.terraform_inputs(common.settings(), json.dumps(inputs()))
    assert result["github_oidc_provider_arn"] == ""
    assert result["github_ci_user_arn"] == "arn:aws:iam::123456789012:user/stocklane-dev-github-ci"
    assert result["github_auth_mode"] == "access-key"
    data = inputs(); data["github_ci_user_arn"] = "arn:aws:iam::999999999999:user/other"
    with pytest.raises(ValueError, match="conflicts"):
        common.terraform_inputs(common.settings(), json.dumps(data))


def test_oidc_permission_denial_is_actionable_and_does_not_retry():
    iam = boto3.client("iam", region_name="ap-southeast-2", aws_access_key_id="test", aws_secret_access_key="test")
    with Stubber(iam) as stub:
        stub.add_client_error("list_open_id_connect_providers", service_error_code="AccessDenied", http_status_code=403)
        with pytest.raises(RuntimeError, match="--auth-mode access-key"):
            bootstrap_pipeline.discover_oidc_provider(iam)
        stub.assert_no_pending_responses()


def test_access_key_handoff_is_private_and_refuses_duplicate_keys(tmp_path, capsys):
    class Identity:
        def __init__(self): self.keys=[]; self.calls=0
        def list_access_keys(self, **kwargs): return {"AccessKeyMetadata": self.keys}
        def create_access_key(self, **kwargs):
            self.calls+=1
            return {"AccessKey": {"AccessKeyId": "test-key-identifier", "SecretAccessKey": "private-test-value"}}
    iam=Identity(); output=tmp_path/"credentials.json"
    bootstrap_pipeline.create_ci_access_key(iam,"stocklane-dev-github-ci",output)
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["repository_secrets"]["AWS_SECRET_ACCESS_KEY"] == "private-test-value"
    assert "private-test-value" not in capsys.readouterr().out
    with pytest.raises(RuntimeError,match="already exists"):
        bootstrap_pipeline.create_ci_access_key(iam,"stocklane-dev-github-ci",output)
    output.unlink(); iam.keys=[{"AccessKeyId":"existing-key"}]
    with pytest.raises(RuntimeError,match="already has an access key"):
        bootstrap_pipeline.create_ci_access_key(iam,"stocklane-dev-github-ci",output)
    assert iam.calls==1


def test_failed_key_handoff_revokes_the_unusable_key(tmp_path,monkeypatch):
    calls=[]
    class Identity:
        def list_access_keys(self,**kwargs):return {"AccessKeyMetadata":[]}
        def create_access_key(self,**kwargs):return {"AccessKey":{"AccessKeyId":"test-key","SecretAccessKey":"private-test-value"}}
        def delete_access_key(self,**kwargs):calls.append(kwargs)
    def fail(*args):raise OSError("disk write failed")
    monkeypatch.setattr(bootstrap_pipeline,"write_private",fail)
    with pytest.raises(OSError,match="disk write failed"):
        bootstrap_pipeline.create_ci_access_key(Identity(),"project-ci",tmp_path/"credentials.json")
    assert calls==[{"UserName":"project-ci","AccessKeyId":"test-key"}]


def test_access_key_workflow_authentication_assumes_roles_without_oidc():
    action = yaml.load((ROOT / ".github/actions/aws-credentials/action.yml").read_text(), Loader=yaml.BaseLoader)
    steps = action["runs"]["steps"]
    access = [step for step in steps if step.get("if") == "env.AWS_AUTH_MODE == 'access-key'"]
    oidc = [step for step in steps if step.get("if") == "env.AWS_AUTH_MODE != 'access-key'"]
    assert len(access) == len(oidc) == 1
    step = access[0]
    assert step["with"]["force-skip-oidc"] == "true"
    assert step["with"]["role-skip-session-tagging"] == "true"
    assert step["with"]["role-to-assume"] == oidc[0]["with"]["role-to-assume"]
    assert step["with"]["aws-secret-access-key"] == "${{ inputs.secret-access-key }}"
    authenticated_jobs = []
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        text = path.read_text()
        assert "aws-actions/configure-aws-credentials@" not in text, path.name
        for name, job in yaml.load(text, Loader=yaml.BaseLoader)["jobs"].items():
            for login in [s for s in job.get("steps", []) if s.get("uses") == "./.github/actions/aws-credentials"]:
                assert login["with"]["role"] in {"ci-bootstrap", "ci-plan", "ci-apply", "github-release",
                                                 "github-platform", "github-training"}, (path.name, name)
                assert "secrets.AWS_SECRET_ACCESS_KEY }}" in login["with"]["secret-access-key"]
                authenticated_jobs.append((path.name, name))
    assert len(authenticated_jobs) >= 8


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("execute", [False, True])
def test_key_bootstrap_never_calls_oidc_apis_or_stores_keys_in_cloudformation(tmp_path,monkeypatch,existing,execute):
    from argparse import Namespace
    from botocore.exceptions import ClientError
    events=[]; captured={}
    for name in ["identity.json"]:
        p=tmp_path/"infra/ci"/name;p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy(ROOT/"infra/ci"/name,p)
    class Sts:
        def get_caller_identity(self):return {"Account":"123456789012","Arn":"arn:aws:sts::123456789012:assumed-role/AccountFullAccessRole/session"}
    class Iam:
        def get_role(self,**kwargs):
            if kwargs["RoleName"] == common.EKS_NODEGROUP_ROLE:
                events.append("check-eks-role")
                return {"Role":{"Arn":"arn:aws:iam::123456789012:role/aws-service-role/eks-nodegroup.amazonaws.com/" + common.EKS_NODEGROUP_ROLE}}
            return {"Role":{"Arn":"arn:aws:iam::123456789012:role/managed/AccountFullAccessRole"}}
        def list_access_keys(self,**kwargs):return {"AccessKeyMetadata":[]}
        def create_access_key(self,**kwargs):
            events.append("create-key")
            return {"AccessKey":{"AccessKeyId":"test-key-identifier","SecretAccessKey":"private-test-value"}}
    class Dns:
        def get_hosted_zone(self,**kwargs):return {"HostedZone":{"Name":"example.com.","Config":{"PrivateZone":False}}}
    class Cfn:
        def describe_stacks(self,**kwargs):
            if not existing:raise ClientError({"Error":{"Code":"ValidationError"}},"DescribeStacks")
            return {"Stacks":[{"StackStatus":"CREATE_COMPLETE","Parameters":[
                {"ParameterKey":"AuthMode","ParameterValue":"access-key"},
                {"ParameterKey":"ExistingOidcProviderArn","ParameterValue":""}]}]}
        def create_change_set(self,**kwargs):captured.update(kwargs);return {"Id":"reviewed-change-set"}
        def describe_change_set(self,**kwargs):return {"Changes":[]}
        def execute_change_set(self,**kwargs):events.append("execute")
        def get_waiter(self,name):
            class Waiter:
                def wait(self,**kwargs):events.append(name)
            return Waiter()
    clients={"sts":Sts(),"iam":Iam(),"route53":Dns(),"cloudformation":Cfn()}
    class Session:
        def client(self,name):return clients[name]
    monkeypatch.setattr(bootstrap_pipeline.boto3,"Session",lambda **kwargs:Session())
    monkeypatch.setattr(bootstrap_pipeline,"ROOT",tmp_path)
    monkeypatch.setattr(bootstrap_pipeline,"github_repository",lambda name:{"full_name":name,"default_branch":"main","created_at":"2026-10-25T00:00:00Z","owner":{"id":123},"id":456})
    monkeypatch.setattr(bootstrap_pipeline,"check_environments",lambda repository:None)
    args=Namespace(auth_mode="access-key",create_access_key=execute and not existing,execute=execute,region="ap-southeast-2",project_name="stocklane-dev",expected_account="123456789012",hosted_zone_id="Z123EXAMPLE",api_domain="api.example.com",repository="example/workshop",oidc_style="auto",operator_cidr="203.0.113.10/32",budget_email="owner@example.com",capacity_profile="demo",environment="dev")
    bootstrap_pipeline.bootstrap(args)
    params={p["ParameterKey"]:p["ParameterValue"] for p in captured["Parameters"]}
    assert params["AuthMode"]=="access-key" and params["ExistingOidcProviderArn"]==""
    assert len(captured["TemplateBody"].encode())<51200
    assert "private-test-value" not in captured["TemplateBody"]
    template=json.loads(captured["TemplateBody"])
    user=template["Resources"]["PipelineUser"]["Properties"]
    assert "LoginProfile" not in user
    statement=user["Policies"][0]["PolicyDocument"]["Statement"][0]
    assert statement["Action"]==["sts:AssumeRole"] and len(statement["Resource"])==6
    assert not any(v["Type"]=="AWS::IAM::AccessKey" for v in template["Resources"].values())
    for role in ["BootstrapRole","PlanRole","ApplyRole"]:
        branches=template["Resources"][role]["Properties"]["AssumeRolePolicyDocument"]["Fn::If"]
        trust=branches[2]["Statement"][0]
        assert trust["Action"]=="sts:AssumeRole"
        assert trust["Principal"]=={"AWS":{"Fn::GetAtt":["PipelineUser","Arn"]}}
    assert captured["ChangeSetType"] == ("UPDATE" if existing else "CREATE")
    if not execute:
        assert "execute" not in events and "check-eks-role" not in events and "create-key" not in events
    elif existing:
        assert "stack_update_complete" in events and "create-key" not in events
        assert not (tmp_path/"deploy/generated/github-credentials.json").exists()
    else:
        assert events.index("create-key")>events.index("stack_create_complete")
    setup=json.loads((tmp_path/"deploy/generated/github-setup.json").read_text())
    assert setup["repository_variables"]["AWS_AUTH_MODE"]=="access-key"
    assert "private-test-value" not in json.dumps(setup)
    # Sizes are reviewed code in terraform.tfvars, never copied into the secret.
    assert "database_instance_class" not in setup["repository_secret"]["value"]
    assert "deletion_protection" not in setup["repository_secret"]["value"]


@pytest.mark.parametrize("exists", [False, True])
def test_eks_service_role_bootstrap_reuses_existing_or_creates_only_after_not_found(exists):
    from botocore.exceptions import ClientError
    events = []
    role = "arn:aws:iam::123456789012:role/aws-service-role/eks-nodegroup.amazonaws.com/" + common.EKS_NODEGROUP_ROLE
    class Iam:
        ready = exists
        def get_role(self, **kwargs):
            assert kwargs == {"RoleName": common.EKS_NODEGROUP_ROLE}
            if not self.ready:raise ClientError({"Error":{"Code":"NoSuchEntity"}}, "GetRole")
            return {"Role":{"Arn":role}}
        def create_service_linked_role(self, **kwargs):
            assert kwargs == {"AWSServiceName":"eks-nodegroup.amazonaws.com"}
            events.append("create");self.ready=True
        def get_waiter(self, name):
            assert name == "role_exists"
            class Waiter:
                def wait(self, **kwargs):events.append("wait")
            return Waiter()
    bootstrap_pipeline.ensure_eks_nodegroup_role(Iam(), "123456789012")
    assert events == ([] if exists else ["create", "wait"])


@pytest.mark.parametrize("code", ["AccessDenied", "ServiceFailure"])
def test_eks_role_bootstrap_does_not_treat_permission_or_service_errors_as_absence(code):
    class Iam:
        def get_role(self, **kwargs):
            from botocore.exceptions import ClientError
            raise ClientError({"Error":{"Code":code}}, "GetRole")
        def create_service_linked_role(self, **kwargs):pytest.fail("Must not create after a denied or failed read")
    from botocore.exceptions import ClientError
    with pytest.raises(ClientError):bootstrap_pipeline.ensure_eks_nodegroup_role(Iam(), "123456789012")


@pytest.mark.parametrize("code,message", [("NoSuchEntity", "is missing"), ("AccessDenied", "cannot read")])
def test_workflow_preflight_reports_missing_role_and_denied_read_distinctly(config, monkeypatch, code, message):
    class Iam:
        def get_role(self, **kwargs):
            from botocore.exceptions import ClientError
            raise ClientError({"Error":{"Code":code}}, "GetRole")
    monkeypatch.setattr(common, "client", lambda service, c: Iam())
    with pytest.raises(RuntimeError, match=message):common.check_eks_nodegroup_role(config)


def test_workflow_preflight_checks_role_arn_with_current_credentials(config, monkeypatch):
    class Iam:
        account = config["account"]
        def get_role(self, **kwargs):
            return {"Role":{"Arn":f"arn:aws:iam::{self.account}:role/aws-service-role/eks-nodegroup.amazonaws.com/{common.EKS_NODEGROUP_ROLE}"}}
    iam = Iam()
    monkeypatch.setattr(common, "client", lambda service, c: iam)
    common.check_eks_nodegroup_role(config)
    iam.account = "999999999999"
    with pytest.raises(RuntimeError, match="Unexpected"):common.check_eks_nodegroup_role(config)


def test_preflight_denial_stops_before_backend_initialization(config, monkeypatch):
    calls = []
    monkeypatch.setattr(delivery, "check_account", lambda c: None)
    def denied(c):raise RuntimeError("cannot read EKS role")
    monkeypatch.setattr(delivery, "check_eks_nodegroup_role", denied)
    monkeypatch.setattr(delivery, "backend_ready", lambda c: calls.append("backend"))
    with pytest.raises(RuntimeError, match="cannot read"):delivery.prepare(config)
    assert calls == []


def environment_values(environment):
    values = {}
    for line in (ROOT / "infra/terraform/environments" / environment / "terraform.tfvars").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            values[key] = json.loads(value)
    return values


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_environment_sizes_are_reviewed_code_and_name_matches_folder(environment):
    values = environment_values(environment)
    assert values["environment"] == environment and values["name"] == "stocklane-" + environment
    declared = set(re.findall(r'variable\s+"([a-z0-9_]+)"', (ROOT / "infra/terraform/environments" / environment / "variables.tf").read_text()))
    assert set(values) <= declared


def test_dev_and_staging_tear_down_cleanly_while_prod_is_protected():
    dev, staging, prod = (environment_values(e) for e in ["dev", "staging", "prod"])
    assert dev["deletion_protection"] is False and staging["deletion_protection"] is False
    assert prod["deletion_protection"] is True and prod["database_multi_az"] is True and prod["nat_per_az"] is True
    assert dev["database_instance_class"] == "db.t4g.micro" and dev["database_max_allocated_storage"] == 0
    assert dev["database_backup_retention_days"] == 1 and prod["database_backup_retention_days"] == 14


def test_environment_roots_share_one_definition():
    shared = ["main.tf", "variables.tf", "outputs.tf", "versions.tf", ".terraform.lock.hcl"]
    for environment in ["staging", "prod"]:
        for name in shared:
            assert (ROOT / "infra/terraform/environments" / environment / name).read_bytes() == \
                (ENVIRONMENT_ROOT / name).read_bytes(), (environment, name)


def test_protect_data_controls_every_teardown_blocker():
    data = (MODULES / "data/main.tf").read_text()
    for expected in ["force_destroy = !var.protect_data", "deletion_protection             = var.protect_data",
                     "skip_final_snapshot             = !var.protect_data", "recovery_window_in_days = var.protect_data ? 7 : 0"]:
        assert expected in data, expected
    root = (ENVIRONMENT_ROOT / "main.tf").read_text()
    assert "protect_data                   = var.deletion_protection" in root
    assert "force_delete = !var.deletion_protection" in root and "force_destroy               = !var.deletion_protection" in root


def recovery_state(config):
    def resource(kind, name, *attributes):
        return {"mode": "managed", "type": kind, "name": name,
                "instances": [{"attributes": item} for item in attributes]}
    def within(module, item):
        return {**item, "module": module}
    return {"version": 4, "resources": [
        within("module.eks", resource("aws_eks_cluster", "main", {"arn": f"arn:aws:eks:{config['region']}:{config['account']}:cluster/{config['project']}"})),
        within("module.eks", resource("aws_iam_role", "nodes", {"arn": f"arn:aws:iam::{config['account']}:role/{config['project']}-nodes"})),
        within("module.network", resource("aws_subnet", "private", {"id": "subnet-11111111"}, {"id": "subnet-22222222"}))]}


def recovery_group(config):
    return {"nodegroupName": "cpu-workers", "clusterName": config["project"], "status": "ACTIVE",
            "nodegroupArn": f"arn:aws:eks:{config['region']}:{config['account']}:nodegroup/{config['project']}/cpu-workers/uuid",
            "nodeRole": f"arn:aws:iam::{config['account']}:role/{config['project']}-nodes",
            "subnets": ["subnet-11111111", "subnet-22222222"], "instanceTypes": ["t3.micro"],
            "tags": {"Project": config["project"], "Environment": "dev", "ManagedBy": "Terraform"}}


def recovery_clients(config, tmp_path, monkeypatch, state=None, group=None, error_code=None):
    from botocore.exceptions import ClientError
    state = recovery_state(config) if state is None else state
    group = recovery_group(config) if group is None else group
    calls = []
    class Storage:
        def get_object(self, **kwargs):
            calls.append("read-state")
            assert kwargs == {"Bucket": config["bucket"], "Key": config["key"], "ExpectedBucketOwner": config["account"]}
            return {"Body": body(state)}
    class Eks:
        def describe_nodegroup(self, **kwargs):
            calls.append("describe-nodegroup")
            assert kwargs == {"clusterName": config["project"], "nodegroupName": "cpu-workers"}
            if error_code:
                raise ClientError({"Error": {"Code": error_code}}, "DescribeNodegroup")
            return {"nodegroup": group}
    monkeypatch.setattr(nodegroup, "terraform_dir", lambda environment: tmp_path)
    monkeypatch.setattr(nodegroup, "client", lambda name, c: {"s3": Storage(), "eks": Eks()}[name])
    return tmp_path / "pipeline-recovery.tf", calls


@pytest.mark.parametrize("status", ["ACTIVE", "CREATE_FAILED", "DEGRADED", "UPDATE_FAILED"])
def test_cancelled_apply_adoption_only_prepares_private_import_configuration(config, tmp_path, monkeypatch, status):
    group = recovery_group(config); group["status"] = status
    path, calls = recovery_clients(config, tmp_path, monkeypatch, group=group)
    nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert calls == ["read-state", "describe-nodegroup"]
    assert 'id = "stocklane-dev:cpu-workers"' in path.read_text()
    assert "to = module.eks.aws_eks_node_group.main" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_orphaned_nodegroup_requires_explicit_plan_option(config, tmp_path, monkeypatch):
    path, _ = recovery_clients(config, tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="adopt_existing_nodegroup=true"):
        nodegroup.prepare_nodegroup_recovery(config)
    assert not path.exists()


@pytest.mark.parametrize("field,value", [
    ("nodeRole", "arn:aws:iam::123456789012:role/another-project-nodes"),
    ("nodegroupArn", "arn:aws:eks:ap-southeast-2:999999999999:nodegroup/stocklane-dev/cpu-workers/uuid"),
    ("clusterName", "another-project"), ("subnets", ["subnet-11111111", "subnet-33333333"]),
    ("tags", {"Project": "another-project", "Environment": "dev", "ManagedBy": "Terraform"}),
])
def test_recovery_refuses_unowned_nodegroups(config, tmp_path, monkeypatch, field, value):
    group = recovery_group(config); group[field] = value
    path, _ = recovery_clients(config, tmp_path, monkeypatch, group=group)
    with pytest.raises(RuntimeError, match="ownership tags"):
        nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert not path.exists()


@pytest.mark.parametrize("status", ["CREATING", "UPDATING", "DELETING"])
def test_recovery_waits_for_inflight_aws_operations(config, tmp_path, monkeypatch, status):
    group = recovery_group(config); group["status"] = status
    path, _ = recovery_clients(config, tmp_path, monkeypatch, group=group)
    with pytest.raises(RuntimeError, match="operation to finish"):
        nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert not path.exists()


@pytest.mark.parametrize("module", [None, "module.another_stack"])
def test_recovery_does_not_import_resources_twice(config, tmp_path, monkeypatch, module):
    state = recovery_state(config)
    state["resources"].append({"mode": "managed", "type": "aws_eks_node_group", "name": "another",
                               "instances": [{"attributes": {"id": "stocklane-dev:cpu-workers"}}]})
    if module: state["resources"][-1]["module"] = module
    path, _ = recovery_clients(config, tmp_path, monkeypatch, state=state)
    with pytest.raises(RuntimeError, match="another address"):
        nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert not path.exists()


def test_tracked_group_never_reimports_and_removes_stale_generated_configuration(config, tmp_path, monkeypatch):
    state = recovery_state(config)
    state["resources"].append({"mode": "managed", "type": "aws_eks_node_group", "name": "main", "module": "module.eks",
                               "instances": [{"attributes": {"id": "stocklane-dev:cpu-workers-new"}}]})
    path, calls = recovery_clients(config, tmp_path, monkeypatch, state=state)
    path.write_text("stale import")
    nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert calls == ["read-state"] and not path.exists()


@pytest.mark.parametrize("error", ["AccessDeniedException", "ServiceUnavailableException"])
def test_aws_errors_are_not_treated_as_missing_nodegroups(config, tmp_path, monkeypatch, error):
    from botocore.exceptions import ClientError
    path, _ = recovery_clients(config, tmp_path, monkeypatch, error_code=error)
    with pytest.raises(ClientError):
        nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert not path.exists()


def test_fresh_cluster_does_not_need_recovery_but_explicit_missing_adoption_is_an_error(config, tmp_path, monkeypatch):
    path, _ = recovery_clients(config, tmp_path, monkeypatch, error_code="ResourceNotFoundException")
    nodegroup.prepare_nodegroup_recovery(config)
    with pytest.raises(RuntimeError, match="No legacy"):
        nodegroup.prepare_nodegroup_recovery(config, adopt=True)
    assert not path.exists()


def test_summary_includes_imports_even_when_the_resource_has_no_other_changes():
    summary = delivery.public_summary({"resource_changes": [{"address": "aws_eks_node_group.main", "change": {
        "actions": ["no-op"], "importing": {"id": "stocklane-dev:cpu-workers"}, "after": {"private": "SENTINEL"}}}]})
    assert summary["actions"]["import"] == 1
    assert summary["resources"] == [{"address": "aws_eks_node_group.main", "actions": ["no-op"], "import": True}]
    assert "SENTINEL" not in json.dumps(summary)


def test_saved_plan_retains_reviewed_import_and_replacement_in_a_fresh_apply_checkout(tmp_path):
    # Exercise Terraform's actual saved-plan semantics without AWS resources or
    # external provider plugins. The apply job does not have the generated
    # import file that existed during planning.
    terraform = shutil.which("terraform")
    (tmp_path / "main.tf").write_text('resource "terraform_data" "worker" {\n'
        'triggers_replace = "new-capacity"\nlifecycle { create_before_destroy = true }\n}\n')
    recovery = tmp_path / "import.tf"
    recovery.write_text('import {\nto = terraform_data.worker\nid = "orphaned-worker"\n}\n')
    for args in [["init", "-backend=false", "-input=false"],
                 ["plan", "-input=false", "-no-color", "-out=plan.bin"]]:
        result = subprocess.run([terraform, *args], cwd=tmp_path, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    document = json.loads(subprocess.check_output([terraform, "show", "-json", "plan.bin"], cwd=tmp_path))
    assert document["resource_changes"][0]["change"]["actions"] == ["create", "delete"]
    assert delivery.public_summary(document)["actions"]["import"] == 1
    recovery.unlink()
    result = subprocess.run([terraform, "apply", "-input=false", "-no-color", "plan.bin"],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / "terraform.tfstate").read_text())
    assert state["resources"][0]["instances"][0]["attributes"]["id"] != "orphaned-worker"


@pytest.mark.parametrize("address,actions,approved", [
    ("module.eks.aws_eks_node_group.main", ["create", "delete"], True),
    ("module.eks.aws_eks_node_group.main", ["delete", "create"], False),
    ("module.eks.aws_eks_node_group.main", ["delete"], False),
    ("aws_eks_node_group.main", ["create", "delete"], False),
    ("module.data.aws_db_instance.main", ["create", "delete"], False),
])
def test_nodegroup_replacement_approval_cannot_authorize_other_deletions(address, actions, approved):
    summary = {"resources": [{"address": address, "actions": actions}]}
    if approved:
        nodegroup.check_change_approval(summary, allow_nodegroup_replacement=True)
        with pytest.raises(RuntimeError): nodegroup.check_change_approval(summary)
    else:
        with pytest.raises(RuntimeError):
            nodegroup.check_change_approval(summary, allow_nodegroup_replacement=True)


def test_nodegroup_approval_still_refuses_mixed_database_and_worker_replacements():
    summary = {"resources": [{"address": address, "actions": ["create", "delete"]}
                              for address in ["module.eks.aws_eks_node_group.main", "module.data.aws_db_instance.main"]]}
    with pytest.raises(RuntimeError):
        nodegroup.check_change_approval(summary, allow_nodegroup_replacement=True)


def test_rds_managed_secret_creation_is_scoped_to_account_region_prefix_and_two_actions():
    from fnmatch import fnmatchcase
    template = json.loads((ROOT / "infra/ci/identity.json").read_text())
    statements = template["Resources"]["ApplyRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    statement = resolve(next(s for s in statements if s["Sid"] == "CreateRdsManagedMasterSecret"),
                        {"AWS::Partition": "aws", "AWS::AccountId": "123456789012", "AWS::Region": "ap-southeast-2"})
    assert set(statement["Action"]) == {"secretsmanager:CreateSecret", "secretsmanager:TagResource"}
    assert statement["Condition"] == {"StringEquals": {"aws:RequestedRegion": "ap-southeast-2"}}
    arn = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:rds!db-randomid-abcdef"
    assert fnmatchcase(arn, statement["Resource"])
    assert not fnmatchcase(arn.replace("123456789012", "999999999999"), statement["Resource"])
    assert not fnmatchcase(arn.replace("ap-southeast-2", "us-east-1"), statement["Resource"])
    assert not fnmatchcase(arn.replace("rds!db-randomid", "unrelated-app-password"), statement["Resource"])
    plan = template["Resources"]["PlanRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert not any(s["Sid"] == "CreateRdsManagedMasterSecret" for s in plan)


@pytest.mark.parametrize("quota,should_pass", [(8, True), (5, False)])
def test_replacement_quota_counts_existing_on_demand_workers_and_new_capacity(config, monkeypatch, quota, should_pass):
    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs == {"Filters": [{"Name": "instance-state-name", "Values": ["pending", "running"]}]}
            instances = [{"InstanceType": "t3.micro", "CpuOptions": {"CoreCount": 1, "ThreadsPerCore": 2}} for _ in range(2)]
            # Spot and GPU quotas are separate from standard On-Demand vCPUs.
            instances.extend([{"InstanceType": "m7i-flex.large", "InstanceLifecycle": "spot"},
                              {"InstanceType": "g5.xlarge"}])
            return [{"Reservations": [{"Instances": instances}]}]
    class Ec2:
        def describe_instance_types(self, **kwargs):
            if kwargs == {"InstanceTypes": ["t3.micro"]}:
                return {"InstanceTypes": [{"InstanceType": "t3.micro", "VCpuInfo": {"DefaultVCpus": 2}}]}
            assert kwargs == {"InstanceTypes": ["m7i-flex.large"]}
            return {"InstanceTypes": [{"ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                                      "VCpuInfo": {"DefaultVCpus": 2}, "MemoryInfo": {"SizeInMiB": 8192}}]}
        def get_paginator(self, name):
            assert name == "describe_instances"
            return Paginator()
    class Quotas:
        def get_service_quota(self, **kwargs):
            assert kwargs == {"ServiceCode": "ec2", "QuotaCode": "L-1216C47A"}
            return {"Quota": {"Value": quota}}
    monkeypatch.setattr(nodegroup, "client", lambda name, c: {"ec2": Ec2(), "service-quotas": Quotas()}[name])
    document = {"resource_changes": [{"address": "module.eks.aws_eks_node_group.main", "change": {"actions": ["create", "delete"]}}]}
    capacity = {"node_instance_type": "m7i-flex.large", "node_desired_size": 2}
    if should_pass:
        nodegroup.check_worker_quota(config, capacity, document)
    else:
        with pytest.raises(RuntimeError, match="quota cannot fit"):
            nodegroup.check_worker_quota(config, capacity, document)


def test_read_only_plan_without_worker_creation_does_not_require_extra_capacity(config, monkeypatch):
    monkeypatch.setattr(nodegroup, "client", lambda *args: pytest.fail("No quota check needed without new workers"))
    nodegroup.check_worker_quota(config, {}, {"resource_changes": []})


@pytest.mark.parametrize("role_name", ["PlanRole", "ApplyRole"])
def test_ci_discovery_covers_the_service_role_and_budget_without_global_access(role_name):
    from fnmatch import fnmatchcase
    template = json.loads((ROOT / "infra/ci/identity.json").read_text())
    statements = resolve(template["Resources"][role_name]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"],
                         {"AWS::Partition": "aws", "AWS::AccountId": "123456789012", "AWS::Region": "ap-southeast-2",
                          "ProjectName": "stocklane-dev", "Environment": "dev", "StateBucketName": "state-bucket",
                          "HostedZoneId": "Z123EXAMPLE", "ApiDomain": "api.example.com", "PublicZoneName": "example.com", "WorkloadBoundary": "boundary"})
    def permitted(action, resource):
        for statement in statements:
            if statement["Effect"] != "Allow" or "Condition" in statement:
                continue
            actions = statement["Action"]
            resources = statement["Resource"]
            if isinstance(actions, str): actions = [actions]
            if isinstance(resources, str): resources = [resources]
            if any(fnmatchcase(action.lower(), a.lower()) for a in actions) and any(fnmatchcase(resource, r) for r in resources):
                return True
        return False
    service_role = "arn:aws:iam::123456789012:role/aws-service-role/eks-nodegroup.amazonaws.com/AWSServiceRoleForAmazonEKSNodegroup"
    budget = "arn:aws:budgets::123456789012:budget/stocklane-dev-monthly"
    assert permitted("iam:GetRole", service_role)
    assert not permitted("iam:GetRole", service_role.replace("123456789012", "999999999999"))
    assert not permitted("iam:GetRole", "arn:aws:iam::123456789012:role/unrelated-admin")
    assert not permitted("iam:UpdateRole", service_role)
    assert permitted("budgets:ListTagsForResource", budget)
    assert not permitted("budgets:ListTagsForResource", budget.replace("stocklane-dev", "other"))
    for action in ["budgets:TagResource", "budgets:UntagResource"]:
        assert permitted(action, budget) == (role_name == "ApplyRole")
        assert not permitted(action, budget.replace("stocklane-dev", "other"))


def test_plan_can_refresh_cognito_resources_without_group_mutation_permissions():
    from fnmatch import fnmatchcase
    template = json.loads((ROOT / "infra/ci/identity.json").read_text())
    statements = template["Resources"]["PlanRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    statements = resolve([s for s in statements if any(a.startswith("cognito-idp:") for a in s["Action"])],
                         {"AWS::Partition": "aws", "AWS::Region": "ap-southeast-2", "AWS::AccountId": "123456789012"})
    def allowed(action, resource, region="ap-southeast-2"):
        for statement in statements:
            if statement["Effect"] != "Allow": continue
            if statement.get("Condition", {}).get("StringEquals", {}).get("aws:RequestedRegion", region) != region: continue
            if any(fnmatchcase(action.lower(), a.lower()) for a in statement["Action"]) and fnmatchcase(resource, statement["Resource"]):
                return True
        return False
    pool = "arn:aws:cognito-idp:ap-southeast-2:123456789012:userpool/ap-southeast-2_Example"
    # Read APIs used to refresh every Cognito resource in web-auth.tf.
    for action in ["DescribeUserPool", "DescribeUserPoolClient", "DescribeUserPoolDomain",
                   "DescribeResourceServer", "GetUserPoolMfaConfig", "GetGroup", "ListTagsForResource"]:
        assert allowed("cognito-idp:" + action, pool), action
    for action in ["CreateGroup", "UpdateGroup", "DeleteGroup", "AdminAddUserToGroup", "AdminGetUser"]:
        assert not allowed("cognito-idp:" + action, pool), action
    assert not allowed("cognito-idp:GetGroup", pool.replace("123456789012", "999999999999"))
    assert not allowed("cognito-idp:GetGroup", pool.replace("ap-southeast-2", "us-east-1"))
    assert not allowed("cognito-idp:GetGroup", pool, region="us-east-1")


def retention_configuration():
    return terraform_blocks(MODULES / "data/variables.tf", "variable", ["database_backup_retention_days"])


@pytest.mark.parametrize("environment,expected", [("dev", 1), ("staging", 3), ("prod", 14)])
def test_rds_retention_keeps_backups_in_every_environment(environment, expected):
    assert environment_values(environment)["database_backup_retention_days"] == expected
    data = (MODULES / "data/main.tf").read_text()
    assert "backup_retention_period         = var.database_backup_retention_days" in data


@pytest.mark.parametrize("retention", [0, -1, 36, 1.5])
def test_invalid_retention_cannot_disable_backups_or_exceed_rds_limits(tmp_path, retention):
    (tmp_path / "main.tf").write_text(retention_configuration())
    result = subprocess.run([shutil.which("terraform"), "plan", "-input=false", "-no-color",
                             "-var=database_backup_retention_days=" + str(retention)],
                            text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode != 0
    assert "automated backups stay enabled" in result.stderr


def test_sns_policy_uses_supported_topic_actions_and_preserves_source_and_tls_guards(tmp_path):
    source = (MODULES / "observability/main.tf").read_text()
    # Evaluate the real policy expression without requiring AWS credentials or
    # provider plugins. Only resource attribute values are replaced by fixtures.
    actions = re.search(r'\nlocals \{\n.*?\n\}', source, re.DOTALL).group(0)
    resource = source.split('resource "aws_sns_topic_policy" "operations" {', 1)[1].split('\nresource ', 1)[0]
    expression = resource.split('policy = ', 1)[1].rsplit('\n}', 1)[0].strip()
    expression = expression.replace("aws_sns_topic.operations.arn", "local.topic_arn")
    (tmp_path / "main.tf").write_text(actions + '\nvariable "name" { default = "stocklane-dev" }\nvariable "region" { default = "ap-southeast-2" }\n'
        + 'variable "partition" { default = "aws" }\nvariable "account_id" { default = "123456789012" }\n'
        + 'locals {\ntopic_arn = "arn:aws:sns:ap-southeast-2:123456789012:stocklane-dev-operations"\noperations_policy = '
        + expression + '\n}\n')
    result = subprocess.run([shutil.which("terraform"), "console", "-no-color"],
                            input="local.operations_policy\n", text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    policy = json.loads(json.loads(result.stdout))
    # AWS's SNS topic-policy allowlist; identity-based policies allow more APIs.
    allowed = {"sns:AddPermission", "sns:DeleteTopic", "sns:GetDataProtectionPolicy", "sns:GetTopicAttributes",
               "sns:ListSubscriptionsByTopic", "sns:ListTagsForResource", "sns:Publish", "sns:PutDataProtectionPolicy",
               "sns:RemovePermission", "sns:SetTopicAttributes", "sns:Subscribe"}
    statements = {s["Sid"]: s for s in policy["Statement"]}
    for statement in statements.values():
        actions = statement["Action"]
        assert set([actions] if isinstance(actions, str) else actions) <= allowed
    tls = statements["TLSOnly"]
    assert tls["Effect"] == "Deny" and tls["Condition"]["Bool"]["aws:SecureTransport"] == "false"
    assert set(tls["Action"]) == set(statements["Owner"]["Action"])
    cloudwatch = statements["CloudWatchAlarms"]
    assert cloudwatch["Principal"] == {"Service": "cloudwatch.amazonaws.com"}
    assert cloudwatch["Action"] == "sns:Publish"
    assert cloudwatch["Condition"]["StringEquals"]["aws:SourceAccount"] == "123456789012"
    assert cloudwatch["Condition"]["ArnLike"]["aws:SourceArn"].endswith(":alarm:stocklane-dev-*")


def test_release_installs_the_onnx_export_dependency_before_downloading_the_model():
    steps = workflow("_release.yml")["jobs"]["release"]["steps"]
    step = next(s for s in steps if "download_model.py" in s.get("run", ""))
    assert "pip install onnx==" in step["run"]

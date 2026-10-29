"""Submit reviewed main source to the VPC CodeBuild project and wait for it."""
import hashlib
import io
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

from pipeline_common import ROOT, check_account, client, load_deployment, settings

FORBIDDEN = {".git", ".aws", ".terraform", ".data", "node_modules", "target", "dist", ".venv",
             "__pycache__", ".pytest_cache", "artifacts", "generated", ".preview-runtime"}


def source_archive(config, sha):
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(filter(None, files)):
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or any(part in FORBIDDEN for part in path.parts):
                continue
            if (path.name.startswith(".env") or ".tfstate" in path.name or ".tfplan" in path.name or path.name.endswith((".tfvars", ".tfvars.json", ".key", ".onnx"))) and not path.name.endswith(".example"):
                continue
            file = ROOT / path
            if file.is_symlink():
                raise RuntimeError("Platform source must not include symlinks")
            if file.is_file():
                archive.write(file, relative)
        archive.writestr("deploy/generated/aws.outputs.json", json.dumps(config))
        archive.writestr("deploy/generated/source.json", json.dumps({"sha": sha}))
    return buffer.getvalue()


def main(operation="bootstrap"):
    c = settings()
    check_account(c)
    config = load_deployment(c)
    deployment = config["deployment"]["value"]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    expected = os.environ.get("STOCKLANE_SOURCE_SHA") or os.environ["GITHUB_SHA"]
    if sha != expected:
        raise RuntimeError("Checked-out platform source does not match the reviewed commit")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("Platform bootstrap requires reviewed main source")
    if operation == "bootstrap":
        # Validate all configured controller and application patches without cluster access.
        subprocess.run(["python", "scripts/validate_kustomize.py", "--environment", c["environment"],
                        "--configured"], cwd=ROOT, check=True)
    payload = source_archive(config, sha)
    digest = hashlib.sha256(payload).hexdigest()
    key = f"sources/{c['environment']}/{sha}-{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}-{digest}.zip"
    response = client("s3", c).put_object(Bucket=c["automation_bucket"], Key=key, Body=payload,
        ServerSideEncryption="AES256", IfNoneMatch="*")
    version = response.get("VersionId")
    if not version or version == "null":
        raise RuntimeError("Platform source must be versioned")
    codebuild = client("codebuild", c)
    result = codebuild.start_build(projectName=deployment["platform_bootstrap_project"],
        sourceTypeOverride="S3", sourceLocationOverride=c["automation_bucket"] + "/" + key,
        sourceVersion=version,
        environmentVariablesOverride=[{"name": "REVIEWED_SOURCE_SHA", "value": sha, "type": "PLAINTEXT"},
                                      {"name": "STOCKLANE_OPERATION", "value": operation, "type": "PLAINTEXT"}])
    build_id = result["build"]["id"]
    print("Private VPC build:", build_id, flush=True)
    deadline = time.monotonic() + 55 * 60
    try:
        while time.monotonic() < deadline:
            builds = codebuild.batch_get_builds(ids=[build_id])["builds"]
            if not builds:
                raise RuntimeError("CodeBuild did not return the submitted build")
            build = builds[0]
            status = build["buildStatus"]
            if status == "SUCCEEDED":
                print("EKS platform is ready; API DNS is configured" if operation == "bootstrap"
                      else "Kubernetes load balancers and volumes released")
                return
            if status in {"FAILED", "FAULT", "STOPPED", "TIMED_OUT"}:
                logs = build.get("logs", {}).get("deepLink", "")
                raise RuntimeError("Platform bootstrap " + status + ". Inspect CodeBuild logs: " + logs)
            time.sleep(15)
        raise TimeoutError("Timed out waiting for the private bootstrap build")
    except BaseException:
        codebuild.stop_build(id=build_id)
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=["bootstrap", "teardown"], default="bootstrap")
    main(parser.parse_args().operation)


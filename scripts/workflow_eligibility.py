"""Select current, validated main commits for application/platform delivery."""
import argparse
import os
import subprocess
from pathlib import Path

APP_PREFIXES = ("apps/", "services/", "packages/", "models/", "mlops/", "deploy/docker/",
                "scripts/render_cloud.py", "scripts/build_release.py", "scripts/bootstrap_database.py")
INFRA_PREFIXES = ("infra/aws/", "infra/ci/", "deploy/codebuild/")
PLATFORM_PREFIXES = ("deploy/kubernetes/", "deploy/codebuild/", "scripts/bootstrap_eks.py",
                     "scripts/run_platform_bootstrap.py", "scripts/pipeline_platform.py")


def eligible(kind, paths, manual=False, current=True):
    if not current:
        return False
    if manual:
        return True
    if kind == "application":
        return any(p.startswith(APP_PREFIXES) for p in paths) and not any(p.startswith(INFRA_PREFIXES) for p in paths)
    # Mixed source/infrastructure uploads need their reviewed Terraform and image
    # release first. Bootstrap automatically only after the GitOps-only merge.
    return (any(p.startswith(PLATFORM_PREFIXES) for p in paths)
            and not any(p.startswith(INFRA_PREFIXES + APP_PREFIXES) for p in paths))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["application", "platform"], required=True)
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    latest = subprocess.check_output(["git", "ls-remote", "origin", "refs/heads/main"]).decode().split()[0]
    parent = subprocess.run(["git", "rev-parse", "--verify", "HEAD^"], capture_output=True)
    command = ["git", "diff", "--name-only", "HEAD^", "HEAD"] if parent.returncode == 0 else ["git", "ls-files"]
    paths = subprocess.check_output(command).decode().splitlines()
    result = eligible(args.kind, paths, manual=os.environ["EVENT_NAME"] == "workflow_dispatch", current=sha == latest)
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write("release=" + str(result).lower() + "\n")
    print("Delivery eligibility:", result)


if __name__ == "__main__":
    main()


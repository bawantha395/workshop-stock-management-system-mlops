"""Runs inside CodeBuild's private VPC network after a reviewed release."""
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

from bootstrap_eks import bootstrap
from kustomize_utils import KUBERNETES, environment, load_yaml


def main(args):
    config = json.loads(Path(args.config).read_text())
    c = config.get("deployment", {}).get("value", config)
    checks = {"account_id": os.environ["EXPECTED_ACCOUNT_ID"],
              "name": os.environ["EXPECTED_PROJECT"], "region": os.environ["EXPECTED_REGION"]}
    if any(c.get(k) != v for k, v in checks.items()):
        raise RuntimeError("Bootstrap configuration does not match the CodeBuild project")
    source = json.loads(Path("deploy/generated/source.json").read_text())
    if source["sha"] != os.environ["REVIEWED_SOURCE_SHA"]:
        raise RuntimeError("Source does not match the reviewed main commit")
    if boto3.client("sts").get_caller_identity()["Account"] != c["account_id"]:
        raise RuntimeError("AWS account mismatch")
    bootstrap(args)
    target, namespace = environment(c)
    env = os.environ.copy()
    env["KUBECONFIG"] = str(Path("deploy/generated/kubeconfig").resolve())
    root = load_yaml(KUBERNETES / "argocd/root" / (target + ".yaml"))
    deadline = time.monotonic() + 20 * 60
    def kubectl(*command):
        return subprocess.run(["kubectl", *command], env=env, capture_output=True, text=True, timeout=90)
    while time.monotonic() < deadline:
        status = kubectl("-n", "argocd", "get", "application", root["metadata"]["name"], "-o", "json")
        if status.returncode == 0:
            obj = json.loads(status.stdout).get("status", {})
            if obj.get("sync", {}).get("status") == "Synced" and obj.get("health", {}).get("status") == "Healthy":
                break
        time.sleep(10)
    else:
        raise TimeoutError("Argo CD root did not become Synced and Healthy. Inspect Argo CD/CodeBuild logs.")
    # Root health alone can remain green while a child still runs an old image.
    child = "stocklane-workshop-" + target
    kubectl("-n", "argocd", "annotate", "application", child,
            "argocd.argoproj.io/refresh=hard", "--overwrite")
    while time.monotonic() < deadline:
        result = kubectl("-n", "argocd", "get", "application", child, "-o", "json")
        obj = json.loads(result.stdout).get("status", {}) if result.returncode == 0 else {}
        if (obj.get("sync", {}).get("status") == "Synced"
                and obj.get("sync", {}).get("revision") == source["sha"]
                and obj.get("health", {}).get("status") == "Healthy"):
            break
        time.sleep(10)
    else:
        raise TimeoutError("Application child did not sync the reviewed commit; inspect its hook/resource errors")
    for name in ["inventory", "workshop", "vision"]:
        subprocess.run(["kubectl", "-n", namespace, "rollout", "status", "deployment/" + name,
                        "--timeout=300s"], env=env, check=True)
    # A public ALB health check does not exercise cross-service ClusterIP traffic.
    # Check the real Workshop network namespace without exposing internal tokens.
    connection_deadline = time.monotonic() + 180
    probe = ('exec 3<>/dev/tcp/inventory/8081; '
             'printf "GET /actuator/health/readiness HTTP/1.1\\r\\nHost: inventory\\r\\nConnection: close\\r\\n\\r\\n" >&3; '
             'IFS= read -r status <&3; printf "%s\\n" "$status"; [[ "$status" == *" 200 "* ]]')
    while time.monotonic() < connection_deadline:
        result = kubectl('-n', namespace, 'exec', 'deployment/workshop', '--',
                         'timeout', '10', 'bash', '-c', probe)
        if result.returncode == 0:
            print('Workshop-to-Inventory Service HTTP readiness passed')
            break
        time.sleep(5)
    else:
        raise RuntimeError('Workshop cannot reach Inventory through its Kubernetes Service. '
                           'Inspect Service endpoints, network policies and node networking.')
    while time.monotonic() < deadline:
        ingress = kubectl("-n", namespace, "get", "ingress", "api", "-o", "json")
        if ingress.returncode == 0 and json.loads(ingress.stdout).get("status", {}).get("loadBalancer", {}).get("ingress"):
            break
        time.sleep(10)
    else:
        raise TimeoutError("ALB did not receive an address")
    subprocess.run(["python", "scripts/configure_api_dns.py", "--config", args.config], env=env, check=True)
    # An unauthenticated catalogue request must reach the actual application.
    # Its expected authentication rejection is proof of routing, not business acceptance.
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("https://" + c["api_domain"] + "/api/inventory/products", timeout=15) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except (urllib.error.URLError, TimeoutError):
            status = None
        if status in {200, 401, 403}:
            print("Reviewed platform ready; authenticated business acceptance remains required")
            return
        time.sleep(10)
    raise TimeoutError("HTTPS API routing did not become ready")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    main(parser.parse_args())


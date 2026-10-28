"""Prepare a reviewed import after a cancelled apply; never edit remote state."""
import json
import os

from botocore.exceptions import ClientError
from pipeline_common import client, terraform_dir

MODULE = "module.eks"
ADDRESS = MODULE + ".aws_eks_node_group.main"
LEGACY_NAME = "cpu-workers"


def managed_resources(state, resource_type, name=None, *, module=MODULE):
    """Instances of one resource type; module=None searches every module."""
    return [instance["attributes"]
            for resource in state.get("resources", [])
            if resource.get("mode") == "managed" and (module is None or resource.get("module") == module)
            and resource.get("type") == resource_type
            and (name is None or resource.get("name") == name)
            for instance in resource.get("instances", [])
            if not instance.get("deposed") and instance.get("attributes")]


def prepare_nodegroup_recovery(c, adopt=False):
    generated = terraform_dir(c["environment"]) / "pipeline-recovery.tf"
    generated.unlink(missing_ok=True)
    state = json.loads(client("s3", c).get_object(
        Bucket=c["bucket"], Key=c["key"], ExpectedBucketOwner=c["account"])["Body"].read())
    if managed_resources(state, "aws_eks_node_group", "main"):
        print("Worker node group is already tracked; no import is required")
        return
    try:
        group = client("eks", c).describe_nodegroup(
            clusterName=c["project"], nodegroupName=LEGACY_NAME)["nodegroup"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        if adopt:
            raise RuntimeError("No legacy cpu-workers group exists to adopt. Request a normal plan with adoption disabled.") from error
        return

    legacy_id = c["project"] + ":" + LEGACY_NAME
    if any(item.get("id") == legacy_id for item in managed_resources(state, "aws_eks_node_group", module=None)):
        raise RuntimeError("The existing node group is tracked at another address; review a state move instead of importing it twice")
    clusters = managed_resources(state, "aws_eks_cluster", "main")
    roles = managed_resources(state, "aws_iam_role", "nodes")
    subnets = {item.get("id") for item in managed_resources(state, "aws_subnet", "private", module="module.network")}
    expected_cluster = f"arn:aws:eks:{c['region']}:{c['account']}:cluster/{c['project']}"
    expected_role = f"arn:aws:iam::{c['account']}:role/{c['project']}-nodes"
    expected_group = f"arn:aws:eks:{c['region']}:{c['account']}:nodegroup/{c['project']}/{LEGACY_NAME}/"
    tags = group.get("tags", {})
    owned = (len(clusters) == len(roles) == 1
             and clusters[0].get("arn") == expected_cluster
             and roles[0].get("arn") == expected_role
             and group.get("nodeRole") == expected_role
             and group.get("clusterName") == c["project"]
             and group.get("nodegroupName") == LEGACY_NAME
             and group.get("nodegroupArn", "").startswith(expected_group)
             and len(subnets) >= 2 and None not in subnets and set(group.get("subnets", [])) == subnets
             and tags.get("Project") == c["project"]
             and tags.get("Environment") == c["environment"]
             and tags.get("ManagedBy") == "Terraform")
    if not owned:
        raise RuntimeError("The existing cpu-workers group does not match this state's cluster, role, subnets and ownership tags. No import was prepared.")
    status = group.get("status")
    print("Existing untracked node group:", legacy_id, "status:", status,
          "instance types:", ",".join(group.get("instanceTypes", [])))
    for issue in group.get("health", {}).get("issues", []):
        print("Node-group health issue:", issue.get("code", "unknown"))
    if status not in {"ACTIVE", "DEGRADED", "CREATE_FAILED", "UPDATE_FAILED"}:
        raise RuntimeError("Wait for the existing node-group operation to finish before planning adoption")
    if not adopt:
        raise RuntimeError("A node group exists outside Terraform state. Run Plan AWS infrastructure manually with adopt_existing_nodegroup=true to review its import and replacement.")
    # Configuration-driven import is part of the saved plan. Only a later,
    # explicitly reviewed apply can write the imported resource to state.
    fd = os.open(generated, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write('import {\n  to = ' + ADDRESS + '\n  id = ' + json.dumps(legacy_id) + '\n}\n')
    generated.chmod(0o600)
    print("Prepared a plan-only import of", legacy_id, "at", ADDRESS)


def check_change_approval(summary, allow_deletions=False, allow_nodegroup_replacement=False):
    deletions = [item for item in summary["resources"] if "delete" in item["actions"]]
    if not deletions or allow_deletions:
        return
    if allow_nodegroup_replacement and all(
            item["address"] == ADDRESS and item["actions"] == ["create", "delete"] for item in deletions):
        return
    raise RuntimeError("Plan includes deletes/replacements without approval. The node-group-only approval permits only create-before-destroy replacement of " + ADDRESS + "; review all other changes separately.")


def check_worker_quota(c, inputs, document):
    if not any(change["address"] == ADDRESS and "create" in change["change"]["actions"]
               for change in document.get("resource_changes", [])):
        return
    ec2 = client("ec2", c)
    instance_type = inputs.get("node_instance_type", "m6i.large")
    info = ec2.describe_instance_types(InstanceTypes=[instance_type])["InstanceTypes"][0]
    if "x86_64" not in info["ProcessorInfo"]["SupportedArchitectures"]:
        raise RuntimeError("The worker type must support the configured x86_64 EKS AMI")
    required = info["VCpuInfo"]["DefaultVCpus"] * inputs.get("node_desired_size", 3)
    running_types = []
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["pending", "running"]}])
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                family = instance["InstanceType"].split(".")[0]
                if (instance.get("InstanceLifecycle") or instance.get("Placement", {}).get("Tenancy") == "host"
                        or family[0] not in "acdhimrtz" or family.startswith(("hpc", "mac"))):
                    continue
                running_types.append(instance["InstanceType"])
    # EC2 quota usage follows the type's default vCPU count, even when CPU
    # options expose fewer cores to the guest operating system.
    vcpus = {instance_type: info["VCpuInfo"]["DefaultVCpus"]}
    missing = sorted(set(running_types) - vcpus.keys())
    for offset in range(0, len(missing), 100):
        for current in ec2.describe_instance_types(InstanceTypes=missing[offset:offset + 100])["InstanceTypes"]:
            vcpus[current["InstanceType"]] = current["VCpuInfo"]["DefaultVCpus"]
    used = sum(vcpus[kind] for kind in running_types)
    quota = client("service-quotas", c).get_service_quota(
        ServiceCode="ec2", QuotaCode="L-1216C47A")["Quota"]["Value"]
    print(f"Worker capacity: {instance_type}, {info['MemoryInfo']['SizeInMiB']} MiB per node. "
          f"Standard On-Demand vCPUs: {used} current + {required} new, quota {quota:g}.")
    if used + required > quota:
        raise RuntimeError("EC2 vCPU quota cannot fit the new workers alongside current instances. "
                           "No approved plan was published. Review the quota or a separate retirement plan; "
                           "do not delete running workers or reset state to bypass this check.")

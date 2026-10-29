"""Clean-up around `terraform destroy` that Terraform cannot do by itself.

    before  delete registered SageMaker model versions (a Model Registry group
            cannot be deleted while it holds versions)
    sweep   delete AWS resources Kubernetes created outside Terraform: load
            balancers, their target groups and security groups, released EBS
            volumes, leftover network interfaces and the api/argocd/grafana
            DNS aliases
    check   fail if anything billable from this environment still exists

The Destroy workflow runs: platform teardown (inside the cluster) -> before ->
sweep -> terraform destroy -> sweep -> check.
"""
import argparse
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

from pipeline_common import check_account, client, settings


def tags_match(tags, cluster):
    keys = {t["Key"]: t["Value"] for t in tags}
    return (keys.get("elbv2.k8s.aws/cluster") == cluster or "kubernetes.io/cluster/" + cluster in keys
            or keys.get("KubernetesCluster") == cluster or keys.get("eks:cluster-name") == cluster)


def owned_by_controller(tags, cluster):
    """Load balancers and target groups: only what the AWS Load Balancer Controller made."""
    return {t["Key"]: t["Value"] for t in tags}.get("elbv2.k8s.aws/cluster") == cluster


def cluster_load_balancers(elb, cluster):
    found = []
    for page in elb.get_paginator("describe_load_balancers").paginate():
        arns = [lb["LoadBalancerArn"] for lb in page["LoadBalancers"]]
        for start in range(0, len(arns), 20):
            for description in elb.describe_tags(ResourceArns=arns[start:start + 20])["TagDescriptions"]:
                if owned_by_controller(description["Tags"], cluster):
                    found.append(description["ResourceArn"])
    return found


def project_vpcs(ec2, project):
    return [v["VpcId"] for v in ec2.describe_vpcs(Filters=[{"Name": "tag:Project", "Values": [project]}])["Vpcs"]]


def delete_model_versions(c):
    """Model Registry groups only delete when empty; versions are training output."""
    sm = client("sagemaker", c)
    for group in [c["project"] + "-visual-sku"]:
        try:
            pages = sm.get_paginator("list_model_packages").paginate(ModelPackageGroupName=group)
            versions = [p["ModelPackageArn"] for page in pages for p in page["ModelPackageSummaryList"]]
        except ClientError as error:
            if error.response["Error"]["Code"] in {"ValidationException", "ResourceNotFound"}:
                continue
            raise
        for arn in versions:
            sm.delete_model_package(ModelPackageName=arn)
            print("Deleted model version", arn.rsplit("/", 2)[-2] + "/" + arn.rsplit("/", 1)[-1])


def sweep(project, region, domains, zone_id, sleep=time.sleep):
    cluster = project
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
        sleep(10)
    groups = [g["TargetGroupArn"] for page in elb.get_paginator("describe_target_groups").paginate()
              for g in page["TargetGroups"]]
    for start in range(0, len(groups), 20):
        for description in elb.describe_tags(ResourceArns=groups[start:start + 20])["TagDescriptions"]:
            if owned_by_controller(description["Tags"], cluster):
                elb.delete_target_group(TargetGroupArn=description["ResourceArn"])
                print("Deleted target group", description["ResourceArn"].rsplit("/", 2)[-2])
    vpcs = project_vpcs(ec2, project)
    if vpcs:
        # Security groups made by the load balancer controller (never Terraform's).
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
                    sleep(10)
        for interface in ec2.describe_network_interfaces(Filters=[
                {"Name": "vpc-id", "Values": vpcs}, {"Name": "status", "Values": ["available"]}])["NetworkInterfaces"]:
            if interface.get("Description", "").startswith(("aws-K8S", "Amazon EKS")):
                try:
                    ec2.delete_network_interface(NetworkInterfaceId=interface["NetworkInterfaceId"])
                    print("Deleted leftover network interface", interface["NetworkInterfaceId"])
                except ClientError:
                    pass
    for page in ec2.get_paginator("describe_volumes").paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
            if tags_match(volume.get("Tags", []), cluster):
                ec2.delete_volume(VolumeId=volume["VolumeId"])
                print("Deleted Kubernetes volume", volume["VolumeId"])
    route53 = boto3.client("route53")
    wanted = {d.rstrip(".") + "." for d in domains if d}
    changes = [{"Action": "DELETE", "ResourceRecordSet": record}
               for page in route53.get_paginator("list_resource_record_sets").paginate(HostedZoneId=zone_id)
               for record in page["ResourceRecordSets"]
               if record["Name"] in wanted and record["Type"] in {"A", "AAAA"}
               and "elb.amazonaws.com" in record.get("AliasTarget", {}).get("DNSName", "")]
    if changes:
        route53.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch={
            "Comment": "Stocklane teardown", "Changes": changes})
        for change in changes:
            print("Deleted DNS alias", change["ResourceRecordSet"]["Name"])


def leftovers(project, region):
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
        "EBS volumes": [v["VolumeId"] for page in ec2.get_paginator("describe_volumes").paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]) for v in page["Volumes"]
            if tags_match(v.get("Tags", []), project)],
    }
    billable = {k: v for k, v in remaining.items() if v}
    for kind, items in billable.items():
        print("Still present -", kind + ":", ", ".join(items))
    if not billable:
        print("No billable", project, "resources remain. Kept: state bucket, CI identity, hosted zone.")
    return not billable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["before", "sweep", "check"])
    parser.add_argument("--domains", default="[]", help="JSON list of api/argocd/grafana hostnames")
    parser.add_argument("--zone-id", default="")
    args = parser.parse_args(argv)
    c = settings()
    check_account(c)
    if args.step == "before":
        delete_model_versions(c)
    elif args.step == "sweep":
        sweep(c["project"], c["region"], json.loads(args.domains), args.zone_id)
    elif not leftovers(c["project"], c["region"]):
        sys.exit(1)


if __name__ == "__main__":
    main()

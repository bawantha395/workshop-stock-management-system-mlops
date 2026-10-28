# Workshop-to-Inventory Service Connectivity

## Evidence and change

The live tests showed DNS resolving Inventory to 172.20.147.62, direct Pod TCP
connectivity succeeding, and Service IP TCP connectivity failing. An additive
Workshop egress policy permitting the Inventory selector and Service IP restored
connectivity. The existing test job was then registered and stock issue worked.

The permanent YAML uses the same policy name, `workshop-to-inventory-service`,
so Argo CD adopts the tested rule instead of leaving a separate manual exception.
It selects only Workshop pods and permits TCP 8081 to Inventory pods and the
cluster Service CIDR. It does not permit arbitrary ports or 0.0.0.0/0. Because
NetworkPolicy cannot express an intersection of Service VIPs and pod labels,
the CIDR branch permits other Service addresses on port 8081 as well; destination
network policies and application authentication still apply. It is not a
per-Service identity guarantee.

The individual Service VIP is not stored in source. Terraform declares
`service_ipv4_cidr` and exports the actual EKS Service CIDR. The release renderer
uses that output to generate an environment-specific policy patch. Existing
outputs without the new field retain this project's 172.20.0.0/16 default.
Each Kustomize environment includes the policy through the shared base.

## Upload these files

```
deploy/kubernetes/apps/base/shared/kustomization.yaml
deploy/kubernetes/apps/base/shared/workshop-inventory-networkpolicy.yaml
scripts/render_cloud.py
scripts/run_platform_bootstrap.py
infra/terraform/environments/dev/variables.tf
infra/terraform/environments/dev/compute.tf
infra/terraform/environments/dev/outputs.tf
tests/test_kustomize.py
docs/NETWORK_POLICY_FIX.md
```

Copy these files into the current repository, preserving unrelated changes,
commit and push. The source is based on main 4df7320, including release PR #12.
Wait for Validate platform, then Bootstrap EKS platform. This is a policy and
bootstrap change; it needs no container rebuild. Do not delete the working live
policy or the completed database Job before GitOps adopts them.

The new bootstrap gate makes an actual HTTP readiness request from Workshop to
`http://inventory:8081/actuator/health/readiness`, with a bounded retry window.
A connection failure stops frontend publication and reports an internal Service
connectivity error. This probe uses no authentication secrets.

## Terraform review

Before applying the Terraform declaration, check the actual immutable CIDR:

```bash
aws eks describe-cluster --region ap-southeast-2 --name stocklane-dev \
  --query 'cluster.kubernetesNetworkConfig.serviceIpv4Cidr' --output text
```

For this project's default, expect `172.20.0.0/16`. If the value differs, set
`service_ipv4_cidr` to that existing value in TFVARS_JSON and configure the
policy accordingly before deployment. Never change the CIDR of an existing
cluster merely to match the default. Review a new Terraform plan: this update
must not replace the cluster or database. Applying the reviewed plan publishes
the new output for future release renders. It is not required just to adopt
the policy in the current default-CIDR cluster.

## Acceptance

1. Confirm the Argo CD application is Synced/Healthy and the named policy shows
   its Argo CD tracking annotation. Inspect the live policy: the IP block must
   be the configured Service CIDR rather than the old individual /32.
2. The platform log must include:
   `Workshop-to-Inventory Service HTTP readiness passed`.
3. Create one new test repair job and issue a part. Confirm inventory decreases
   once and the new job is registered without any manual registration request.
4. Return the unused part, finalise its invoice, and confirm balances after reload.

Local verification: the existing 120 pipeline/Kustomize checks passed and the
additional custom-Service-CIDR test passed with the Kustomize suite (21 tests).
Terraform formatting, Python compilation and whitespace checks passed. The
new HTTP gate has not run against AWS from this build environment. Full GitHub
CI and the live platform gate must pass after upload.

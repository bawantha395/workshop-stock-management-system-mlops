# Recover the interrupted AWS apply

Repository: `bawantha395/workshop-stock-management-system-mlops`.
AWS account: `721274598579`. Region: Sydney, `ap-southeast-2`.

The latest log reports an existing EKS `cpu-workers` group while Terraform
attempts to create it, and RDS cannot create its managed master-password secret.
A cancelled apply can leave a resource in AWS before its ID is persisted to
state. Removing a stale lock permits access to state; it does not import that
resource. Keep the existing backend, state versions and completed resources.

## What changes

- The apply role gains `secretsmanager:CreateSecret` and `TagResource` for
  RDS-managed instance secrets named `rds!db-*` in this account and Region.
  Existing project-secret permissions cover `stocklane-dev/*`, which does not
  include RDS's generated names. This new statement grants no password reads
  or secret deletion. Existing regional KMS permissions remain in place.
- The demo profile uses two `m7i-flex.large` On-Demand workers, each with
  2 vCPUs and 8 GiB RAM. AWS lists this type for the newer Free Tier. Eligible
  usage consumes credits; it is not an unlimited free cluster.
- AWS's published policy for this project-account experience denies Spot
  requests and Spot market launches. No Spot Fleet or policy bypass is added.
- Workers use a generated `cpu-workers-` name and create-before-destroy.
  Changing instance types requires replacement; reusing a fixed name would
  collide with the existing group. Old and new workers briefly overlap and
  need enough EC2 quota. Planning checks that quota before publishing a plan.
- RDS stays Single-AZ `db.t4g.micro`, 20 GiB `gp2`, one-day backups and no
  storage autoscaling. The production capacity profile stays unchanged.

## 1. Upload the update and validate

Copy the project contents into your existing repository and push to `main`.
Wait for **Validate platform** on that commit. If a plan automatically starts
before you update IAM/configuration, request a new plan after the next steps.

## 2. Update the existing AWS trust stack

Use an authenticated Sydney CloudShell session. No Terraform installation is
needed for this bootstrap, and no new AWS access key is requested.

```bash
export AWS_REGION=ap-southeast-2
export AWS_DEFAULT_REGION=ap-southeast-2
cd ~/workshop-stock-management-system-mlops
git pull --ff-only

python3 scripts/bootstrap_pipeline.py \
  --repository bawantha395/workshop-stock-management-system-mlops \
  --project-name stocklane-dev \
  --environment dev \
  --capacity-profile demo \
  --auth-mode access-key \
  --region ap-southeast-2 \
  --expected-account 721274598579 \
  --hosted-zone-id Z035879924YQHJ4M5G2A3 \
  --api-domain api.stocklane.bawantha-rathnayake.tech \
  --budget-email 'bawantharathnayake395@gmail.com' \
  --execute
```

Expect an `ApplyRole` policy update and the existing EKS service-linked-role
verification. If the checkout is missing in a new CloudShell home, clone the
repository first. Keep any specific authorization error for investigation.

## 3. Replace TFVARS_JSON with the full generated object

The existing secret contains `t3.micro`; editing the default profile alone
cannot override that explicit input. Print the generated configuration:

```bash
python3 -c 'import json; print(json.dumps(json.load(open("deploy/generated/github-setup.json"))["repository_secret"]["value"], indent=2))'
```

Paste the complete object into GitHub **Settings → Secrets and variables →
Actions → Repository secrets → TFVARS_JSON → Update**. It must include
`"node_instance_type": "m7i-flex.large"`. Keep both existing AWS access-key
secrets and repository variables.

## 4. Plan the import and worker replacement

Open **Actions → Plan AWS infrastructure → Run workflow → main**.
Set **adopt_existing_nodegroup=true** for this recovery.

The planner reads the current state and EKS metadata. It only prepares an
import when the old group matches this state's cluster ARN, worker IAM role,
private subnets, Project/Environment/ManagedBy tags, account and Region.
Groups in CREATING, UPDATING or DELETING must finish first. A group already
tracked in state does not need another import. A group tracked at another
address is not imported twice.

Review the existing group's status and health codes in the log. The saved plan
should include an import at `aws_eks_node_group.main` if it was untracked,
followed by creation of a uniquely named group and deletion of the legacy
group. The summary shows import/create/delete counts and addresses. The new
workers should use `m7i-flex.large`; RDS should use the settings above.

Planning does not modify state or delete workers. The import is embedded in
the private saved plan for the reviewed apply. If ownership checks or the EC2
quota check fail, retain the exact message; do not delete resources or reset
state. Quotas and real regional capacity still govern successful creation.

## 5. Apply the newly reviewed plan

Open **Apply reviewed Terraform plan** on `main` and set:

| Input | Value |
| --- | --- |
| plan_id | This new plan's ID |
| plan_sha256 | This new plan's checksum |
| allow_deletions | false |
| allow_nodegroup_replacement | true, after reviewing this worker replacement |
| prepare_release | false |

The targeted approval permits only create-before-destroy replacement of
`aws_eks_node_group.main`. An unrelated deletion or a destroy-before-create
replacement still fails approval. Do not reuse a plan from an earlier apply
or from before the IAM/configuration update.

Wait for the apply to finish. After infrastructure succeeds, continue with
**Prepare AWS release**, its reviewed GitOps PR, and **Bootstrap EKS platform**
using [PIPELINE_SETUP.md](PIPELINE_SETUP.md). Application readiness has not been
verified just because Terraform succeeds.

## State locks after interruptions

Keep S3 native locking and bucket versioning. Plan and apply share one GitHub
concurrency group and do not automatically cancel each other. DynamoDB locking
is deprecated; either mechanism can retain a lock after a forced cancellation.
Do not disable locking or automatically expire/delete a lock by age.

If a lock remains, first confirm all Terraform writers are stopped and match
the lock ID to your cancelled run. Use `terraform force-unlock LOCK_ID` only
from the matching initialized backend, or deliberately remove only that
verified `.tflock` object. Keep `terraform.tfstate` and its version history.
Generate a fresh plan afterward; investigate any AWS/state mismatch separately.

## References

- [RDS managed-password permissions](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html)
- [EC2 Free Tier eligible instance types](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html)
- [EC2 instance specifications](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html)
- [Managed project policies, including Spot denials](https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html)
- [Terraform imports](https://developer.hashicorp.com/terraform/language/import)
- [S3 backend locking and DynamoDB deprecation](https://developer.hashicorp.com/terraform/language/backend/s3)

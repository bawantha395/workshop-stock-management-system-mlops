# Resume the partially completed AWS apply

For `bawantha395/workshop-stock-management-system-mlops`, AWS account
`721274598579`, Sydney `ap-southeast-2`, environment `stocklane-dev`.

The apply completed some resources, including ElastiCache, then reported four
errors. A failed Terraform apply does not roll back resources that succeeded.
Keep the existing remote state bucket and key. Completed resources can continue
using credits while deployment is paused.

## What changed

| Failure | Correction |
| --- | --- |
| EKS could not validate `AWSServiceRoleForAmazonEKSNodegroup` | The plan/apply roles can read that exact service-linked role ARN. Existing permission to create the EKS service-linked role stays service-scoped. |
| RDS rejected 14 days of backups on this Free plan | Dev/test/UAT default to one day of automated backups. Production retains its 14-day default. `database_backup_retention_days` supports an explicit account-compatible override from 1 to 35 whole days. |
| AWS Budgets denied `budgets:TagResource` | Apply can tag/untag the one project monthly budget. Plan/apply can read that budget's tags for refresh. |
| SNS rejected the topic policy's action scope | Owner and TLS-deny statements enumerate SNS's supported topic-policy actions. CloudWatch's source-account/source-alarm constraints and topic encryption remain. |

AWS documents the [SNS topic-policy action list](https://docs.aws.amazon.com/sns/latest/dg/sns-access-policy-language-api-permissions-reference.html),
[budget tagging permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_budgets.html),
[EKS node-group service-linked role](https://docs.aws.amazon.com/eks/latest/userguide/using-service-linked-roles-eks-nodegroups.html)
and [RDS backup retention settings](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.BackupRetention.html).
The supplied error confirms that this account rejected 14 days; the one-day
setting is a conservative correction and still needs acceptance by this account.
It is not a claim that AWS publishes a universal one-day Free-plan maximum.

## 1. Upload the corrected files to the existing repository

Copy this project's contents into your existing Git checkout, keeping its Git
history, then commit and push to `main`. The functional changes are in:

- `infra/ci/identity.json`
- `infra/aws/variables.tf`
- `infra/aws/data.tf`
- `infra/aws/ml-observability.tf`

The archive also includes regression tests and this recovery guide. Wait for
**Validate platform** to pass on the new commit. A push may automatically start
a Terraform plan; generate another after the permission update below completes.

## 2. Update the existing pipeline-role policies once in CloudShell

The CI apply role deliberately cannot modify its own permissions. Run this
through your existing operator session in CloudShell. The helper updates the
existing `stocklane-dev-github-trust` CloudFormation stack. It creates no new
access key because `--create-access-key` is omitted.

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

Expect changes to `PlanRole` and `ApplyRole`, followed by **AWS trust is ready**.
Keep the GitHub secrets and variables already configured. The helper writes its
local setup handoff again, but does not change GitHub settings. The existing
`TFVARS_JSON` with environment `dev` already selects one-day backups when no
explicit retention override is present.

## 3. Generate a fresh plan and apply it

1. Open **Actions → Plan AWS infrastructure → Run workflow**, branch `main`.
2. Review the new summary. Terraform refreshes the existing state and should
   retain completed resources. If it proposes unexpected deletions or
   replacements, inspect them before proceeding.
3. Open **Apply reviewed Terraform plan**, branch `main`, and enter this new
   plan's ID and SHA256. Set `allow_deletions` to `false` and
   `prepare_release` to `true`.
4. After apply succeeds, follow the automatically dispatched **Prepare AWS
   release** workflow and review its deployment PR as described in
   [PIPELINE_SETUP.md](PIPELINE_SETUP.md).

The old saved plan is stale after a partial apply. Do not use its ID/checksum,
delete the state, destroy the stack or start from an empty state. The existing
Terraform backend does not need to be bootstrapped again for this fix.

# Resume AWS with the minimum demo database

Repository: `bawantha395/workshop-stock-management-system-mlops`.
AWS account: `721274598579`. Region: Sydney, `ap-southeast-2`.

SNS and the monthly budget completed in the latest apply. EKS node-group
creation still reported a service-linked-role read error; RDS rejected the
previous `db.t4g.small` class. Keep the existing resources and remote state.

## Current corrections

| Setting | Demo value |
| --- | --- |
| Database class | `db.t3.micro` |
| Database availability | Single-AZ |
| Database storage | 20 GiB `gp2` |
| Storage autoscaling | Disabled, maximum allocated storage `0` |
| Automated backups | One day |

AWS's [PostgreSQL getting-started guide](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_GettingStarted.CreatingConnecting.PostgreSQL.html)
uses `db.t3.micro` for its Free tier example. Account eligibility and available
regional capacity still need confirmation during deployment. This is the demo
profile; the production capacity profile keeps its existing settings.

The updated CloudShell bootstrap verifies the account-wide
`AWSServiceRoleForAmazonEKSNodegroup`. It creates that AWS-managed role only
when IAM reports `NoSuchEntity`. Existing roles are reused; denied reads do not
trigger a creation attempt. The role is a shared account prerequisite, not a
Terraform-managed role that should be destroyed with one application.

The plan and apply workflows now test their own `iam:GetRole` access before
Terraform initialization. They distinguish a missing role from a denied read.
The repeated EKS message alone does not establish which condition caused the
server-side validation error. The new check supplies direct evidence instead
of widening IAM permissions without evidence.

## 1. Update the existing repository

Copy the updated project contents into your existing checkout, then commit and
push to `main`. Keep the existing repository and history. The additional runtime
changes for this follow-up are:

- `infra/ci/capacity-demo.json`
- `infra/aws/variables.tf`
- `infra/aws/data.tf`
- `scripts/bootstrap_pipeline.py`
- `scripts/pipeline_common.py`
- `scripts/pipeline_terraform.py`

The archive also retains the earlier IAM, Cognito, SNS and backup corrections,
and includes the tests and updated guides. Wait for **Validate platform** to
pass on the new commit.

## 2. Run the updated bootstrap in CloudShell

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

An unchanged trust-stack template is expected when the IAM correction has
already been applied. The helper still checks the service-linked role when
`--execute` is supplied. Expect:

```text
EKS node-group service-linked role is ready: arn:aws:iam::721274598579:role/aws-service-role/eks-nodegroup.amazonaws.com/AWSServiceRoleForAmazonEKSNodegroup
```

If IAM denies this step, retain that specific error. The helper does not change
SCPs or treat denied reads as missing roles. No new access key is requested.

## 3. Replace only the TFVARS_JSON secret

This time the existing GitHub secret must change: it still contains the old
RDS class. Source defaults cannot override an explicit value in that secret.

Print the new configuration object in your own CloudShell session:

```bash
python3 -c 'import json; print(json.dumps(json.load(open("deploy/generated/github-setup.json"))["repository_secret"]["value"], indent=2))'
```

Copy the complete printed object into GitHub **Settings → Secrets and variables
→ Actions → Repository secrets → TFVARS_JSON → Update**.

Verify these entries are present:

```json
"database_instance_class": "db.t3.micro",
"database_multi_az": false,
"database_storage_type": "gp2",
"database_max_allocated_storage": 0,
"database_backup_retention_days": 1
```

Keep the existing `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and repository
variables. The printed configuration is not a replacement for those keys.

## 4. Request a new plan, then apply that plan

1. Run **Plan AWS infrastructure** on `main` after the bootstrap and secret
   update. A plan automatically started by the earlier push may use old inputs;
   request a fresh one now.
2. Check for **Verified EKS service-linked role with current workflow
   credentials**. If this check fails, use its specific missing-role or denied
   permission error before another apply.
3. Review the plan log and summary. RDS should request `db.t3.micro`, 20 GiB,
   `gp2`, one-day backups and Single-AZ. Existing completed resources should be
   retained. Inspect unexpected deletions or replacements before proceeding.
4. Run **Apply reviewed Terraform plan** on `main`, supplying this new plan's
   ID and SHA256, `allow_deletions=false` and `prepare_release=true`.

Do not reuse a plan from before either the partial apply or secret update.
The existing state bucket/key stays in use. After a successful apply, follow
**Prepare AWS release** and its deployment PR using [PIPELINE_SETUP.md](PIPELINE_SETUP.md).

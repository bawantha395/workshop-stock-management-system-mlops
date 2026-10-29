# Infrastructure

Two layers. The **foundation** is created once per environment and is never
destroyed; the **environment** is everything Terraform builds and can be
destroyed and recreated in one pipeline run.

```
infra/
├── ci/                         FOUNDATION (CloudFormation, once per environment)
│   ├── state.json              private, versioned Terraform state bucket
│   └── identity.json           GitHub/CI roles + permissions boundary for every role Terraform creates
│
└── terraform/                  ENVIRONMENT (Terraform)
    ├── modules/                reusable building blocks, one per AWS concern
    │   ├── network/            VPC, public/private subnets, NAT, S3 endpoint
    │   ├── data/               KMS, S3 buckets, SQS, PostgreSQL, Redis, secrets
    │   ├── registry/           ECR repositories
    │   ├── eks/                cluster, managed nodes, core add-ons
    │   ├── workload-identity/  one IAM role per Kubernetes service account (Pod Identity)
    │   ├── edge/               CloudFront, ACM certificates, Route 53 records
    │   ├── auth/               Cognito user pool and clients
    │   ├── ml/                 SageMaker roles + Model Registry, Bedrock model access
    │   ├── observability/      logs, alarms, SNS alerts, budget, alarm root-cause Lambda
    │   └── cicd/               GitHub deploy roles, automation bucket, private CodeBuild runner
    │
    └── environments/
        ├── dev/                main.tf composes the modules; terraform.tfvars = small, disposable
        ├── staging/            same main.tf; production-like but smaller, disposable
        └── prod/               same main.tf; 3 AZs, NAT per AZ, Multi-AZ DB, deletion protection
```

## How an environment is defined

`environments/<env>/main.tf`, `variables.tf`, `outputs.tf` and `versions.tf` are
identical in every environment (a test enforces this). Only two things differ:

| What | Where | Example |
| --- | --- | --- |
| Size and protection | `environments/<env>/terraform.tfvars` (committed) | node type, DB class, `deletion_protection` |
| Account-specific values | `TFVARS_JSON` GitHub secret, written to `pipeline.auto.tfvars.json` at run time | admin ARN, your IP, domains, alert email |
| State | `state/<env>/terraform.tfstate` in that environment's state bucket | — |

`deletion_protection = false` (dev, staging) makes teardown a single
`terraform destroy`: no final DB snapshot, buckets and images emptied, secrets
deleted immediately. `true` (prod) turns all of that protection back on.

## Module dependencies

```
network ─┬─ data ─┬─ registry ── ml
         │        ├─ edge ── auth
         └─ eks ──┴─ workload-identity, observability, cicd
```

Modules only talk through inputs and outputs. For example, `network` publishes
its private subnet IDs only after the NAT routes exist, so EKS nodes, RDS and
CodeBuild never start without internet access.

## Running it

The **Deploy environment** and **Destroy environment** pipelines run Terraform
(see [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md)).
Locally, for checks only:

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/environments/dev init -backend=false
terraform -chdir=infra/terraform/environments/dev validate
```

A new environment needs its own foundation: run `scripts/bootstrap_pipeline.py`
with `--environment staging --project-name stocklane-staging` (or `prod`).

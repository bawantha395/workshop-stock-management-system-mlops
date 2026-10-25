# Stocklane - Workshop Stock AI

Start with **[START_HERE.md](START_HERE.md)** for the complete-project ZIP,
GitHub upload instructions and the first validation step. The
**[folder guide](docs/REPOSITORY_STRUCTURE.md)** explains where to make each change.

A workshop inventory application built with **React + TypeScript**, two
**Spring Boot** microservices and a **Python vision service**. Track receipts,
issue parts to repair jobs, return unused items and create reconciled invoices.
Use approved reference photos to help identify existing products. New items
wait for a mechanic's review.

This repository is a new project. It does not depend on the housing-loan app
or the earlier DevOps assistant.

## Deploy on AWS

**Deployment now runs through GitHub Actions.** Start with
**[the pipeline setup guide](docs/PIPELINE_SETUP.md)**. A one-time AWS OIDC trust
setup enables backend creation, saved Terraform plans, explicit reviewed applies,
release PR preparation, private CodeBuild platform bootstrap and frontend publication.
Workflows use temporary AWS credentials and the Sydney Region (`ap-southeast-2`).

**AWS is the deployment target.** Mechanics use the HTTPS web application on
their phones or computers. They do not install a model or run an application
server. GitHub Actions builds the model/runtime artifacts; EKS serves them.

The production profile includes:

- Three availability zones, private worker subnets and a NAT gateway per zone.
- Three EKS workers, three replicas per application, HPA and disruption budgets.
- Private Multi-AZ RDS PostgreSQL, encrypted storage and 14-day backups.
- ElastiCache primary/replica across zones with automatic failover.
- Cognito staff sign-in with required MFA, scoped camera access and private application secrets.
- Separate internal read/control/capture capabilities, network policies and
  non-root containers. Metrics tokens cannot authorise inventory changes.
- Private S3, CloudFront, ACM HTTPS, ECR image digests and reviewed GitOps releases.

Review the **[Kustomize architecture](docs/KUSTOMIZE.md)** and follow
**[AWS deployment steps](docs/AWS_DEPLOYMENT.md)**. The first account setup
uses **AWS CloudShell once** to establish OIDC trust. Backend creation,
Terraform plans/applies, image builds, private EKS bootstrap and frontend
publication then run through pipelines. The guide uses your Sydney account,
repository and owned API hostname/Route 53 zone. No cloud resources have been
created from this build.

The default pipeline capacity is the smaller demo profile. Both demo and
production profiles have continuing AWS charges and consume eligible credits.
Review the actual Terraform plan and regional prices before applying it.

Optional Docker and developer-test instructions are in
[docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md).

## Try the complete flow

1. **Inventory -> Register product.** Create an exact SKU: brand, grade/part
   number and capacity. Enter a physically counted opening quantity of **50**.
2. **Capture & receive.** Upload a clear photo. Select the exact approved item,
   confirm **10** units and optionally save the checked photo as a reference.
   Shelf stock becomes **60**. A subsequent delivery creates a new receipt,
   while a retry of the same command returns the original result.
3. **Repair jobs -> New repair job.** Enter the customer and vehicle.
4. **Issue parts.** Issue **2** units to that job. Shelf stock becomes **58**.
5. **Return.** Select the original issue and return **1** unused sealed unit.
   Shelf stock becomes **59**.
6. **Review usage & invoice.** Confirm labour and finalise. The final invoice
   uses **1** net unit plus labour. Download its PDF from the job or Invoices.
7. **New item.** Capture an unfamiliar item and create a draft. If Bedrock is
   configured, it proposes visible label fields. Otherwise, a manual draft
   stays blank for review. Approve a new SKU or link to an existing product.

2L, 4L and 8L bottles are **different SKUs**. Sealed containers use whole units.
Bulk stock can use litres with confirmed measurements. A photo does not measure
the remaining contents of an opaque bottle.

## What is implemented

| Area | Implementation |
| --- | --- |
| Web application | Dashboard, inventory search, receipts, capture matching, review queue, jobs, returns, invoices, CSV exports and activity. Sticky top bar and responsive layout. |
| Inventory service | PostgreSQL stock ledger, exact SKU catalogue, row locking, non-negative balances, command idempotency, original-issue returns, job freeze and transactional outbox with retry backoff. |
| Workshop service | Customer/vehicle job cards, QR job links, idempotent event projections, authoritative invoice reconciliation, frozen-job protection and PDF generation. |
| Vision service | Real CPU MobileNetV2 image embeddings through OpenCV DNN, reference matching, pgvector storage, versioned caches, manual/Bedrock drafts, camera inbox and approval checks. |
| Cache | Redis locally; ElastiCache Redis OSS on AWS. Catalogue metadata and exact-image embeddings/drafts use bounded TTLs. Current stock and invoices come from database transactions. |
| Camera agent | Controlled-tray stable-frame capture, one encounter ID per item, durable SQLite spool, retries and scoped Cognito M2M authentication. Creates pending evidence; never posts stock itself. |
| AWS IaC | VPC, private EKS workers, ECR, private RDS, ElastiCache, S3/CloudFront, Cognito, SQS/DLQs, IAM/Pod Identity, KMS, Secrets Manager, ACM and CloudWatch alarms. |
| Delivery | GitHub Actions checks, digest-based image builds, staged frontend artifacts, reviewed GitOps release PR, Argo CD and separate frontend publication. |
| MLOps | SageMaker training container, real workshop-data validation, same-SKU calibrator training, independent quality gates, pending Model Registry approval and checked artifact promotion. |
| Observability | Kustomize-managed Prometheus/Grafana, authenticated application metrics, CloudWatch container logs, encrypted SNS notifications and replicated Prometheus/Alertmanager. |

The supplied encoder is **ImageNet-pretrained**, not trained on your brother's
stock. Similarity scores are not confidence percentages. This release always
requires a person to confirm movements. The training pipeline learns a pair
calibrator while retaining the frozen image encoder; it does not fine-tune a
deep learning network in this milestone.

## Repository layout

```text
apps/web/                  React application
packages/platform-java/    Shared security, API errors and idempotency
services/inventory/        Spring Boot inventory service and Flyway migrations
services/workshop/         Spring Boot jobs, events and invoices
services/vision/           FastAPI image matching, drafts and capture inbox
edge/                      Fixed-camera capture agent
mlops/                     Training, evaluation, serving contract and promotion
models/                    Model preparation instructions; generated weights ignored
infra/ci/                  One-time OIDC trust, pipeline state backend and capacity profiles
infra/bootstrap/           Optional manual Terraform state bootstrap
infra/aws/                 AWS resources and IAM roles
deploy/docker/             Runtime and training images
deploy/codebuild/          Private VPC platform bootstrap build and client-tool locks
deploy/local/              PostgreSQL roles/schemas and reverse proxy
deploy/observability/      Grafana dashboard source
deploy/kubernetes/         Separate YAML bases, dev/test/UAT/production overlays and Argo CD applications
scripts/                   Pipeline automation, release rendering, AWS bootstrap and local setup
tests/                     Delivery and dataset safeguards
.github/workflows/         CI, backend, Terraform, release, EKS bootstrap, training and frontend publication
docs/                      AWS deployment, operations and validation notes
```

## AWS deployment

Follow [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md). The source is prepared;
**no AWS resources or remote GitHub workflows have been run from this build**.
The pipeline guide includes this account's Sydney Region, repository and DNS
settings. Configure the six main-only GitHub environments, run the one-time
trust helper, and copy its generated GitHub settings. Use GitHub OIDC.

The EKS/RDS/cache/NAT/ALB stack has recurring charges. Use your credits for
bounded deployment sessions, review the Terraform plan and configure a budget before
applying. RDS deletion protection and retained S3 data are intentional.

## Development and checks

Java 21 and Maven are required outside Docker. Python services use Python 3.12.

```bash
mvn -B -ntp verify
cd apps/web
npm ci
npm run build
cd ../..
python3 -m venv .venv
source .venv/bin/activate
pip install -r services/vision/requirements-dev.txt -r scripts/requirements.txt fakeredis scikit-learn
python scripts/install_kustomize.py --directory "$PWD/deploy/generated/tools"
export PATH="$PWD/deploy/generated/tools:$PATH"
python scripts/download_model.py
PYTHONPATH=services/vision pytest services/vision/tests tests -q
```

An optional no-Docker developer stack uses **H2 and SQLite**, with Redis
fallback if it is unavailable. It is for development, not the AWS data layer:

```bash
python scripts/dev.py --seed
```

Use `python scripts/dev.py --smoke-only` to start isolated temporary databases,
exercise the real HTTP services and shut them down. The recommended Compose
setup and CI integration job use PostgreSQL + pgvector + Redis.

See [docs/VALIDATION.md](docs/VALIDATION.md) for what was actually verified,
including environment limitations. Physical camera detection, account-specific
AWS deployment, model quality on real stock and recovery targets require their
own acceptance tests before live business use.

## Put it in your GitHub repository

The existing repository is
[`bawantha395/workshop-stock-management--system-mlops`](https://github.com/bawantha395/workshop-stock-management--system-mlops).
Follow the fresh-upload procedure in [START_HERE.md](START_HERE.md) to replace
the source on a review branch while preserving repository history. The ZIP
extracts to `workshop-stock-ai/`; that folder name does not change the GitHub
repository name.

Ignore rules exclude local credentials, account-specific Terraform variable
files, model weights, runtime data, build outputs and Terraform state. Do not
copy real workshop photos or customer records into Git.

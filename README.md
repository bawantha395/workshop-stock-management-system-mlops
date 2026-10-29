# Stocklane — workshop stock management on AWS

A stock-management system for a vehicle workshop: mechanics receive and take out
stock by scanning a QR label or taking a photo, owners see stock analysis and a
usage forecast. It runs as microservices on **Amazon EKS**, is built entirely
with **Terraform + GitHub Actions + Argo CD**, and has **dev, staging and prod**
environments that can each be created and destroyed with one pipeline run.

## Architecture

```mermaid
flowchart LR
  U[Phone / browser] --> CF[CloudFront<br/>React app in S3]
  U --> ALB[ALB + ACM<br/>api.stocklane.*]
  subgraph VPC [VPC: public + private subnets, NAT]
    ALB --> EKS
    subgraph EKS [EKS cluster]
      INV[inventory<br/>Spring Boot]
      WS[workshop<br/>Spring Boot]
      VIS[vision<br/>FastAPI + MobileNetV2]
      FC[forecast<br/>FastAPI]
      MON[Prometheus / Grafana]
      ARGO[Argo CD]
    end
    EKS --> RDS[(RDS PostgreSQL)]
    EKS --> REDIS[(ElastiCache Redis)]
  end
  EKS --> S3[(S3 photos, models)]
  EKS --> SQS[SQS + DLQ]
  VIS --> BR[Bedrock Nova Lite]
  SM[SageMaker jobs] --> REG[Model Registry]
  U -. sign in .-> COG[Cognito + MFA]
```

- **Security:** private worker subnets, Pod Identity role per service account
  with a permissions boundary, Secrets Manager via External Secrets, KMS, network
  policies, non-root containers, Cognito with MFA.
- **Observability:** Prometheus, Alertmanager → SNS, Grafana dashboards,
  CloudWatch logs and alarms, a budget, and a Lambda that writes a root-cause
  summary when an alarm fires.
- **AI/MLOps:** photo matching, stock forecasting and Bedrock label reading,
  with SageMaker jobs, quality gates and a reviewed Model Registry
  ([docs/MLOPS.md](docs/MLOPS.md)).

## Repository layout

```text
apps/web/                 React frontend
services/                 inventory, workshop (Spring Boot) · vision, forecast (FastAPI)
mlops/                    SageMaker jobs, evaluation, promotion
edge/                     optional fixed-camera capture agent
infra/
  ci/                     foundation: CI roles + state bucket (CloudFormation, once)
  terraform/modules/      network, data, registry, eks, workload-identity, edge,
                          auth, ml, observability, cicd
  terraform/environments/ dev · staging · prod (same main.tf, different tfvars)
deploy/
  kubernetes/             Kustomize bases + dev/staging/prod overlays, Argo CD apps,
                          monitoring, vendored pinned upstream YAML
  docker/                 service and training images
  codebuild/              private in-VPC runner for the cluster bootstrap
scripts/                  pipeline steps (Python), local dev helpers
tests/                    pipeline, Terraform, Kustomize and ML safeguards
.github/workflows/        deploy, destroy, ci + reusable stages (_*.yml) + ML jobs
```

The same three names — `dev`, `staging`, `prod` — are used for the Terraform
environment, the Kustomize overlay, the Kubernetes namespace (`stocklane-<env>`)
and the pipeline input.

| | dev | staging | prod |
| --- | --- | --- | --- |
| AZs / NAT | 2 / 1 shared | 2 / 1 shared | 3 / one per AZ |
| Nodes | 2 × m7i-flex.large | 2–3 × m7i-flex.large | 3–6 × m6i.large |
| Database | db.t4g.micro | db.t4g.small | db.t4g.small Multi-AZ |
| App replicas | 1 | 2 | 3 (HPA to 6) |
| `deletion_protection` | false | false | true |

## Pipelines

```mermaid
flowchart LR
  subgraph deploy.yml [Deploy environment]
    direction LR
    t[test] --> p[plan] --> a[apply] --> r[release] --> k[platform] --> f[frontend] --> m[train?]
  end
  subgraph destroy.yml [Destroy environment]
    direction LR
    c[confirm] --> td[k8s teardown] --> s[sweep] --> dp[destroy plan] --> d[destroy] --> ch[check]
  end
```

**One master pipeline creates everything; one destroys it.** Each stage is a
reusable workflow (`_terraform`, `_release`, `_platform`, `_frontend`,
`_cleanup`) so the master pipelines are just the order of stages.

| Stage | What happens |
| --- | --- |
| test | `ci.yml`: Java, frontend, Python tests; `terraform validate` + mocked plan for all three environments; Kustomize build and schema checks; actionlint; Trivy |
| plan | Terraform plan for `infra/terraform/environments/<env>`, saved privately to S3 with an ID and SHA256 |
| apply | applies **exactly** that saved plan (the hash is checked) |
| release | builds images to ECR by digest, renders the env's Kustomize overlay, commits it to `main` (GitOps) |
| platform | private CodeBuild runner inside the VPC installs Argo CD and controllers; Argo CD syncs the release commit; HTTPS probe |
| frontend | publishes the React build to S3 and invalidates CloudFront |
| train | optional SageMaker jobs that register pending model versions |

Destroy first removes what Kubernetes created in AWS (load balancers, volumes,
DNS records), then runs a reviewed `terraform destroy`, then **checks that
nothing billable is left**. Only the state bucket, CI roles and hosted zone stay.

Setup and usage: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## Spring Boot service structure

There are two Spring Boot microservices, `services/inventory` and
`services/workshop`. Each one is **self-contained** (its own `pom.xml`, security,
exception handling, migrations, Docker image and database schema) and has the
same layered layout:

```text
services/<service>/src/main
├── java/com/stocklane/<service>/
│   ├── <Service>Application     Spring Boot entry point
│   ├── controller/              REST endpoints and role checks (@PreAuthorize)
│   ├── service/                 business rules, transactions, calls to other services and AWS
│   ├── repository/              all SQL (JdbcTemplate), one class per table group
│   ├── dto/                     request bodies (Java records)
│   ├── config/                  SecurityConfig: Cognito JWT, service tokens, CORS
│   └── exception/               ConflictException (409), NotFoundException (404), GlobalExceptionHandler
└── resources/                   application.yml, db/migration (Flyway SQL)
```

Requests go `controller → service → repository → PostgreSQL`. The two services
call each other only over HTTP and an SQS-backed outbox (inventory events update
workshop job allocations). Routing between services is done by the ALB ingress,
so there is no separate API-gateway service.

`service/Commands` (idempotent requests: the same `Idempotency-Key` returns the
same result) and the `config` and `exception` classes are copied into both
services so that each can be built and deployed on its own. A test
(`tests/test_backend_structure.py`) keeps the copies identical and keeps SQL out
of controllers and services.

## Design decisions worth explaining

- **Modules + per-environment roots instead of workspaces.** Each environment has
  its own state file and its own small `terraform.tfvars`; the code is identical
  (a test enforces it), so differences between dev and prod are visible in one file.
- **Saved plans.** What gets applied is the plan that was reviewed, not a fresh
  one that could differ.
- **Private runner for the cluster.** The EKS API is restricted to the operator's
  IP, so cluster bootstrap runs on CodeBuild inside the VPC.
- **GitOps.** The pipeline never runs `kubectl apply` for apps; it commits the
  rendered overlay and Argo CD makes the cluster match Git.
- **Vendored YAML instead of Helm** for third-party components: every file is
  SHA-pinned, so a deploy can only apply reviewed bytes
  ([docs/KUSTOMIZE.md](docs/KUSTOMIZE.md)).
- **One switch for disposability.** `deletion_protection=false` turns off DB
  snapshots, bucket retention and secret recovery windows so dev/staging destroy
  cleanly; prod keeps all of them.

## Run it locally

```bash
python3 scripts/configure_local.py
docker compose --profile tools run --rm model-init
docker compose up --build -d          # http://localhost:4173
```

Tests and tool setup: [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md).

## More docs

| Doc | Topic |
| --- | --- |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | One-time setup, deploy, destroy, troubleshooting |
| [infra/README.md](infra/README.md) | Terraform modules and environments |
| [docs/KUSTOMIZE.md](docs/KUSTOMIZE.md) | Kubernetes layout, overlays, Argo CD |
| [docs/MLOPS.md](docs/MLOPS.md) | SageMaker, Model Registry, Bedrock |
| [docs/REAL_DATA.md](docs/REAL_DATA.md) | Training on real public data (UCI sales, Kaggle car-part photos) |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Stock rules, alerts, recovery drills |
| [docs/WAREHOUSE_UX.md](docs/WAREHOUSE_UX.md), [docs/STOCK_ANALYSIS.md](docs/STOCK_ANALYSIS.md), [docs/DEMAND_FORECASTING.md](docs/DEMAND_FORECASTING.md) | Application features |

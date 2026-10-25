# Repository structure

The repository is a monorepo: each runtime service has its own source and
tests, while infrastructure and delivery configuration stay outside the
application directories. Paths below are relative to `workshop-stock-ai/`.

## Application and model code

| Folder | Responsibility |
| --- | --- |
| `apps/web/` | React/TypeScript web app, Vite configuration, styles and npm lock file. |
| `services/inventory/` | Spring Boot catalogue, stock ledger, receipts/issues/returns, Flyway migrations and service tests. |
| `services/workshop/` | Spring Boot repair jobs, stock-event handling, invoice reconciliation, PDFs and service tests. |
| `services/vision/` | FastAPI photo matching, embeddings, approved references, drafts, capture inbox and service tests. |
| `packages/platform-java/` | Shared Java security, API errors and command handling. |
| `edge/` | Optional fixed-camera capture agent and Python requirements. |
| `mlops/` | SageMaker training entrypoint, same-SKU calibrator, evaluation, serving contract and promotion. |
| `mlops/data/` | Dataset-manifest example. Actual workshop training data belongs in private storage. |
| `models/` | Instructions for preparing versioned model bundles. Generated weights are ignored. |
| `tests/` | Cross-service delivery, dataset and Kustomize safeguards. |

Java modules retain Maven's `src/main/java`, `src/main/resources` and
`src/test/java` conventions. Vision keeps application code in `app/` and tests
in `tests/`. Each service has its own dependency manifest.

## Infrastructure and delivery

| Folder | Responsibility |
| --- | --- |
| `infra/ci/` | One-time GitHub trust, pipeline-owned S3 backend and capacity profiles. |
| `deploy/codebuild/` | Private VPC platform bootstrap buildspec and tool checksums. |
| `infra/bootstrap/` | Optional manual backend bootstrap; pipelines use `infra/ci/state.json`. |
| `infra/aws/` | AWS root configuration, resource files, example variables and IAM policies. See [infra/README.md](../infra/README.md). |
| `deploy/docker/` | Java, vision, web, operations and training Dockerfiles. |
| `deploy/kubernetes/apps/` | Application bases and environment-specific Kustomize overlays. |
| `deploy/kubernetes/platform/` | EKS controllers, secret-store integration, encrypted EBS StorageClass and Fluent Bit. |
| `deploy/kubernetes/argocd/` | Argo CD installation, projects, child Applications and environment root Applications. |
| `deploy/kubernetes/monitoring-operator/` | Prometheus Operator installation and CRDs. |
| `deploy/kubernetes/monitoring/` | Prometheus, Alertmanager, Grafana, dashboards, metrics scraping and alerts. |
| `deploy/kubernetes/bootstrap/` | Database bootstrap Job, service account and per-environment configuration. |
| `deploy/kubernetes/vendor/` | Pinned upstream manifests, one resource per YAML, with upstream licenses. |
| `deploy/observability/` | Dashboard source used by dashboard-generation tooling. |
| `deploy/certs/` | Public AWS RDS certificate-authority bundle; no private keys. |
| `deploy/local/` | Optional local PostgreSQL setup and nginx routing. |
| `.github/workflows/` | CI, backend, reviewed Terraform plan/apply, release PR, private platform bootstrap, training and frontend publication. |
| `scripts/` | Configuration, model preparation, release rendering, validation and bootstrap tools. |

## Kubernetes resource layout

Each application service under `deploy/kubernetes/apps/base/` has separate
`deployment.yaml`, `service.yaml`, `serviceaccount.yaml`, `external-secret.yaml`,
`hpa.yaml`, `pdb.yaml`, `servicemonitor.yaml` and `kustomization.yaml` files.
Shared configuration, ingress and network policies live in `base/shared/`.

The deployment groups have `overlays/dev`, `overlays/test`, `overlays/uat` and
`overlays/production`. Change shared resource behavior in `base/`; keep
environment differences in the selected overlay. The Argo CD root Applications
are in `argocd/root/`.

Grafana has a separate `pvc.yaml`. Prometheus and Alertmanager request storage
through their custom resources. EBS CSI dynamically provisions the actual PVs;
there is no fixed, pre-created EBS volume or handwritten static `pv.yaml`.
Application business data lives in RDS and S3.

AWS Secrets Manager supplies application and Grafana secrets through External
Secrets. The Alertmanager routing Secret contains non-sensitive configuration.
Never commit passwords, AWS keys or actual Kubernetes secret values.

See [KUSTOMIZE.md](KUSTOMIZE.md) for dependency order, storage, secret handling
and validation. Kustomize and kubectl deploy these manifests; Helm is not
required by the deployment workflow.

## Root files and documentation

| Path | Purpose |
| --- | --- |
| `START_HERE.md` | ZIP contents, fresh upload to the existing GitHub repository and first checks. |
| `README.md` | Product behavior, architecture and implemented capabilities. |
| `pom.xml` | Java multi-module build and managed dependency versions. |
| `package.json` | Frontend/build convenience commands. |
| `compose.yml` | Optional local integration stack. |
| `Makefile` | Developer convenience commands. |
| `.gitignore`, `.dockerignore` | Keep credentials, generated data and build outputs out of source/image contexts. |
| `.env.example` | Optional local-development configuration template. |
| `docs/AWS_DEPLOYMENT.md` | AWS configuration and deployment procedure. |
| `docs/PIPELINE_SETUP.md` | Default automated deployment, including one-time GitHub OIDC trust setup. |
| `docs/OPERATIONS.md` | Operational runbooks and recovery considerations. |
| `docs/VALIDATION.md` | Completed verification and remaining acceptance work. |
| `docs/LOCAL_DEVELOPMENT.md` | Optional developer environment. |

No account-specific `.tfvars`, Terraform state, generated deployment output,
customer records, real workshop photos, dependency directories or Git metadata
are part of the ZIP. The complete source includes `.github/` and `.gitignore`.

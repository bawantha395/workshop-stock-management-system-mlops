# Start here

**New stock forecasting:** [Deploy and run the separate Forecast microservice](docs/DEMAND_FORECASTING.md).

**Current release scope and checks:** [FINAL_RELEASE_CHECKS.md](docs/FINAL_RELEASE_CHECKS.md).

**Owner reporting:** [Stock analysis and forecasting data](docs/STOCK_ANALYSIS.md).

**Final domain setup:** [Stocklane, Argo CD and Grafana HTTPS](docs/CUSTOM_DOMAINS.md).

**Latest corrected release:** [Network fix, Bedrock and SageMaker lifecycle](docs/AI_MLOPS_RELEASE.md).

**Latest UI:** see [the warehouse task release guide](docs/WAREHOUSE_UX.md).
Receiving and stock-out now use scan → draft list → review → confirm.

**Existing deployed project:** this update introduces the stock-only phase one.
Read [docs/STOCK_FIRST_PHASE1.md](docs/STOCK_FIRST_PHASE1.md), pass validation,
prepare a new release, merge its GitOps PR and deploy. Existing AWS trust and
credentials do not need to be recreated for this source update.

If you already uploaded the project and hit the IAM OIDC provider denial,
follow [docs/FREE_PLAN_FIX.md](docs/FREE_PLAN_FIX.md) to resume with the
restricted CI user authentication option.

**Use [docs/PIPELINE_SETUP.md](docs/PIPELINE_SETUP.md) to automate AWS deployment.**
It replaces the earlier manual CloudShell deployment sequence. Keep the Free
plan and Sydney. Upload the complete source update first, pass all eight CI
jobs, then complete the one-time GitHub environment and AWS trust setup.

This is the complete Stocklane workshop inventory and AI project. The ZIP
extracts to one `workshop-stock-ai/` folder. It contains the application source,
tests, Dockerfiles, Terraform, GitHub Actions and Kustomize manifests.

## Find your code

| What you want to change | Location |
| --- | --- |
| Web interface | `apps/web/` |
| Product catalogue, stock movements and balances | `services/inventory/` |
| Repair jobs, customer invoices and PDFs | `services/workshop/` |
| Photo matching, new-item suggestions and approval | `services/vision/` |
| Optional fixed-camera capture | `edge/` |
| SageMaker training, evaluation and model promotion | `mlops/` |
| AWS resources | `infra/aws/` |
| EKS application manifests | `deploy/kubernetes/apps/` |
| Argo CD | `deploy/kubernetes/argocd/` |
| Prometheus, Alertmanager and Grafana | `deploy/kubernetes/monitoring/` |
| All folders and their responsibilities | [docs/REPOSITORY_STRUCTURE.md](docs/REPOSITORY_STRUCTURE.md) |

The application supports manual photo capture/upload as well as the optional
camera agent. Product categories are editable; it is not limited to engine oil.
Current stock units are whole items (`UNIT`) and litres (`LITRE`). A person
confirms item identity, quantities and stock movements.

## Upload the complete source to your existing GitHub repository

Keep your existing repository and its history. The following procedure creates
a separate clean clone and a review branch, replaces its tracked source, and
pushes the update. It does not change your existing working folder.

1. Extract the ZIP in Downloads. Confirm this file is at
   `~/Downloads/workshop-stock-ai/START_HERE.md`.
2. In Terminal, run the commands below. Choose an unused directory if
   `~/workshop-stock-ai-upload` already exists.

```bash
cd ~
git clone https://github.com/bawantha395/workshop-stock-management-system-mlops.git workshop-stock-ai-upload
cd workshop-stock-ai-upload
git switch -c update/aws-pipeline
git rm -r -- .
rsync -av "$HOME/Downloads/workshop-stock-ai/" ./
git add -A
git status --short
git commit -m "Support Free-plan pipeline authentication with scoped role sessions"
git push -u origin update/aws-pipeline
```

`git rm` above is only for the new clean clone and review branch. It removes
the previous tracked files before copying this complete source, so obsolete
deployment files do not remain. The clone's Git metadata and remote are kept.
`rsync` also copies `.github/`, `.gitignore` and the example configuration.

3. Open the repository in GitHub. Create a pull request from
   `update/aws-pipeline` into `main`.
4. Wait for **Validate platform** to finish. It has eight jobs: Java, frontend,
   vision/manifests, Compose integration, Kustomize, infrastructure, automation and security.
   Fix any failing check before merging.

The validation workflow does not require AWS credentials. AWS workflows skip
until you complete the one-time account setup. GitHub may ask
you to sign in when pushing; do not add account passwords or AWS keys to files.

## After validation

Follow [docs/PIPELINE_SETUP.md](docs/PIPELINE_SETUP.md). Complete these one-time
steps, then run deployments from GitHub Actions:

1. Create the six GitHub environments with a main-only branch rule.
2. Use CloudShell once to prepare, review and execute the pipeline trust stack
   with `--auth-mode access-key`, as the guide describes.
3. Copy the generated repository variables, `TFVARS_JSON`, and restricted CI
   user's access-key pair into GitHub Actions secrets.
4. Run **Bootstrap Terraform backend**, then **Plan AWS infrastructure**.
5. Review the plan and run **Apply reviewed Terraform plan** with its ID and SHA256.
6. Review and merge the generated release PR. Successful CI then starts the
   private platform bootstrap and frontend publication.

The known project details are:

| Setting | Value |
| --- | --- |
| AWS account | `721274598579` |
| AWS Region | `ap-southeast-2` (Sydney) |
| GitHub repository | `bawantha395/workshop-stock-management-system-mlops` |
| Owned domain | `bawantha-rathnayake.tech` |
| Intended API hostname | `api.stocklane.bawantha-rathnayake.tech` |
| Route 53 hosted zone | `Z035879924YQHJ4M5G2A3` |

The helper resolves the operator IAM role and current CloudShell IP, and asks
for your budget-alert email locally. This account's Free-plan SCP blocks IAM
OIDC providers. Its CI user can only assume the project delivery roles; its key
is kept in Actions secrets. Keep the Free plan. The smaller demo capacity
still consumes credits, so review the plan and cost before applying it.

## Deployment status and limits

- Source validation is recorded in [docs/VALIDATION.md](docs/VALIDATION.md).
  This ZIP has not been deployed into your AWS account.
- Kubernetes has separate `dev`, `test`, `uat` and `production` overlays.
  These do not automatically create four AWS environments.
- Terraform currently uses `infra/bootstrap` and one `infra/aws` root. The AWS
  root is split into resource files, but reusable child modules and a full
  multi-account promotion pipeline are not implemented.
- Checked-in deployment overlays contain explicit placeholders. The release
  renderer fills reviewed account values and immutable application image
  digests; configured validation rejects unresolved placeholders.
- Secrets, Terraform state, dependencies, build outputs and generated model
  weights are excluded. Example configuration and lock files are included.
- Physical camera acceptance, real-stock model evaluation and live AWS
  recovery/deployment checks remain required before business use.

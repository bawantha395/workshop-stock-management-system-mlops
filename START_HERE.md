# Start Here — Complete Stocklane Project

This ZIP contains the complete `workshop-stock-management-system-mlops/` project: frontend, Java/Python services, AWS Terraform, GitHub Actions, Dockerfiles, Kustomize, Argo CD, Prometheus/Grafana, model-training scripts, tests, documentation and the real public-data subset.

It is a source snapshot based on repository commit `46ca6c78d56d052470af379874c7f1c21cc08f32` plus the runtime corrections and real-data training extension prepared in this conversation. It is not a fresh download of any later GitHub commits. Review differences before merging into your existing repository.

## Your AWS Deployment Already Exists

Keep your existing GitHub repository, AWS resources, Terraform state, repository variables and secrets. This source update does not require creating them again. Source files and workflow configuration are included; live credentials and Git history are not.

Unzip this package outside your existing checkout. Copy the project contents into a review branch in your existing repository, including `.github/` and `.gitignore`, and review the diff before committing. Do not delete your repository's `.git` directory. Keep any newer changes you made on GitHub when resolving differences.

Then use this order:

1. Push the reviewed source changes and let **Validate platform** pass.
2. Run **Prepare AWS release** on `main` and merge its validated GitOps release PR. This builds and publishes the updated application and `ml-training` containers and renders current deployment settings. Do not bootstrap directly from old image references in a source snapshot.
3. Complete **Bootstrap EKS platform** for the new release.
4. Run **Train real-data ML models** on `main`, choosing `both`.
5. In the workflow Summary, find the actual returned SageMaker Training job ARNs and evaluation results. In AWS, select **Sydney / ap-southeast-2 → SageMaker AI → Training → Training jobs**.

No manual SageMaker notebook, Studio domain or persistent endpoint is needed by this training workflow. It reuses your existing training roles and downloads the pinned public inputs automatically. AWS training and storage charges are subject to your plan, credits and regional quotas.

## What Is Included

| Folder | Purpose |
| --- | --- |
| `apps/web/` | Stock frontend, phone QR scanner and reporting pages. |
| `services/inventory/` | Product catalogue, stock ledger, movements and event outbox. |
| `services/vision/` | Photo matching, camera captures and optional Bedrock drafts. |
| `services/forecast/` | Separate stock forecasting API. |
| `services/workshop/` | Existing compatibility service; stock tasks do not require labour, customers or invoices. |
| `packages/platform-java/` | Shared authentication, metrics security and API support. |
| `edge/` | Optional connected-camera agent. |
| `mlops/` | Data validation, training, evaluation, Registry review and promotion. |
| `datasets/public-benchmark/` | 115 real source images, 23 product identities, 64 monthly parts-sales histories, licences, checksums and local evaluation. |
| `infra/` | AWS infrastructure and CI identity/state templates. |
| `deploy/` | Dockerfiles, EKS/Kustomize/Argo CD manifests and observability. |
| `.github/workflows/` | Validation, infrastructure delivery, releases and training. |
| `scripts/` | Pipeline and operational automation. |
| `tests/` | Integration, deployment and ML-data safeguards. |
| `docs/` | Architecture, deployment, operations and model guides. |

## Read These First

- [Real-data training, sources and measured results](docs/REAL_DATA_TRAINING.md)
- [Runtime readiness and existing fixes](docs/FEATURE_READINESS_AND_DEMO.md)
- [Prometheus/Grafana correction](docs/MONITORING_AUTH_FIX.md)
- [Folder responsibilities](docs/REPOSITORY_STRUCTURE.md)
- [Existing pipeline setup reference](docs/PIPELINE_SETUP.md)

The included public images and 1998–2002 monthly history are external benchmark data, not your brother's workshop records. They are not automatically added to the live product catalogue or stock ledger. Monthly observations are not converted into invented daily usage.

Both public model candidates failed their pooled quality gates in local evaluation. Benchmark packages remain pending and cannot replace live workshop models. No AWS training was started while preparing this ZIP; an actual successful workflow run is needed for that claim. Live serving remains on EKS, so an empty SageMaker Endpoints page is expected.

Local verification of the included implementation: 239 Python tests passed; five PostgreSQL integration tests needed a live test database and were skipped. The Java runtime corrections previously passed 39 tests. See [PACKAGE_VERIFICATION.json](docs/PACKAGE_VERIFICATION.json) for the recorded scope.

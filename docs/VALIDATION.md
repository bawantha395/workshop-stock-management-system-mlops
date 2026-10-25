# Validation record

Checked on 25 October 2026. This is the verification record for the supplied
source, not evidence that resources are running in AWS or that a production SLO
has been achieved.

## Completed in the build environment

| Check | Result | Scope |
| --- | --- | --- |
| Java 21 / Maven build and tests | Passed, 14 tests | Inventory transactions, idempotency conflicts, concurrent issues, returns, job freezing, internal capabilities, event deduplication and multi-page invoice PDFs. |
| Python tests | Passed, 28 tests | Real CPU encoder, reviewed image references, capture retry/conflict rules, versioned cache behavior, Cognito claim/scope validation, cloud authentication guards, release manifests and dataset safeguards. |
| Real HTTP workflow | Passed | Three running backend services; opening 50 + receipt 10 - issue 2 + return 1 = 59. Invoice reconciles one net bottle and labour to LKR 6,500. PDF produced; later issues rejected for the frozen job. |
| Camera API workflow | Passed | IN/OUT pending captures, source metadata verification, unique movement linkage and job linkage. No physical camera was connected. |
| React / TypeScript production build | Passed | Type checking and Vite asset generation. Fonts bundled with the application. |
| Browser interaction | Passed | Open inventory, create a receipt, confirm stock increases from 2 to 5 and check the stock activity entry. |
| npm production dependency audit | Passed | No reported vulnerabilities in the audit performed during the build. This is time-specific and does not cover every container or language dependency. |
| Terraform formatting / HCL parsing | Passed | All source files format and parse. This does not verify AWS provider schemas or account permissions. |
| YAML / release guards | Passed | Workflow YAML parsed, third-party Actions use full commit pins, generated workload images require digests, cloud identity cannot use the local demo header, private capabilities are restricted by service. |
| Python helper compilation | Passed | Deployment, camera and training helpers compile. |

The HTTP check used isolated H2 and SQLite databases. It exercised actual API
and model code, but it does not replace PostgreSQL/pgvector, Redis, Cognito or
SQS integration testing. The supplied GitHub CI has a separate Compose job for
real PostgreSQL/pgvector and Redis; Docker was unavailable here, so that job has
not been executed in this environment.

## Deployment gates still open

**Terraform provider validation is blocked here.** A fresh initialization now
succeeds with signed AWS 6.70.0 and random 3.9.1 providers, resolving the earlier
cache/checksum issue. The local runtime then prevents both providers from
opening their Unix sockets (`socket: operation not permitted`). Terraform
formatting and HCL parsing pass; provider schema validation still must pass
the supplied GitHub CI infrastructure job before account-specific deployment.

There is no authenticated AWS or GitHub account connection in this build.
Consequently, no Terraform plan/apply, ECR push, EKS rollout, live AWS smoke test,
SageMaker training job or remote GitHub workflow has run. Account service quotas,
regional model access, controller compatibility and the generated IAM
permissions require validation during the real deployment.

CloudWatch/SNS, replicated Prometheus/Alertmanager and required Cognito MFA are
implemented as source configuration. Confirm the owner's SNS email subscription
and exercise a firing/recovery notification after deployment. No notification
has been sent from this build.

No reviewed workshop dataset was supplied. The included encoder is pretrained
on ImageNet; the training code learns a same-SKU pair calibrator from real,
reviewed workshop photos. Neither workshop recognition accuracy nor a trained
calibrator is claimed. Always confirm exact grade, capacity, quantity and job.

Before the workshop depends on the system, perform an HTTPS/Cognito end-to-end
stock and invoice acceptance test, a representative load test and a restore into
a separate environment. Measure recovery time and data loss before committing
to an RTO/RPO. Test the optional camera under the actual tray lighting. Configure
business invoice/tax requirements and the documented invoice character-set
limitations before using its PDFs as official customer bills.

See [AWS deployment](AWS_DEPLOYMENT.md) for account setup and
[operations](OPERATIONS.md) for recovery procedures and current product limits.

## Separate-YAML Kustomize update

The application and platform now use separate YAML resource files and four
Kustomize environment overlays. Local Kustomize builds and custom-resource
schema checks passed for all four profiles. Thirteen additional Kustomize tests
passed. The PostgreSQL JDBC override to 42.7.14 passed the configured Trivy
HIGH/CRITICAL vulnerability and secret gate. Live AWS deployment is still
pending. See KUSTOMIZE.md for the layout and acceptance boundaries.

The user-provided GitHub run 40183341915 showed the original infrastructure and
PostgreSQL/Redis integration jobs passing. Its security job identified the
PostgreSQL JDBC CVE subsequently patched here. That evidence predates this
Kustomize refactor; the updated revision must pass the new CI jobs after commit.

Kubeconform also validated the Kubernetes 1.35 built-in resource schemas.
Custom kinds skipped by kubeconform are checked against the vendored CRD
schemas by validate_kustomize.py. No server-side AWS/EKS acceptance test has run.

## GitHub Actions automation update

| Check | Result | Scope |
| --- | --- | --- |
| Targeted Python tests | Passed, 54 tests; two training tests deselected | Region/account/repository guards, conditional state initialization, deleted-state recovery, version/checksum/age checks for saved plans, protected GitHub environments, private source archives, workload IAM boundaries, delivery filters, model retention/promotion, Kustomize and release guards. |
| GitHub workflow lint | Passed | All workflows checked with checksum-pinned actionlint 1.7.7. |
| CloudFormation lint | Passed | IAM/OIDC trust/boundary and private state-backend templates checked with cfn-lint 1.58.0. Policy-size checks also pass. |
| Terraform format and HCL parse | Passed | All 11 Terraform source files; provider initialization succeeds with signed locked providers. Full provider validation is blocked by the local socket restriction described above. |
| Python compilation | Passed | Scripts, MLOps and edge helpers. |
| Trivy vulnerability/secret gate | Passed | Trivy 0.70.0 with a fresh database dated 25 October 2026; zero fixable HIGH/CRITICAL findings and zero HIGH/CRITICAL secrets across nine dependency targets. This is the CI gate's scope, not a claim that every dependency has a resolved version or all container images are clean. |
| Updated setup-guide links | Passed | Main setup/readme/repository guide links resolve locally. |

The new tests used real Terraform CLI expression evaluation and real Kustomize
builds, plus stubbed AWS clients. The two deselected tests require the separate
training dependencies and remain in the full CI/release suite. Existing Java,
frontend and training application tests were not rerun for this automation-only
update. Online kubeconform checks were not repeated; the earlier result above
predates this update.

An old local Trivy database crashed during the first scan; a fresh database
download and complete rerun passed. No scan failure was ignored. No pipeline
dispatch, CloudFormation execution, Terraform plan/apply or AWS deployment was
performed from this build. All eight GitHub CI jobs must pass on the uploaded
revision before the first deployment. Follow [PIPELINE_SETUP.md](PIPELINE_SETUP.md).

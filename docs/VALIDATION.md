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

## Free-plan pipeline authentication correction

The uploaded main revision `b1fe3f8` passed all eight GitHub CI jobs in run
`40215273192`, including full Terraform provider validation. During the user's
first bootstrap, the account then explicitly denied
`iam:ListOpenIDConnectProviders` through SCP `p-iao1sqv6`. This is consistent
with AWS's [published Free-plan policy](https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html),
whose `DenyIAMRestrictedActions` includes `iam:*Provider*`. The OIDC-only
account setup supplied earlier cannot complete under that restriction.

The update adds explicit `access-key` authentication mode. The bootstrap creates
a CI IAM user permitted only to assume six exact project roles. The user's key
is generated after stack completion and written to an ignored `0600` handoff
file; it never enters CloudFormation outputs or Terraform state. GitHub Actions
assumes the delivery roles and explicitly skips OIDC and session tagging.
Terraform creates no OIDC provider in this mode. Account plan and organization
policies are not changed.

Checks for this correction:

- **60 targeted tests passed**, with two training tests deselected. New cases
  verify zero provider API calls in key mode, actionable OIDC denial, protected
  key handoff, refusal of duplicate keys, key revocation after failed handoff,
  account-bound Terraform inputs and role assumption in all seven AWS workflows.
- **actionlint 1.7.7 with ShellCheck 0.11.0 passed**. The CI requirements now
  pin ShellCheck explicitly, avoiding a weaker local lint check when it is absent.
- **cfn-lint 1.58.0 passed** for both templates. Policy-size and compact inline
  CloudFormation-template size checks passed.
- Terraform formatting, all 11 HCL source parses and Python compilation passed.
- Trivy's configured vulnerability/secret gate passed again with zero fixable
  HIGH/CRITICAL vulnerabilities and zero HIGH/CRITICAL secrets.

The new revision still needs all eight CI jobs to pass after upload. Its live
IAM user/key creation, role assumption and infrastructure deployment have not
been executed here. An additional account policy can still deny an otherwise
supported API; use its explicit error instead of bypassing organization controls.

## First-apply corrections, 26 October 2026

The user supplied output from apply run `40221578717`: ElastiCache completed,
while EKS node-group creation, RDS backup retention, budget tagging and the SNS
topic policy failed. This is evidence of a partially completed deployment, not a
successful platform rollout. The earlier statements about no AWS execution
refer to this build environment; the user is now deploying through GitHub.

The correction grants `iam:GetRole` for the exact EKS node-group service-linked
role and budget tag access for the single project budget. It uses explicit SNS
topic-policy actions and defaults non-production RDS automated backups to one
day. Existing GitHub inputs without a retention override continue to work.
Production keeps its 14-day default; an explicit retention override is checked
as a whole number from 1 to 35.

- **74 targeted tests passed**, with two unchanged training tests deselected.
  New cases evaluate the actual retention and SNS policy expressions with
  Terraform CLI, check role/budget resource boundaries, reject disabled or
  invalid backup retention, and verify that rerunning the trust-stack update
  without the key-creation flag does not generate another key.
- **CloudFormation lint, IAM policy-size checks, Terraform formatting, parsing
  of all 11 HCL files and `git diff --check` passed.**
- Full provider validation, the security gate and all eight CI jobs must pass
  on the new uploaded commit. No dependency versions or application code were
  changed for this correction. Local provider validation remains subject to
  the socket restriction recorded above.

AWS has not accepted this corrected configuration in the user's account yet.
Keep the existing remote state and generate a fresh plan after the operator
updates the trust-stack policies. Follow [FIRST_APPLY_FIX.md](FIRST_APPLY_FIX.md).

### Cognito plan refresh follow-up

The supplied full log for plan run `40224267297` shows signed provider
initialization and successful Terraform validation. Its only AWS errors are
two `cognito-idp:GetGroup` denials while refreshing the existing `OWNER` and
`MECHANIC` groups. Both come from `stocklane-dev-ci-plan`; no SCP denial is
reported. The log confirms that the pending RDS instance now requests one-day
automated backups. Its displayed 13-create/0-change/0-delete summary is not a
successful saved plan.

The template now grants the plan role `GetGroup` for user pools in its own
account and Region. A regression case covers the Cognito refresh APIs used by
the configured resources and rejects group mutations, user administration,
cross-account group reads and cross-Region group reads. Updating the source
template alone does not update the deployed IAM role: the operator must rerun
the existing trust-stack update before requesting a new plan.

For this follow-up, **75 targeted tests passed**, with the same two training
tests deselected. CloudFormation lint, policy-size checks and `git diff --check`
also passed. The supplied log verifies provider validation of the prior
uploaded Terraform configuration; this follow-up changes the IAM template,
tests and recovery documentation only. The new deployed policy and a successful
new plan have not been verified in AWS from this build environment.

## Minimum demo RDS and EKS prerequisite follow-up

The user's next apply completed the SNS topic policy and monthly budget. EKS
again reported failure validating its node-group service-linked role, and RDS
rejected the selected instance class under the account's Free plan. The EKS
message does not by itself prove that the role is absent or explain why the
earlier exact-ARN permission did not satisfy server-side validation.

The demo profile now uses Single-AZ `db.t3.micro`, 20 GiB `gp2`, no storage
autoscaling and one-day backups. Other demo capacity and the production profile
retain their settings. The operator bootstrap verifies or creates the required
AWS-managed node-group service-linked role. Plan/apply perform a read-only role
check with their actual workflow credentials before Terraform initialization.
The check reports denied reads and missing roles separately, and verifies the
expected account/path. No additional IAM wildcard permission was added.

**86 targeted tests passed**, with two training tests deselected. New cases
cover role reuse/creation, denied/service-error handling, review-only bootstrap
without service-role mutations, account-bound role verification, a preflight
failure stopping initialization, and the micro profile reaching the Terraform
input renderer. CloudFormation lint, policy-size checks, Terraform formatting,
all 11 HCL parses and compilation of the three changed Python helpers passed.

The RDS class is an explicit value in the existing GitHub `TFVARS_JSON` secret;
changing source alone cannot replace it. Follow [FIRST_APPLY_FIX.md](FIRST_APPLY_FIX.md)
to update that one configuration secret and generate a new plan. AWS access
keys remain the same. No role creation, IAM access check, micro RDS creation or
successful corrected apply has been executed from this build environment.

### User-selected micro instances

The user subsequently requested `t3.micro` for the node group (replacing the
earlier nano request) and `db.t4g.micro` for RDS. The current demo profile uses
those types, retaining two workers, Single-AZ RDS, 20 GiB `gp2`, disabled storage
autoscaling and one-day backups. The earlier `db.t3.micro` selection above
describes the preceding revision.

**86 targeted tests passed**, with two training tests deselected, after the
updated database class was reflected in the existing profile tests. A real
Kustomize build of the dev application/monitoring overlays confirms 2,144 MiB
of requests for inventory, workshop, vision, Prometheus, Grafana and
Alertmanager alone. This exceeds two `t3.micro` workers' combined 2,048 MiB
raw memory before platform controllers, EKS add-ons and node overhead. The full
rollout cannot fit these requested worker settings. The recovery guide now
recommends an infrastructure-only apply with `prepare_release=false` until
capacity is addressed. No scheduling or readiness success on AWS is claimed.

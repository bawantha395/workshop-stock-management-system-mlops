> Optional operator reference. The default automated path is [PIPELINE_SETUP.md](PIPELINE_SETUP.md).

# Deploy the AWS production profile

This is the manual account handoff for the implemented source. No resources
have been created in your AWS account. Use a dedicated AWS account/region and
review actual charges. Credit eligibility is account-specific; this stack is
not a 24/7 free deployment. The production profile uses three availability zones, three NAT gateways, three CPU
workers, Multi-AZ RDS and a cross-zone cache replica with automatic failover.
Capacity, recovery targets and business acceptance tests still need to be
verified before real workshop traffic.

## 1. Prepare your accounts

You can use AWS CloudShell for operator commands. Install/configure Terraform >=1.10, AWS CLI v2, kubectl compatible with EKS 1.35,
Kustomize and Python 3.12. Container image builds run in GitHub Actions; Docker is
not required on the operator computer. Use your own IAM operator role or temporary AWS
credentials. Confirm the account with `aws sts get-caller-identity`.

Create the empty GitHub repository and push this project. Allow Actions to
create pull requests in repository settings. Create GitHub environments
`aws-release` and `aws-training`, restrict them to the `main` branch and enable
required reviewers where your GitHub plan supports that control. Protect `main`
with reviews and the Validate platform checks.

You need an **owned API hostname and Route 53 hosted zone** for ACM HTTPS,
for example `api.stocklane.yourdomain.com`. A CloudFront hostname is supplied for
the frontend. The AWS API will not be published as an unencrypted demo endpoint.

Before provisioning, require the GitHub infrastructure validation job to pass.
The build-environment provider-checksum blocker is recorded in
[VALIDATION.md](VALIDATION.md); do not bypass checksum verification.

## 2. Create private remote state

Pick a globally unique state bucket name. Bootstrap stores local Terraform
state initially; keep it private and backed up.

```bash
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap plan -var='region=eu-west-1' -var='state_bucket=YOUR_PRIVATE_STATE_BUCKET' -out=bootstrap.tfplan
terraform -chdir=infra/bootstrap apply bootstrap.tfplan
```

Copy `infra/aws/backend.hcl.example` to a local backend file and insert the
bucket/region. S3 native lock files are enabled. Never upload state or binary
plans as public GitHub artifacts; state contains generated secret values.

## 3. Review and provision resources

Copy `infra/aws/terraform.tfvars.example` to `infra/aws/terraform.tfvars` and fill
your repository, existing operator IAM ARN, current public IP/32, owned API
hostname, Route 53 zone and budget email. If an account-wide GitHub OIDC
provider already exists, supply its ARN instead of creating a duplicate.

```bash
terraform -chdir=infra/aws init -backend-config=backend.hcl
terraform -chdir=infra/aws plan -out=production.tfplan
terraform -chdir=infra/aws apply production.tfplan
mkdir -p deploy/generated
terraform -chdir=infra/aws output -json > deploy/generated/aws.outputs.json
```

Plan/apply are operator actions in this first release. GitHub performs static
Terraform validation; it is not given an administrator role for arbitrary
infrastructure changes. The output object contains endpoints, ARNs and public
client IDs, not application passwords.

The management endpoint permits only `operator_cidrs`. GitHub does not need
Kubernetes admin access: it publishes artifacts and GitOps changes; Argo CD
pulls changes from inside the cluster.

## 4. Configure GitHub environments

Use **Variables**, not Secrets, for the following non-secret metadata. Copy the
`deployment.value` object from the output JSON into `DEPLOYMENT_JSON`.

| Environment | Variables |
| --- | --- |
| aws-release | `AWS_REGION`, `AWS_RELEASE_ROLE_ARN` = `github_release_role_arn`, `DEPLOYMENT_JSON` |
| aws-training | `AWS_REGION`, `AWS_TRAINING_ROLE_ARN` = `github_training_role_arn`, `SAGEMAKER_TRAINING_ROLE_ARN` = `training_role_arn`, `MODEL_BUCKET`, `MODEL_PACKAGE_GROUP`, `PROJECT_NAME` |

OIDC role trust is bound to the exact repository and environment. Application
pods receive AWS permissions through EKS Pod Identity. Database passwords and
the private service/cache tokens are fetched from Secrets Manager, not GitHub.

Run **Prepare AWS release** manually on `main`, leaving the model package empty
for the initial pretrained baseline. It prepares immutable image digests,
a checksum-bound model archive, public runtime configuration and a GitOps PR.
Review the generated per-resource patches under `deploy/kubernetes/`.
The `kustomize` CI job must pass. Merge only after validation succeeds. The
baseline remains human-reviewed; it is not a trained workshop classifier.

GitHub's default automation token may not trigger workflows from its own PR
events. The release workflow runs its checks directly; the generated overlay
and reviewed source must still be inspected before merge.

## 5. Bootstrap controllers and service-owned databases

In AWS CloudShell or your authenticated operator session, pull the merged GitOps overlay. Install Python
helpers and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/install_kustomize.py --directory "$PWD/deploy/generated/tools"
export PATH="$PWD/deploy/generated/tools:$PATH"
python scripts/bootstrap_eks.py --config deploy/generated/aws.outputs.json
```

This applies the separate Kustomize YAML for the pinned load-balancer controller, External Secrets Operator,
Argo CD, metrics server, Prometheus Operator, Prometheus/Grafana and Fluent Bit.
No Helm installation is required. The helper waits for CRDs and controllers
before creating their custom resources, then hands reconciliation to Argo CD. It creates the gp3
storage class and private SecretStore. A temporary bootstrap job fetches the
RDS administrator secret in memory and creates separate schema-owning roles.
It never prints passwords. Runtime services never receive the RDS master secret.

The helper writes an isolated kubeconfig under `deploy/generated/`. Use it:

```bash
export KUBECONFIG="$PWD/deploy/generated/kubeconfig"
kubectl get pods -n stocklane
kubectl get externalsecrets -n stocklane
kubectl get ingress api -n stocklane
```

For a private GitHub repository, configure an Argo CD read-only deploy key or
repository credential yourself before syncing. A public portfolio repository
needs no repository credential. Business photos and customer data remain private
in S3/RDS regardless of repository visibility.

Once the ingress reports an ALB address:

```bash
python scripts/configure_api_dns.py --config deploy/generated/aws.outputs.json
```

ACM certificate validation must have completed. The frontend API origin is
`https://API_DOMAIN`; CORS is limited to the Terraform-generated frontend URL.

## 6. Create the owner and mechanic accounts

Use the Cognito console for the created User Pool. Create the owner account and
add it to **OWNER**. Create mechanic accounts and add them to **MECHANIC**.
Public signup is disabled. Staff complete their own initial password setup and
must configure software-token MFA; it is required by this pool policy. The browser uses authorization code + PKCE.

Run **Publish reviewed frontend** after the initial API is healthy. Subsequent
GitOps frontend changes trigger that workflow through the protected environment.
It verifies staged file checksums before copying the reviewed build to S3 and
invalidating the HTML/config entry points. It does not publish an unreviewed
build during preparation.

Open the `frontend_url` and sign in. Register actual stock from a physical count.
Do not load the local sample-data script into a business environment.

## 7. Add Bedrock and the camera

Select a vision-capable model supported in your chosen AWS region. Set its
exact ARN in Terraform `bedrock_model_arn`, review/apply the IAM update and set
the corresponding model ID in the deployment configuration as
`bedrock_model_id`. Prepare/review another release. Do not assume every region
or model accepts images, and do not invent a model ID.

For unattended capture, enrol the dedicated Cognito confidential camera client.
Obtain its client secret securely on the workshop workstation; do not commit it
or place it in a browser. Give the agent only the capture scope. Cognito M2M has
separate pricing from staff sign-ins.

```bash
python3 -m venv .camera-venv
source .camera-venv/bin/activate
pip install -r edge/requirements.txt
# Set CAMERA_CLIENT_SECRET securely in your local environment.
python edge/camera_agent.py --api-url https://YOUR_API_HOST --direction IN --station receiving-tray --token-url YOUR_COGNITO_TOKEN_URL --client-id YOUR_CAMERA_CLIENT_ID
```

Start with an empty tray. Use `--roi X Y WIDTH HEIGHT` to restrict the view and
test thresholds under real lighting. OUT captures can include `--job-id UUID`;
missing links remain for review. One encounter ID survives retries in the local
SQLite spool. Confirm quantity and exact SKU in Review queue before posting.

## 8. Train and promote a real workshop model

Collect multiple real photos per SKU across different capture sessions. Review
labels, especially near-identical sizes/grades. Build a versioned S3 dataset
with `manifest.csv`: `file,sku,session,split`. Use disjoint sessions for train,
validation and test. The example manifest is a schema example, not training data.

Upload the verified encoder files to an S3 `encoder` prefix. Run **Train reviewed
workshop model** with the immutable training-image digest, dataset prefix and
encoder prefix. It uses one CPU `ml.m5.large`, a 10-minute maximum runtime and
network isolation. A failed quality gate must not be overridden by fabricated
metrics. Passing results enter Model Registry as **PendingManualApproval**.

Review metrics and provenance in AWS, then approve the package yourself. Run
Prepare AWS release with that package ARN. The helper verifies approval and
artifact checksums. Argo CD's PreSync job builds the new model's versioned
reference vectors before serving it. Periodic reconciliation catches approved
references created during rollout. Old vectors remain for rollback. Similarity
still requires a human check; no automatic stock policy is enabled.

## 9. Verify operations

Use local port forwards for the private administrative UIs:

```bash
kubectl -n argocd port-forward svc/argocd-server 8443:443
kubectl -n monitoring port-forward svc/grafana 3000:80
```

Retrieve administrator credentials from their Kubernetes Secrets on your own
machine; do not put them into this repository. Inspect API latency/errors,
inference latency, SQS age/DLQs and capture corrections. CloudWatch alarms and Alertmanager route to an encrypted SNS operations topic.
The owner must confirm the SNS email subscription, then trigger a test alert
and verify both firing and recovery notifications before go-live. Prometheus
runs two replicas with seven days of local retention; Alertmanager runs three.
Grafana is a private single-instance administrative UI with persistent storage. CloudWatch AI investigations is a later
AIOps extension, not an implemented automated-remediation agent.

Test RDS and S3 restoration before defining a business RPO/RTO. Reverting the
GitOps image/model/index configuration rolls back application releases; database
migrations require their own compatible recovery plan. Keep old model/index
versions until the rollback window expires.

## 10. Control production costs deliberately

Stopping worker workloads alone does not stop the EKS control-plane, NAT, ALB,
RDS or cache charges. Review the plan before tearing down compute. Preserve
business records, model archives, backups and invoices. Deletion protection,
final RDS snapshots and non-empty/versioned S3 buckets intentionally require an
operator decision. Do not treat a teardown as a stock-data cleanup command.

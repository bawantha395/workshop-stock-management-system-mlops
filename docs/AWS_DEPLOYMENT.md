# AWS deployment through pipelines

The default deployment procedure is **[PIPELINE_SETUP.md](PIPELINE_SETUP.md)**.
It uses the current Free plan and Sydney (ap-southeast-2).

GitHub Actions manages state-backend creation, Terraform plan/apply, release
preparation and orchestration. CodeBuild runs controller bootstrap inside the
private VPC. Argo CD reconciles the separate Kustomize manifests.

The initial AWS operator task is creating scoped pipeline roles and the
restricted CI user through the supplied CloudFormation helper in access-key
mode. This account's Free-plan SCP blocks IAM OIDC providers. GitHub
environment protections, plan review and release review are documented in the
setup guide. The CI user's key belongs in Actions secrets; Terraform state and
private plan files remain in S3. OIDC remains optional for eligible accounts.

[MANUAL_AWS_DEPLOYMENT.md](MANUAL_AWS_DEPLOYMENT.md) preserves the optional
operator reference. Do not combine its separate Terraform state-bucket bootstrap
with the pipeline-owned backend unless you deliberately plan a state migration.

# AWS deployment through pipelines

The default deployment procedure is **[PIPELINE_SETUP.md](PIPELINE_SETUP.md)**.
It uses the current Free plan and Sydney (ap-southeast-2).

GitHub Actions manages state-backend creation, Terraform plan/apply, release
preparation and orchestration. CodeBuild runs controller bootstrap inside the
private VPC. Argo CD reconciles the separate Kustomize manifests.

The only initial AWS operator task is creating the GitHub OIDC trust and
scoped pipeline roles through the supplied CloudFormation helper. GitHub
environment protections, plan review and release review are documented in the
setup guide. AWS credentials and Terraform state are not uploaded to GitHub.

[MANUAL_AWS_DEPLOYMENT.md](MANUAL_AWS_DEPLOYMENT.md) preserves the optional
operator reference. Do not combine its separate Terraform state-bucket bootstrap
with the pipeline-owned backend unless you deliberately plan a state migration.

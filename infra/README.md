# AWS infrastructure

Use [the pipeline setup guide](../docs/PIPELINE_SETUP.md) for deployment. Create
the GitHub OIDC trust once in CloudShell; GitHub Actions then owns backend
creation and reviewed Terraform plan/apply operations in Sydney.

| Path | Responsibility |
| --- | --- |
| `ci/identity.json` | One-time OIDC trust, separate CI roles and workload permissions boundary. |
| `ci/state.json` | Pipeline-owned private, encrypted, versioned Terraform state bucket. |
| `ci/capacity-*.json` | Explicit demo/production capacity selections used by the setup helper. |
| `bootstrap/main.tf` | Optional manual state bootstrap; do not mix with the pipeline-owned backend. |
| `aws/versions.tf` | Terraform/provider constraints and backend declaration. |
| `aws/variables.tf` | Account, environment, capacity and security inputs. |
| `aws/network.tf` | VPC, subnets, routing and network controls. |
| `aws/compute.tf` | EKS, ECR, deployment access and Pod Identity. |
| `aws/automation.tf` | Private CodeBuild platform bootstrap, source/output storage and delivery roles. |
| `aws/github-oidc.tf` | Immutable GitHub identity claims and workload boundary input. |
| `aws/data.tf` | Databases, cache, object storage, queues, encryption and secrets. |
| `aws/web-auth.tf` | Frontend delivery, certificates and Cognito authentication. |
| `aws/ml-observability.tf` | ML platform resources, monitoring and budget configuration. |
| `aws/outputs.tf` | Values consumed by reviewed release configuration and bootstrap tooling. |
| `aws/policies/` | Controller IAM policy and upstream provenance. |
| `aws/*.example` | Backend and Terraform-variable templates. |

`bootstrap/` and `aws/` are independently initialized Terraform roots. The main
AWS stack is organized into files in one root; these are not reusable child
modules. The `environment` input supports `dev`, `test`, `uat` and `production`.
Separate deployments need separate backend state and reviewed account/network
configuration. Do not reuse one state file for different environments.

The pipeline helper generates the repository configuration and `TFVARS_JSON`
secret. Plans and state stay in private S3. Actual `*.tfvars`, generated
configuration, state, plans and credentials are ignored by Git.

The legacy `.tfvars.example` files use a production capacity profile; the
pipeline helper defaults to `ci/capacity-demo.json`. Selecting a development
Kustomize overlay alone does not resize AWS resources or make the stack free.

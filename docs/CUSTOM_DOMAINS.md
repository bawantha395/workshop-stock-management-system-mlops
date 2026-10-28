# Stocklane custom domains

| Address | Route |
| --- | --- |
| https://stocklane.bawantha-rathnayake.tech | CloudFront -> private S3 frontend |
| https://api.stocklane.bawantha-rathnayake.tech | Existing public API ALB -> EKS services |
| https://argocd-stocklane.bawantha-rathnayake.tech | Restricted shared admin ALB -> Argo CD HTTPS |
| https://grafana-stocklane.bawantha-rathnayake.tech | Same restricted admin ALB -> Grafana |

This source includes the AI/MLOps release and permanent network patches. These
addresses do not become live merely by uploading the ZIP. Follow the sequence below.
Do not replace later GitOps commits when copying a complete source snapshot.

## 1. Update the existing pipeline trust

The original CI role only managed Sydney ACM certificates and API DNS names.
CloudFront needs a certificate in us-east-1, and your new hostnames need DNS rights.
This update adds scoped CloudFront-certificate permissions and DNS changes within
your owned public hosted zone. It keeps EKS, RDS and other workloads in Sydney.

Upload the new source and validate it. In CloudShell, pull the updated main and
rerun the existing bootstrap helper against the SAME project/account:

```bash
export AWS_REGION=ap-southeast-2
export AWS_DEFAULT_REGION=ap-southeast-2
cd ~/workshop-stock-management-system-mlops
git pull --ff-only
python3 scripts/bootstrap_pipeline.py \
  --repository bawantha395/workshop-stock-management-system-mlops \
  --project-name stocklane-dev \
  --environment dev \
  --auth-mode access-key \
  --region ap-southeast-2 \
  --expected-account 721274598579 \
  --hosted-zone-id Z035879924YQHJ4M5G2A3 \
  --api-domain api.stocklane.bawantha-rathnayake.tech \
  --budget-email bawantharathnayake395@gmail.com \
  --execute
```

This updates the existing trust stack. Do not create a new access key or replace
your current TFVARS_JSON with the helper's newly generated defaults. Retain all
existing infrastructure values and credentials. Review the CloudFormation changes.
The certificate permissions use a separate managed policy to stay within IAM's
10 KiB aggregate inline policy limit.

If your Organizations SCP denies ACM in us-east-1, this code cannot override it.
The account administrator must permit the CloudFront certificate operations, or
continue using the CloudFront hostname. Do not deploy EKS in another region.

## 2. Configure domain and AI inputs

Find your HOME/OFFICE public IPv4 address from the network where you will open the
admin dashboards (not CloudShell's egress IP). Merge the following keys into the
EXISTING GitHub TFVARS_JSON secret, replacing the IP placeholder:

```json
{
  "web_domain": "stocklane.bawantha-rathnayake.tech",
  "argocd_domain": "argocd-stocklane.bawantha-rathnayake.tech",
  "grafana_domain": "grafana-stocklane.bawantha-rathnayake.tech",
  "admin_allowed_cidrs": ["YOUR_PUBLIC_IPV4/32"],
  "bedrock_model_id": "amazon.nova-lite-v1:0",
  "bedrock_model_arn": "",
  "bedrock_daily_request_limit": 50
}
```

Use a valid IP before running Terraform. Admin ranges must be /24 or narrower;
0.0.0.0/0 is rejected. A phone on mobile data may have a different public IP and
will be blocked from the dashboards. The stock frontend remains publicly reachable
and requires Cognito sign-in. Do not paste secrets or passwords into chat.

## 3. Plan and apply

Run the existing Terraform plan workflow. Review its new resources:
- Public ACM certificate in us-east-1 for CloudFront, DNS validation and web A alias.
- Regional Sydney ACM certificate covering both admin hostnames.
- CloudFront alias and TLS configuration.
- Cognito custom-domain callback/logout URLs; existing CloudFront callbacks retained.
- Existing Bedrock and model-review IAM/configuration changes from the AI release.

Apply only the reviewed plan. Keep all DNS validation records for certificate
renewal. The existing CloudFront distribution, Cognito pool and stock database
are updated/reused rather than replaced by this feature.

## 4. Prepare and deploy the release

Prepare AWS release from the updated main using its new Terraform outputs. Review
and merge its GitOps PR. Admin ingress YAML is generated in the platform overlay,
with explicit argocd/monitoring namespaces, and stays under Argo CD management.
A Grafana environment patch sets its public root URL and secure session cookies.

Run platform deployment. Bootstrap installs the ingress resources after their
namespaces exist; its existing DNS step now publishes the API and both admin aliases
from their ALB addresses. Publish reviewed frontend afterwards. Its API CORS origin
now points to https://stocklane.bawantha-rathnayake.tech. Sign in again on that domain
because browser sessions are origin-specific. Use the new domain for business tests.

CloudFront invalidation now includes /, /index.html and /config.js.
Platform readiness also checks that the application child has synced the reviewed
commit, rather than relying only on a healthy root application with old pods.
Network policies are applied before the model-index hook can depend on them.

## 5. Open the dashboards

Use the exact HTTPS addresses in the table from an allowed public IP.
Argo CD retains its existing login; Grafana retains its existing admin secret.
This change does not create Cognito single sign-on for these dashboards and does
not enable anonymous access. Keep credentials in their existing Kubernetes/Secrets
Manager locations. Use AWS/Kubernetes access to retrieve them privately if needed.
The Argo backend connection uses HTTPS; Grafana uses HTTP inside the VPC behind
ALB TLS termination and secure public cookies.

Both dashboards share ONE additional admin ALB to reduce duplication. That ALB,
Route 53 usage and the rest of your AWS platform have ongoing costs. This is not
a free-tier-cost guarantee. Bedrock is on demand; SageMaker training is explicit.
If you do not want admin ALB charges yet, leave both admin domain variables empty.

For disabling/removing admin exposure later, remove the ingress/DNS records through
a reviewed change; clearing optional variables alone does not prune old resources
because this repository deliberately disables automatic Argo CD pruning.

## Photo catalogue and ML

Register first, then open Find an item -> select the item -> Add a reference photo.
Review the selected item and save the verified reference. Stock does not change.
Each workshop's dataset must use its actual item identities. This release remains
a single-workshop deployment; it does not claim multi-tenant isolation.
Read AI_MLOPS_RELEASE.md for reviewed dataset upload, training, approval and rollback.

## Verification limits

Automated checks exercise rendered admin ingress namespaces, shared ALB/IP
restrictions, backend HTTPS and Grafana cookie/root URL configuration. Terraform
formatting, Python checks and frontend build/tests are run for the handoff.
DNS propagation, certificate issuance, AWS account permissions and paid model
invocation must be verified by your pipelines in your account; they were not run here.

References:
- https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html
- https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/

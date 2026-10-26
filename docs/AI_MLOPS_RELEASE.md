# Corrected network policy and AI/MLOps lifecycle

This release is based on main 38761b6. It retains that release's frontend and
image references while permanently fixing the Inventory Service egress policy.
Both the base and dev overlay now select workshop, vision, vision-index and forecast.
The renderer uses the corrected base when preparing future releases.

**Complete ZIP deployment:** this package also adds the Forecast microservice. Follow [DEMAND_FORECASTING.md](DEMAND_FORECASTING.md) for Terraform and image-release order first. The isolated network-only procedure below is not a substitute for releasing the new service.

## Deploy the network fix first

Upload the updated source to your synchronised main and pass Validate platform.
The network policy change does not require a container build. Sync the existing
Argo CD application. If the old PreSync Job blocks it, patch the live selector
once AFTER committing the corrected manifests, as in the troubleshooting steps.
Verify Vision can reach inventory:8081, then retry the pending receipt's unfinished
reference update. Do not create a second receipt for already-recorded units.

## Low-cost Bedrock label suggestions

Model: amazon.nova-lite-v1:0, using regional Sydney Bedrock Converse. Amazon's
model card lists in-region Sydney support. Your account's SCP, model access and
quotas still apply; an available model does not imply permission to invoke it.

Merge ONLY these keys into the existing TFVARS_JSON GitHub secret (retain all
current networking, account, budget, database and domain settings):

```json
{
  "bedrock_model_id": "amazon.nova-lite-v1:0",
  "bedrock_model_arn": "",
  "bedrock_daily_request_limit": 50
}
```

Run Terraform plan, review its IAM/configuration changes, and apply the reviewed
plan. It publishes the model ID into deployment outputs; the next Prepare AWS
release renders it into the vision configuration. Merge the release PR, complete
platform deployment and frontend publication. No Bedrock API key is needed: the
existing EKS Pod Identity role receives permission for this regional model only.
Do not use a US or cross-region inference profile to work around an account deny.

The app makes on-demand requests only when a user requests label suggestions.
Responses are capped at 450 output tokens. Cached results live 15 minutes per
image ID/model/prompt. Redis limits uncached requests to 50 per UTC day by default,
shared across replicas. Cache failure disables paid suggestions instead of silently
removing the limit. Failed attempts also consume allowance. This is an application
request limit, not an AWS-account dollar spending cap. It does not control calls
made outside the app. Manual registration remains available.

Token usage and model ID are logged; images, label text and credentials are not.
The LLM can propose visible label fields only. It cannot change quantities, approve
catalogue entries, invent prices or determine vehicle fitment.

Pricing: use the current AWS Bedrock pricing page with Sydney selected before
activation. Charges depend on input tokens (including the image) and output tokens.
For an ILLUSTRATION only, at $0.06/M input and $0.24/M output, a request consuming
2,000 input plus 300 output tokens costs $0.000192, or $0.192 per 1,000 requests.
Actual regional rates, image token counts, retries and other AWS costs may differ.
No provisioned throughput or new hosted endpoint is created by this integration.

### Bedrock UAT

Find an item > Identify from photo > photograph an unfamiliar product label >
Suggest details from label. Check name, brand and manufacturer part number.
Review every field, approve registration, print its QR and confirm the receipt.
A registration inside a receipt starts at zero stock until receipt confirmation.
After the daily limit, manual entry must still work. Use the server status endpoint
or UI to verify configuration; do not print tokens or secrets for diagnosis.

## SageMaker lifecycle implemented

Reviewed photos -> immutable S3 dataset -> bounded SageMaker training -> separate
validation/test gate -> pending Model Registry package -> explicit review workflow
-> Prepare AWS release with approved package ARN -> GitOps -> EKS model serving.

This is a GitHub Actions-orchestrated SageMaker Training/Model Registry lifecycle,
not a native SageMaker Pipelines graph or a claim to implement every SageMaker
feature. Training fits a same-SKU logistic similarity calibrator on frozen
MobileNet embeddings. It does not fine-tune MobileNet or train a room-wide object
detector. After release, retrieval uses the model's learned decision threshold.
The model still requires human confirmation before stock changes.

### 1. Collect and review data

Create a local reviewed folder containing manifest.csv and JPEG/PNG images:

```csv
file,sku,session,split
images/filter-a-01.jpg,ITEM-FILTER-A,session-a,train
images/filter-a-02.jpg,ITEM-FILTER-A,session-b,validation
images/filter-a-03.jpg,ITEM-FILTER-A,session-c,test
```

The three rows above are a FORMAT EXAMPLE, not a trainable dataset. Minimum 60
unique real images; every split needs at least 15 images across 3 SKUs. Use
independent capture sessions across splits. Aim for at least 90 diverse photos
(3 or more SKUs represented in every split), different angles and realistic
lighting. Duplicate image bytes and capture-session leakage are rejected.
These minimums do not guarantee a useful model or that quality gates will pass.

### 2. Upload the immutable dataset

From a machine with the reviewed folder and an authorised AWS CLI/SDK session:

```bash
python3 -m pip install boto3==1.43.118
python3 mlops/upload_dataset.py \
  --directory /path/to/reviewed \
  --bucket stocklane-dev-models-721274598579 \
  --region ap-southeast-2
```

Keep the returned datasetUri. Each upload gets a content-addressed prefix and
per-file checksums. Existing bytes cannot be overwritten by the uploader.
Photos never become training data simply because they entered the camera inbox:
review their SKU and assign session/split before uploading.

### 3. Train

Run **Train reviewed workshop model** from main in GitHub Actions. Provide
`dataset_uri`; leave `encoder_uri` and `training_image` empty to use the approved
encoder bundle and ml-training image. The workflow verifies/stages the approved
encoder into S3 and selects the pinned ECR training image automatically.

One CPU ml.m5.large instance, 10 GiB training volume, network isolation and a
600-second training runtime limit are used. The controller requests a stop after
20 minutes of wall-clock waiting. The instance is a transient training job; no
24-hour SageMaker endpoint or Studio notebook is created. Account restrictions
and regional training quotas can block it. Do not assume your free-plan credits
permit every API/instance; inspect the returned AWS denial if creation fails.

Validation selects a threshold at >=98% pair precision; independent test precision
must be >=98%, recall >=50%, and at least 10 test-positive predictions are required.
Failing runs cannot register a releasable model. Review the metrics: these are
pairwise test metrics on your dataset, not a production accuracy guarantee.

### 4. Review and approve

A passing run prints its package ARN and metrics in the Actions summary. Inspect
them and the training logs, then run **Review SageMaker model**, supplying that ARN
and Approved or Rejected. This workflow uses the existing aws-training environment;
configure its required reviewers/main-branch restriction for your desired governance.
It only permits packages belonging to this account, region and project model group.
Do not approve a model simply to bypass a failed quality gate.

### 5. Promote and deploy

Run **Prepare AWS release**, providing `model_package_arn` with the approved ARN.
Existing promotion checks approval, quality flags and artifact checksum, then copies
the immutable bundle to the release prefix. Review and merge the generated GitOps
PR, deploy the platform and verify the index Job and applications are healthy.
Check /api/vision/status for the deployed model version. Test several known and
unseen item photos; keep human confirmation enabled.

For rollback, run Prepare AWS release with a previously approved package ARN and
review that release PR. No retraining is required. Baseline retention remains
supported for installations without a trained package.

## Required pipeline order

1. Upload this source and commit the corrected network policies.
2. Validate platform.
3. Merge the Bedrock keys into existing TFVARS_JSON; plan and apply the reviewed
   Terraform changes (Bedrock permissions/config and model-review permission).
4. Prepare AWS release; merge GitOps PR; deploy and publish frontend.
5. Test optional Bedrock suggestions.
6. Collect/review images, upload dataset, train, review and promote your model.

No paid invocation, training job or deployment was executed while creating this
package. Java/AWS integration, phone-camera behaviour and model quality on real
workshop data must be verified in your account. Existing stock records and pending
receipt commands should be retained.

Sources checked 26 October 2026:
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html
- https://aws.amazon.com/bedrock/pricing/
- https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html

## Verification completed for this ZIP

- Frontend production build and all 8 frontend tests passed.
- Combined vision/platform suite: 160 passed, 5 skipped. A subsequent targeted
  rerun passed all 7 AI lifecycle checks after adding streamed dataset upload
  coverage and tightening label field lengths.
- Terraform format check and Python compilation passed. Existing platform tests
  exercise Terraform configuration evaluation and Kustomize rendering.
- Live SageMaker training, paid Bedrock invocation and AWS deployment were not
  executed. Java 21 compilation remains a required existing CI gate.

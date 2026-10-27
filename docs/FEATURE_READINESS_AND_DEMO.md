# Stocklane feature readiness and synthetic training

Checked against repository baseline 46ca6c78d56d052470af379874c7f1c21cc08f32,
the supplied fixes, and the deployment outputs shared in this conversation.
Current AWS account state must be checked with the included runtime checker.

## What is ready, blocked, or awaiting evidence

| Feature | Latest evidence | Action |
| --- | --- | --- |
| Catalogue, QR and confirmed stock IN/OUT | You reported the deployed stock flow working | Repeat the happy path after the updated release |
| Vision to Inventory networking | The Git source already selects workshop, vision, vision-index and forecast in the Service egress policy | Reconcile Git instead of repeating a temporary kubectl patch |
| Baseline photo matching | A pretrained MobileNetV2 encoder was loaded; reference retrieval is implemented | Collect real references and test different camera sessions |
| Custom workshop photo model | No completed real-data SageMaker training and approved deployed package have been shown | Train on reviewed real part photos for production evidence |
| Demand forecast | Your published result had 9 insufficient-history items, with null trainingJob and modelPackageArn | Keep recording real history; use the separate demo workflow for training practice |
| Bedrock label suggestions | The last actual model request returned ThrottlingException and the applied model quotas were zero | Check the current quota/access state; changing source code cannot grant an AWS allowance |
| Monitoring | Grafana's Prometheus UID was missing and the two Java scrape endpoints returned HTTP 401 | This patch corrects provisioning and token handling; release it and verify the live scrapes |
| SQS | Inventory publishes catalogue events, Vision consumes them, and Workshop consumes stock events | This patch also publishes ordinary opening, receipt and stock-out movements; verify queue activity after a test movement |
| Room-wide CCTV counting | Deferred from the first phase | It is a future feature, separate from the implemented controlled capture path |

Model configuration, a green workflow and a Ready pod are separate evidence.
They do not establish model accuracy, provider access or full production readiness.

## What this update changes

- Java metrics keep their internal-token protection while the exact metrics
  route avoids being interpreted as a Cognito user-JWT request.
- Grafana provisions the expected Prometheus UID and receives a rollout when
  startup provisioning changes. Persistent Grafana data is retained.
- Bedrock failures return useful, sanitized quota, permission, configuration,
  timeout or invalid-response explanations. Raw provider error text is not
  shown. `/api/vision/status` distinguishes configured from verified access;
  its observation belongs to the responding replica. Draft outcomes are metrics.
- Every committed stock movement creates an outbox event. Retrying a confirmed
  command does not create a second event. Workshop acknowledges stock-only events
  without creating a customer, repair allocation, price calculation or bill.
- Demo training is separate from the live release path. No Terraform/IAM changes
  or new always-running model endpoint are introduced by these fixes.

## Included synthetic datasets

| Dataset | Size | What it exercises |
| --- | --- | --- |
| Catalogue | 24 generic items | Filters, brakes, belts, ignition/electrical parts, fasteners, fluids and seals |
| Cold-start forecast | 9 items, 14 days each | Explicit insufficient-history handling |
| Weekday forecast | 12 items, 56 days each | Friday peaks and weekday baselines |
| Mixed seasonal forecast | 24 items, up to 1,095 days | December/April seasonality, Friday peaks, growth, intermittent usage, stock-outs and new products |
| Visual fixtures | 216 JPEG illustrations, 12 SKUs | 72 images per train/validation/test split, distinct rendered capture sessions, checksums and varied views |

The simple growth profiles deliberately provide a learnable artificial signal.
The visual fixtures are code-generated illustrations, not photographs of real
workshop parts. No manufacturer fitment or real demand is implied. Their metrics
describe only these fixtures. Do not import them into the live stock ledger.

Generate a different reproducible dataset from the updated repository:

```bash
python3 -m pip install pillow==13.0.0
python3 mlops/generate_demo_data.py \
  --output artifacts/demo-data-2 \
  --seed 20261028
```

The default seed is 20261027. Change the seed to vary noise, intermittent usage,
backgrounds and visual views. A different seed need not pass the evaluation gate.
Keep a rejected candidate as evidence of a working rejection path.

## Release the fixes first

1. Apply the supplied patch to an updated clean checkout. Review and push it.
2. Let **Validate platform** pass.
3. Complete **Prepare AWS release**, using an already-triggered run if present.
4. Review and merge the generated GitOps release PR. This step releases the new
   ml-training image containing explicit demo-mode support.
5. Complete **Bootstrap EKS platform** and check the child application's revision
   and rollout. The Grafana manifests and rebuilt Java images are both required.

The existing permanent Service egress policy remains in Git. Do not replace it
with a selector that only allows the Workshop pod.

## Run both SageMaker demo jobs

In GitHub Actions, open **Train demo ML models**, select `main`, choose `both`
and use seed `20261027`. The existing `aws-training` environment and repository
AWS variables/secrets are reused.

The workflow generates and uploads the dummy inputs itself. It runs the actual
SageMaker Training API, evaluates candidates, and registers passing demo packages
in the existing visual-SKU/forecast registry groups. Descriptions and metadata
clearly label the versions **SYNTHETIC DEMO ONLY**. They remain pending approval.

Synthetic inputs and output artifacts stay under the model bucket's `demo/`
prefix. The checksum-verified approved encoder is staged immutably under its
existing encoder prefix. No live forecast pointer, model URI, GitOps release or
stock record is changed by the demo workflow.

The normal photo-upload/training paths reject marked synthetic input. Production
approval and promotion reject synthetic packages/artifacts. Vision refuses to
load a synthetic encoder; Forecast refuses to serve synthetic projections.
The normal forecast publication runner refuses marked dummy history.

Each selected task uses one CPU `ml.m5.large` instance with a maximum 600-second
training runtime. There are no GPU jobs or permanent SageMaker endpoints. AWS
training charges and account quotas still apply. A free-plan restriction or a
zero training quota must be resolved in AWS; the workflow does not change the
account plan or bypass limits.

Inspect `artifacts/demo-training-report.json` in the workflow summary. A valid
demo result includes a real training job, artifact URI and model package ARN,
along with `syntheticData: true` and `productionEligible: false`. Local results
in the data ZIP are labelled local validation and do not prove an AWS run.

## Bedrock and production data

Amazon Nova in Bedrock is a managed pretrained model. The dummy data does not
train or unlock it. The last regional request used `amazon.nova-lite-v1:0` in
Sydney. Test that exact configured runtime/identity after AWS access is restored;
an increase for a different inference mode alone is not an application test.

For a real workshop photo candidate, collect at least 60 unique reviewed images
with session-separated train, validation and test splits and at least 3 SKUs per
split. More varied real examples are normally needed for useful quality.

For this forecast implementation, a weekday baseline requires at least 28 recent
complete available-stock days. An ML candidate requires at least 112 days, 20
positive-usage days and sufficient uncensored windows. Annual features require
730 days before the 42 held-out validation/test days. Day counts alone do not
guarantee a passing model. Only real consistently recorded history should inform
actual replenishment decisions.

## Check current AWS and workload evidence from CloudShell

Run from your updated repository in CloudShell. Use a session that can reach the
private EKS API, or retain the existing permitted endpoint access. The script
creates a temporary kubeconfig for the intended cluster, avoiding the recurring
localhost:8080 issue.

```bash
export AWS_REGION=ap-southeast-2
export AWS_DEFAULT_REGION=ap-southeast-2
aws sts get-caller-identity --query Account --output text --no-cli-pager
python3 -m pip install --user -r scripts/requirements.txt
python3 scripts/check_readiness.py \
  --project stocklane-dev \
  --expected-account 721274598579 \
  --region ap-southeast-2 \
  --environment dev \
  --kubernetes \
  --probe-bedrock
```

The optional Bedrock flag makes one small, bounded text request under the actual
Vision Pod Identity. It checks invocation access, not photo-draft quality. The
script prints no token or secret values. Its remaining operations read model,
history, registry, queue and CloudWatch state; it does not start training or send,
receive, delete or purge queue messages. AWS permission or network failures are
reported as unverified rather than healthy.

The private report is `artifacts/readiness-report.json`. It distinguishes a
loaded baseline, a calibrated real model, demo-only registry versions, missing
history, actual invocation access and recent queue activity. It does not certify
production readiness or business acceptance.

After the release, verify the Grafana UID and all four application scrapes as
described in MONITORING_AUTH_FIX.md. To test SQS, perform one real test receipt or
stock-out using the UI, then inspect Sent/Received/Deleted metrics and the DLQ.
An empty queue may simply be idle; it does not prove that an event was processed.

## References

- Bedrock quotas: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html
- SageMaker Model Registry: https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html
- SQS dead-letter queues: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html

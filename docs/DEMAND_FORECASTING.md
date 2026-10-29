# Stock usage forecasting — release and operation

This release implements a separate **Forecast microservice** on EKS, a history
snapshot owned by Inventory, and a single protected **Train and publish stock
forecast** GitHub Actions workflow. It does not contain a model trained on your
workshop yet. Real data is required. Synthetic histories exist only in tests.

## Service boundaries

| Component | Responsibility |
| --- | --- |
| Inventory, Spring Boot | Authoritative stock ledger, current availability, owner-confirmed history snapshot to S3. No forecasting algorithm. |
| Forecast, Python/FastAPI | Owner-only GET /api/forecast, read published projections from S3, combine with current Inventory quantities and suggest a seven-day top-up. No stock writes or direct database access. |
| Vision, Python | Photo embeddings / visual SKU matching and optional Bedrock label suggestions. Independent of the forecast model. |
| SageMaker AI | Bounded batch training and chronological evaluation. Accepted models are versioned in a separate stock-forecast Model Registry group. |
| GitHub Actions | Protected training, quality gate, artifact publication and summaries. No native SageMaker Pipelines graph or always-running SageMaker endpoint. |
| SQS | Existing stock and catalogue queues, retries and dead-letter queues. Forecast training currently reads an explicit snapshot, not an SQS consumer. |
| SNS | Existing operations alarms / notifications. |
| MSK | Not used. Kafka infrastructure is unnecessary for this phase. |

Separate Deployment, Service, ServiceAccount, ExternalSecret, HPA,
PodDisruptionBudget and ServiceMonitor YAML live in
`deploy/kubernetes/apps/base/forecast/`. ConfigMap and NetworkPolicy remain
shared platform controls. The service is stateless and does not need a PVC.
It has its own ECR repository and Pod Identity with read-only access to the
published forecast. Its temporary filesystem is an emptyDir, not persistent data.

## Deploy it

The Forecast service is part of every environment. **Deploy environment**
creates its ECR repository, Pod Identity and the stock-forecast Model Registry
group, builds its image and waits for its deployment with the other services.
The forecast workflow below handles training through publication **after** the
environment is deployed; it cannot bypass Terraform review or manufacture
missing history.

## Run forecasting once

1. Sign in as OWNER. Open **Stock analysis → Stock demand forecast**.
2. Expand **Prepare history for the forecast pipeline**.
3. Set the first day on which all stock movements were reliably recorded.
   Confirm the checkbox only when this is true. Zero-filled missing days are valid
   only under this assumption; the software cannot discover unrecorded movements.
4. Click **Prepare forecast history**. Inventory writes a content-addressed JSON
   snapshot and latest snapshot pointer in the private model bucket. All active
   catalogue items are included, not just the current report filter. No browser
   AWS credentials or manual S3 CSV upload is required.
5. GitHub Actions → **Train and publish stock forecast** → Run workflow → main.
   Leave Publish selected to authorise publication within the protected
   `aws-training` environment. The training role/credentials are reused; no new
   GitHub secret is needed. Configure required reviewers for that environment
   if you want a separate human release approval.
6. Read the workflow summary: training job, registry ARN (if accepted ML), dataset
   hash, versioned S3 release URI, evaluation metrics and per-method counts.
7. Refresh the forecast in the web app. The service caches S3 for at most 60
   seconds. Current stock is fetched live from Inventory on each request.

A newly installed workshop will show **More history needed**. With fewer than
112 eligible days, the workflow skips paid SageMaker training and publishes
labelled baselines or insufficient-history rows. It still completes successfully.
No synthetic data is imported into stock or used as your production history.

## Actual model and acceptance gate

- One model per SKU: regularised linear regression (Ridge), with weekday indicators,
  previous-week usage and seven-/28-day rolling means.
- Separate 14-day chronological validation selects regularisation. The final
  **28 days are held out** for recursive testing; predictions do not see actual
  future test quantities. Month indicators and annual sine/cosine features are enabled only when at
  least 730 days exist before those 42 held-out days.
- Accepted ML requires test WAPE <= 60% and MAE at least 5% lower than the fixed
  origin four-week weekday baseline. Exact weekly baselines are kept instead of
  labelling an equivalent model as an improvement.
- Minimum 112 days, 20 positive-usage days, enough uncensored training windows,
  and fully in-stock recent validation/test days. Short or censored histories
  fall back conservatively. At least 28 recent complete in-stock days are needed
  even for the baseline.
- Refit an accepted model on all available eligible history. Save coefficients,
  intercept, hyperparameters, lineage, evaluation and 37 daily projections.
- A failed quality gate preserves a labelled weekday baseline for that item.
  A training/API failure fails the workflow and does not replace the current
  forecast. Mixed catalogues can contain accepted ML, baseline and data-needed rows.
- No confidence intervals, maintained holiday calendar, weather feeds, supplier
  lead-time optimisation, automatic purchase orders or automatic retraining
  schedule are claimed in this phase.

Friday/December effects are learned only if the history supports them. Annual/month
features can learn seasonal patterns, but do not guarantee a December spike.
Use actual recorded stock-out usage as the target, not customer repair counts.
Returns affect stock availability but do not reduce historical outgoing usage.

## Safety, costs and limits

The snapshot excludes today's partial Asia/Colombo day and the partial product
registration day. Products can have different tracking lengths. Ledger totals
must reconcile with current stock. Days with zero beginning/end stock are censored;
unrecorded intraday stock-outs remain a limitation. Training does not infer unmet
demand. End-of-day/starting balance is only an availability proxy.

One CPU `ml.t3.large` SageMaker Processing job (or an `ml.m5.large` training job
with `SAGEMAKER_JOB_TYPE=training` once the account has training quota), a
runtime limit, network isolation, no automatic retries and a controller
wall-clock stop limit are used. Account SCPs and SageMaker quotas still apply. There is no continuously billed SageMaker endpoint.
The Forecast EKS pod requests 50m CPU / 96Mi memory. Check cluster headroom;
existing tiny nodes may need capacity before another pod can schedule.

History snapshots are bounded to 1000 active items, 200000 movements, three years
and 12 MiB; larger histories require an offline extraction pipeline. They stay
private in the versioned project model bucket. No prices, customers or vehicles
are sent to the model. Owner identity is retained as confirmation audit metadata.

Published forecasts are rejected when history is over seven days old. The
37-day artifact allows rolling 7-/30-day displays through that interval. Refresh
history and rerun weekly or after a meaningful demand change. Training is manual
and bounded; there is no paid scheduled job enabled automatically.

Recommendations use **ceil(max(0, next seven-day usage minus available stock))**
for pieces, and round up to 0.001 litre for measured stock. They exclude supplier
lead time and safety stock and never create a receipt, issue or purchase order.
Forecast table estimates are not guaranteed future demand.

## Rollback and monitoring

S3 versioning retains earlier `forecast/current.json` objects. Restore a reviewed
previous version via your normal controlled AWS change process; freshness checks
still apply. Versioned `forecast/releases/<sha>/forecast.json` objects and workflow
summaries preserve lineage. Re-running with Publish unchecked evaluates and stores
a candidate without replacing current.json (accepted ML is PendingManualApproval).

The Forecast ServiceMonitor exposes authenticated request outcomes and history
age. Age is updated when forecasts are requested. General pod/HTTP reliability
monitoring remains in the existing platform. Compare subsequent observed outgoing
usage with saved projections before claiming ongoing forecast accuracy. Automatic
live drift scoring/alerting is not implemented in this phase.

## Happy-path acceptance

- OWNER can prepare history; MECHANIC receives 403 at both sensitive endpoints.
- Brand-new item: data-needed, with no fabricated 7-/30-day numbers.
- Confirmed 35-day, in-stock weekly history: labelled weekday baseline.
- Sufficient real history: SageMaker job appears; test metrics determine whether
  a SKU is accepted ML. Pipeline failure leaves the previous artifact intact.
- Receive/take out stock: live availability and top-up change, while predicted
  usage and ledger quantities remain untouched by the forecast service.
- New snapshot → workflow → refresh: lineage/date and method update.
- A stale artifact produces a refresh message and no actionable top-up.

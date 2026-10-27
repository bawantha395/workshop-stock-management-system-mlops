# Train Stocklane with real public data

This update adds **Train real-data ML models** (`train-public-data.yml`). It downloads licensed, checksum-pinned public inputs, creates actual SageMaker Training jobs in **ap-southeast-2**, evaluates the models and records pending Model Registry versions. No manual SageMaker notebook, Studio domain or persistent endpoint is required by this workflow.

The update has been tested locally. No authenticated AWS job was submitted during its preparation. A workflow file, an EKS baseline model and a populated SageMaker model package group do not prove that custom training has run.

## Real inputs included

| Input | Prepared subset | Source and purpose |
| --- | --- | --- |
| Product imagery | 115 source catalogue images; 23 product identities; five images each | [Amazon Berkeley Objects](https://registry.opendata.aws/amazon-berkeley-objects/), CC BY 4.0. Tools, workshop supplies and automotive accessories; not a Mitsubishi fitment database. |
| Historical sales | 64 complete anonymous parts series; 3,264 observed months | [Monash Car Parts with Missing Values](https://zenodo.org/records/4656022), DOI 10.5281/zenodo.4656022, CC BY 4.0. Original monthly observations from January 1998 to March 2002. |

Source image bytes and observed values are preserved. Nothing is generated to imitate a real photograph or sale. Unknown sales are not filled with zero. Series containing missing values are excluded. Series selection considers availability and positive sales in the initial training period, then uses a fixed SHA256(series ID) ordering. It does not select histories based on held-out prediction errors.

Image splits contain different product identities: eight training, eight validation and seven test products. Duplicate image bytes are rejected. The source does not provide independent physical capture sessions. The manifest's `session=source-product:<ASIN>` is a grouping key, not an invented camera session. A visual review excluded five images from one listing whose motor-oil title pointed to chair imagery. Catalogue sets also include close-ups, bundled accessories and explanatory panels; these are not independent workshop camera observations.

The history IDs are anonymous. They have no known relationship to the photo ASINs, Montero part numbers, Sri Lankan customers or this workshop. Sales are not known unconstrained demand: the source does not provide stock availability. The monthly records stay monthly and retain their historical dates.

## Models and evaluation

**Photos:** a frozen pretrained MobileNetV2 encoder produces embeddings. Logistic regression learns same-product versus different-product similarity from the real image pairs. This trains the calibrator; it does not fine-tune the MobileNet backbone or train an object detector. A validation split selects the threshold; held-out product identities measure generalization.

**History:** a separate monthly benchmark fits Ridge candidates using month, lag and rolling-history features. Six chronological validation months select regularization and a comparison baseline. Seasonal-naive, Croston-SBA and recent-mean baselines compete on that validation period. The last 12 months are held out. Multi-month predictions are recursive and do not read the future actual sales.

The public monthly benchmark uses the existing forecast training image and Model Registry group. It does not add an EKS microservice or replace the daily workshop forecast schema. Daily and Friday patterns cannot be recovered from monthly totals.

### Measured local results, 2026-10-27

| Check | Result |
| --- | --- |
| Photo independent-test precision | 0.3846 |
| Photo independent-test recall | 0.0714 |
| Photo quality gate | Failed |
| Monthly pooled Ridge MAE | 0.7357 sales per series-month |
| Monthly pooled selected-baseline MAE | 0.6703 |
| Monthly pooled quality gate | Failed; one of 64 series passed its individual gate |

These are local measurements, not evidence of a completed AWS run. `local-validation-report.json` in the data ZIP contains the full metrics and hashes. The AWS workflow records its own job names, artifacts and evaluations. The results show that a trained model can be worse than a simple baseline; a successful training job must not be presented as production acceptance.

Public candidates can still be archived with the failed quality results for MLOps practice. They are marked `syntheticData=false`, `benchmarkOnly=true`, `productionEligible=false` and **PendingManualApproval**. The live uploader, approval workflow, promotion script and EKS model loaders reject public benchmark artifacts. Even a manual console approval does not make them live workshop models.

## Run it using the existing pipelines

1. Apply the source update to a clean checkout, commit and push to `main`. Keep `Validate platform` green.
2. Run **Prepare AWS release** on `main`. Merge its generated GitOps release PR after validation. This publishes the updated `ml-training` container and digest. Skipping this step leaves the old training container, which does not support the new monthly task or benchmark flag.
3. Let **Bootstrap EKS platform** finish for the merged release, or run it on `main` if needed. Existing app/runtime fixes included in the cumulative patch are deployed here.
4. Open GitHub Actions → **Train real-data ML models** → **Run workflow** → branch `main` → task `both`. Complete the normal `aws-training` environment approval if your repository requires it.
5. Read the workflow Summary. Each created job has a returned ARN and `creationConfirmed=true`. A rejected request is labelled false; a guessed name is not reported as a successful creation.

The workflow fetches the real inputs and uploads them to a content-addressed S3 prefix automatically. You do not need to upload the data ZIP manually. The ZIP is provided so you can inspect and retain the exact inputs.

Both jobs use one `ml.m5.large` CPU training instance, sequentially, with a ten-minute training runtime limit each. SageMaker training, image/storage and transfer charges can apply to your account. No always-running SageMaker endpoint is created. Account free-plan restrictions, the training instance quota, permissions and available credits still apply; this has not been verified in your account.

There are no new Terraform resources or IAM permissions in this update. It uses the existing model bucket, ECR training image, SageMaker execution role and two Registry groups. Keep your existing GitHub variables and secrets. Do not replace `TFVARS_JSON` or rotate keys for this code change.

## What to see in AWS

Open [SageMaker AI in Sydney](https://ap-southeast-2.console.aws.amazon.com/sagemaker/home?region=ap-southeast-2).

- **Training → Training jobs**: look for `stocklane-dev-public-photo-...` and `stocklane-dev-public-forecast-...`, using the exact names in the workflow Summary. A successful job reaches `Completed`.
- **Model Registry**: look in `stocklane-dev-visual-sku` and `stocklane-dev-stock-forecast`. New public-data versions remain pending, with benchmark provenance and S3 evaluation reports.
- **CloudWatch Logs → /aws/sagemaker/TrainingJobs**: inspect the reported job's streams for training details.
- **S3 → stocklane-dev-models-721274598579 → benchmarks/public/**: immutable inputs, training artifacts and evaluations.

The SageMaker **Endpoints** page may be empty: Stocklane serves live inference on EKS. A Model Registry version is also different from a standalone SageMaker hosting **Model** resource. Neither hosting resource is created by this training workflow.

If the workflow fails before creation, check its `errorCode`: `ResourceLimitExceeded` means inspect the regional training-instance quota; `AccessDenied` may involve the role or an organization policy. If a job was created but failed, inspect that exact Training job and its logs. Do not claim a completed AWS run based on the local report.

## Move toward a workshop production model

Continue collecting approved photos when owners register real items, with actual product/part identifiers and capture sessions. Keep multiple physical examples, angles and lighting conditions; collect similar-looking negative examples. Use independent real capture sessions for evaluation. The normal **Train reviewed workshop model** path retains its quality gates.

Continue recording dated stock movements and availability in the workshop. The live daily forecast path learns from this business's history, with baselines while data is insufficient. A year or more is needed to observe annual seasonality, and evidence of a repeating effect requires validation across time. Public 1998–2002 sales cannot substitute for that operational evidence.

Bedrock is separate from these two ML jobs. Product-drafting suggestions invoke an existing foundation model; this update does not train an LLM or resolve the account's previously observed Bedrock quota restriction.

## New source files

| File | Why it exists |
| --- | --- |
| `mlops/public-data-sources.lock.json` | Exact source images, product splits, official URLs, licence and SHA256 pinning. |
| `mlops/prepare_public_data.py` | Downloads and validates real bytes, creates manifests and preserves monthly observations. |
| `mlops/monthly_parts_benchmark.py` | Evaluates monthly data without fabricating daily workshop history. |
| `mlops/run_public_training.py` | Submits actual SageMaker jobs, records ARNs and registers isolated benchmark candidates. |
| `.github/workflows/train-public-data.yml` | One workflow using the existing protected training identity. |
| `tests/test_public_data.py` | Checks provenance, split isolation, chronological selection, SDK request schemas and live-release barriers. |

`entrypoint.py`, the training Dockerfile and training/serving scripts support the new task. Release and readiness checks distinguish benchmark packages from production workshop candidates.

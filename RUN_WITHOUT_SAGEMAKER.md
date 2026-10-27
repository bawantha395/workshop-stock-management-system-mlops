# Train without SageMaker (GitHub runner or local)

Why: the SageMaker `ml.m5.large` training quota is 0 on free-tier accounts (ResourceLimitExceeded).
These models are small CPU jobs, so they run fine on a GitHub runner or your own machine.
Results are benchmark-only; nothing live is changed.

## Option A: GitHub Actions (recommended)
1. Push this repo to GitHub (the new workflow is `.github/workflows/train-public-data-runner.yml`).
2. Make sure repo variables `AWS_ACCOUNT_ID` and `PROJECT_NAME` and environment `aws-training` exist
   (same as the old training workflow; only needed for the photo task).
3. Actions -> "Train real-data ML models (on GitHub runner, no SageMaker)" -> Run workflow.
   Start with `forecast` (no AWS needed), then `photo`, then `both`.
4. Read metrics in the run Summary. Download models from the `benchmark-models` artifact.

## Option B: Local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r mlops/requirements.txt
cd mlops
python prepare_public_data.py --output ../artifacts/data --cache ../artifacts/cache

# forecast
python -c "from monthly_parts_benchmark import main; main('../artifacts/data/monthly-history','../artifacts/out/forecast')"

# photo (needs AWS CLI configured; S3 only)
URI=$(python -c "import json;print(json.load(open('../deploy/kubernetes/apps/overlays/dev/release.json'))['model']['uri'])")
aws s3 cp "$URI" /tmp/enc.tar.gz --region ap-southeast-2
mkdir -p ../artifacts/encoder && tar -xzf /tmp/enc.tar.gz -C ../artifacts/encoder encoder.onnx model.json
python -c "from train import train; train('../artifacts/data/photos','../artifacts/encoder','../artifacts/out/photo','local-public',benchmark_mode=True)"
```
Outputs land in `artifacts/out/`.

## Not included
No SageMaker model package is registered. To get that later, request the
"ml.m5.large for training job usage" quota in Service Quotas (ap-southeast-2).

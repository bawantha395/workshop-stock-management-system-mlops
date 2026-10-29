# Optional development and automated-test setup

## Start locally

Install Docker Desktop with Compose and Python 3. Use a terminal in this folder:

```bash
python3 scripts/configure_local.py
docker compose --profile tools run --rm model-init
docker compose up --build -d
```

Open **http://localhost:4173**. The first container build downloads normal
Java/Python/Node dependencies. The image model download is about **14 MB**.
No Ollama model, OpenAI account or AWS account is required for local matching.

Optionally add clearly labelled local sample records:

```bash
docker compose exec vision python /app/tools/seed_demo.py
```

Demo reference images are synthetic illustrations. They are not evidence of
workshop recognition accuracy. For meaningful matching, capture real photos
of your workshop's items and approve them as catalogue references.

```bash
docker compose ps
docker compose logs --tail=100 inventory workshop vision
docker compose down
```

`down` keeps stock, photos and invoice volumes. **Do not add `-v` when keeping
business records.** Local ports are bound to loopback. Local mode uses explicitly
labelled demo identities; the AWS configuration requires Cognito access tokens.

## Run the automated checks

Java 21 + Maven, Node 22 and Python 3.12 are needed outside Docker.

```bash
mvn -B -ntp verify
(cd apps/web && npm ci && npm run build && npm test)

python3 -m venv .venv && source .venv/bin/activate
pip install -r services/vision/requirements-dev.txt -r scripts/requirements-ci.txt fakeredis scikit-learn
python scripts/install_kustomize.py --directory "$PWD/deploy/generated/tools"
python scripts/install_kustomize.py --tool kubeconform --directory "$PWD/deploy/generated/tools"
export PATH="$PWD/deploy/generated/tools:$PATH"
python scripts/download_model.py
PYTHONPATH=services/vision pytest services/vision/tests tests -q
python scripts/validate_kustomize.py
```

Terraform checks (no AWS account needed; the plan uses mocked providers):

```bash
for env in dev staging prod; do
  terraform -chdir=infra/terraform/environments/$env init -backend=false
  terraform -chdir=infra/terraform/environments/$env validate
  terraform -chdir=infra/terraform/environments/dev test -var-file=../$env/terraform.tfvars
done
```

A no-Docker developer stack (H2 + SQLite) is also available for quick UI work:
`python scripts/dev.py --seed`, or `python scripts/dev.py --smoke-only` to start,
exercise and stop the real HTTP services.

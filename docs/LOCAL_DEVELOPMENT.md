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

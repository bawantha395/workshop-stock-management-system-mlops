FROM python:3.12-slim
WORKDIR /app
COPY services/vision/requirements.lock ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m app && mkdir -p /data/images /models/baseline && chown -R 10001:10001 /app /data /models
COPY --chown=10001:10001 services/vision/app ./app
COPY --chown=10001:10001 scripts/fetch_model.py scripts/reindex.py ./tools/
COPY deploy/certs ./certs
USER 10001
EXPOSE 8083
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8083","--no-server-header"]

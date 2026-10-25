FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir boto3==1.43.118 psycopg[binary]==3.3.6 && useradd -u 10001 -m app
COPY scripts/bootstrap_database.py ./bootstrap_database.py
COPY deploy/certs ./certs
USER 10001
CMD ["python","/app/bootstrap_database.py"]

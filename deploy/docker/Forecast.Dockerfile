FROM python:3.12-slim
WORKDIR /app
COPY services/forecast/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m app
COPY services/forecast/app ./app
COPY services/vision/app/security.py ./shared_security.py
USER 10001
EXPOSE 8084
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8084","--no-server-header"]

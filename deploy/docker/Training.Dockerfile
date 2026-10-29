FROM python:3.12-slim
WORKDIR /opt/program
COPY mlops/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/vision/app/encoder.py ./app/encoder.py
COPY services/vision/app/__init__.py ./app/__init__.py
COPY mlops/train.py mlops/dataset.py mlops/serve.py mlops/entrypoint.py ./
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python","/opt/program/entrypoint.py"]

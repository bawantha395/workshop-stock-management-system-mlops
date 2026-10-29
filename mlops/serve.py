"""SageMaker-compatible feature endpoint for Model Registry package validation.
The workshop application itself serves inference on EKS.
"""
import base64,os
from fastapi import FastAPI,HTTPException
from app.encoder import Encoder
from pathlib import Path
encoder=Encoder(os.environ.get('SM_MODEL_DIR','/opt/ml/model'))
app=FastAPI(docs_url=None,openapi_url=None)
@app.get('/ping')
def ping():return {'status':'UP'}
@app.post('/invocations')
def invoke(body:dict):
    try:
        data=base64.b64decode(body['image'],validate=True)
        if len(data)>8*1024*1024:raise ValueError()
        return {'embedding':encoder.encode(data),'modelVersion':encoder.version}
    except (KeyError,ValueError):raise HTTPException(400,'Provide a base64 encoded product image') from None

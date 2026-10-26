"""SageMaker-compatible feature endpoint for Model Registry package validation.
The workshop application itself serves inference on EKS.
"""
import base64,os
from fastapi import FastAPI,HTTPException
from app.encoder import Encoder
import json
from pathlib import Path
model_dir=Path(os.environ.get('SM_MODEL_DIR','/opt/ml/model'))
forecast=json.loads((model_dir/'forecast.json').read_text()) if (model_dir/'forecast.json').exists() else None
encoder=None if forecast else Encoder(str(model_dir))
app=FastAPI(docs_url=None,openapi_url=None)
@app.get('/ping')
def ping():return {'status':'UP'}
@app.post('/invocations')
def invoke(body:dict):
    if forecast is not None:
        rows=forecast['products']
        if body.get('productId'):rows=[p for p in rows if p['id']==body['productId']]
        return {'task':'stock_usage_forecast','historyUntil':forecast['historyUntil'],'products':rows}
    try:
        data=base64.b64decode(body['image'],validate=True)
        if len(data)>8*1024*1024:raise ValueError()
        return {'embedding':encoder.encode(data),'modelVersion':encoder.version}
    except (KeyError,ValueError):raise HTTPException(400,'Provide a base64 encoded product image') from None

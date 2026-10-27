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
benchmark=json.loads((model_dir/'benchmark.json').read_text()) if (model_dir/'benchmark.json').exists() else None
manifest=json.loads((model_dir/'model.json').read_text()) if (model_dir/'model.json').exists() else {}
encoder=None if forecast or benchmark else Encoder(str(model_dir),allow_benchmark=manifest.get('benchmarkOnly') is True)
app=FastAPI(docs_url=None,openapi_url=None)
@app.get('/ping')
def ping():return {'status':'UP'}
@app.post('/invocations')
def invoke(body:dict):
    if benchmark is not None:
        rows=benchmark['series']
        if body.get('seriesId'):rows=[row for row in rows if row['id']==body['seriesId']]
        return {'task':benchmark['task'],'frequency':'monthly','benchmarkOnly':True,'productionEligible':False,
                'series':[{'id':row['id'],'historicalHorizon':row['historicalHorizon']} for row in rows]}
    if forecast is not None:
        rows=forecast['products']
        if body.get('productId'):rows=[p for p in rows if p['id']==body['productId']]
        return {'task':'stock_usage_forecast','historyUntil':forecast['historyUntil'],'products':rows}
    try:
        data=base64.b64decode(body['image'],validate=True)
        if len(data)>8*1024*1024:raise ValueError()
        return {'embedding':encoder.encode(data),'modelVersion':encoder.version,'benchmarkOnly':manifest.get('benchmarkOnly') is True}
    except (KeyError,ValueError):raise HTTPException(400,'Provide a base64 encoded product image') from None

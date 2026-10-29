"""Nightly stock-usage forecast with a pretrained time-series model (Chronos-Bolt, zero-shot).

Nothing is trained: the foundation model is used as it is. Each item is back-tested on its own most recent
days (the model only sees the days before them) and its forecast is released only when the back-test error is
small enough. Items that fail, or have too little history, get no forecast; the app then falls back to the
plain reorder-level rule, so the owner always gets an answer.
"""
import hashlib,json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

MODEL_ID='amazon/chronos-bolt-small'
HORIZON=37          # days produced (the service serves the next 30)
MIN_DAYS=21         # fewest usable days before an item is forecast
MAX_CONTEXT=365     # most recent days given to the model
MAX_WAPE=.60        # back-test error above this: the forecast is not released

def validate(data):
    if data.get('schemaVersion')!=1 or data.get('timezone')!='Asia/Colombo' or data.get('historyConfirmed') is not True:
        raise ValueError('Use an owner-confirmed Stocklane forecast snapshot')
    end=date.fromisoformat(data['historyUntil']);rows=data.get('products',[]);ids=set()
    if len(rows)>1000:raise ValueError('Too many products')
    for row in rows:
        if row['id'] in ids:raise ValueError('Duplicate product')
        ids.add(row['id']);start=date.fromisoformat(row['start']);usage=row['usage'];mask=row['inStock']
        if len(usage)!=(end-start).days or len(usage)!=len(mask) or not 0<=len(usage)<=1096:raise ValueError('History must contain complete consecutive days')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1e9 for v in usage):raise ValueError('Invalid usage quantity')
        if any(type(v) is not bool for v in mask):raise ValueError('Invalid availability mask')
    return rows

def filled(values,mask):
    """Days when the item was out of stock show zero use only because nothing was there to give.
    Replace them with the average of the days it was in stock, so a stock-out is not read as no demand."""
    seen=[v for v,m in zip(values,mask) if m]
    if len(seen)<MIN_DAYS:return None
    average=sum(seen)/len(seen)
    return [v if m else average for v,m in zip(values,mask)][-MAX_CONTEXT:]

def holdout_days(length):
    return max(7,min(28,length//4))

def errors(actual,predicted):
    absolute=sum(abs(a-b) for a,b in zip(actual,predicted))
    return {'mae':absolute/len(actual),'wape':absolute/max(sum(actual),1e-9)}

def forecast(data,predict):
    """predict(list_of_series, horizon) -> list_of_forecasts; the same call serves back-test and release."""
    rows=validate(data);end=date.fromisoformat(data['historyUntil']);future=[end+timedelta(days=i) for i in range(HORIZON)]
    result=[];ready=[]
    for row in rows:
        out={k:row[k] for k in ('id','sku','name','unit')};out.update(historyDays=len(row['usage']),daily=[])
        series=filled(row['usage'],row['inStock']) if len(row['usage'])>=MIN_DAYS else None
        if series is None:
            out.update(status='needs_more_history',message='Needs at least %d days of recorded use.'%MIN_DAYS);result.append(out);continue
        if sum(series[-28:])==0:
            out.update(status='not_moving',message='No use in the last four weeks.',daily=[{'date':d.isoformat(),'quantity':0} for d in future]);result.append(out);continue
        out['_series']=series;result.append(out);ready.append(out)
    if ready:
        held=[holdout_days(len(o['_series'])) for o in ready]
        tests=predict([o['_series'][:-h] for o,h in zip(ready,held)],max(held))
        finals=predict([o['_series'] for o in ready],HORIZON)
        for o,h,test,final in zip(ready,held,tests,finals):
            score=errors(o['_series'][-h:],test[:h]);passed=score['wape']<=MAX_WAPE
            o['evaluation']={'holdoutDays':h,'wape':round(score['wape'],4),'mae':round(score['mae'],4),'passed':passed}
            if passed:
                o.update(status='forecast',message='Forecast by %s; back-test error %.0f%%.'%(MODEL_ID.split('/')[1],score['wape']*100),
                         daily=[{'date':d.isoformat(),'quantity':round(max(0.,float(v)),4)} for d,v in zip(future,final)])
            else:o.update(status='unreliable',message='Use is too irregular to forecast reliably; the reorder level is used instead.')
    for o in result:o.pop('_series',None)
    encoded=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    return {'schemaVersion':1,'task':'stock_usage_forecast','timezone':'Asia/Colombo','generatedAt':datetime.now(timezone.utc).isoformat(),'historyUntil':end.isoformat(),
            'datasetSha256':hashlib.sha256(encoded).hexdigest(),'model':{'name':MODEL_ID,'type':'pretrained, zero-shot'},'products':result,
            'limitations':['Recorded outgoing usage, not unobserved demand.','Days out of stock are filled with the in-stock average.','No automatic stock changes or purchase orders.']}

def load_predictor(model_id=MODEL_ID):
    """Chronos-Bolt on CPU; weights come from the official Hugging Face repository (safetensors)."""
    import torch
    from chronos import BaseChronosPipeline
    pipeline=BaseChronosPipeline.from_pretrained(model_id,device_map='cpu',torch_dtype=torch.float32)
    def predict(series,horizon):
        outputs=[]
        for start in range(0,len(series),64):
            quantiles,_=pipeline.predict_quantiles(context=[torch.tensor(s,dtype=torch.float32) for s in series[start:start+64]],prediction_length=horizon,quantile_levels=[.5])
            outputs+=[[float(v) for v in q[:,0]] for q in quantiles]
        return outputs
    return predict

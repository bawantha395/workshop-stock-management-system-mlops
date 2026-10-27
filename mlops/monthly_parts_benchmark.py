"""Real monthly car-parts sales benchmark; separate from workshop daily demand.

Chronological validation selects Ridge alpha and baseline method. The final
twelve months are held out for evaluation. No missing values are filled, no
historical dates are shifted, and no monthly count becomes fabricated daily use.
"""
import hashlib
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge


def month(start,offset):
    value=start.year*12+start.month-1+offset
    return date(value//12,value%12+1,1)


def validate(data):
    if (data.get('schemaVersion')!=1 or data.get('frequency')!='monthly'
            or data.get('benchmarkOnly') is not True or data.get('syntheticData') is not False):
        raise ValueError('Use the explicitly marked real monthly benchmark snapshot')
    seen=set()
    if not 3<=len(data['series'])<=256:raise ValueError('Use 3 to 256 benchmark series')
    for row in data['series']:
        if row['id'] in seen:raise ValueError('Duplicate monthly series')
        seen.add(row['id']);start=date.fromisoformat(row['start']);values=row['values']
        if start.day!=1 or not 48<=len(values)<=120:raise ValueError('Use complete monthly histories of at least 48 months')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):
            raise ValueError('Missing or invalid monthly sales; do not fill unknowns with zeros')
    return data['series']


def features(start,index,past):
    return ([float(month(start,index).month==m) for m in range(1,13)]
        +[past[-1],past[-3],past[-12],sum(past[-3:])/3,sum(past[-6:])/6,
          sum(past[-12:])/12,sum(v==0 for v in past[-12:])/12])


def fit(start,values,alpha):
    x=[features(start,i,values[:i]) for i in range(12,len(values))]
    return Ridge(alpha=alpha).fit(np.asarray(x),np.asarray(values[12:]))


def ridge_forecast(model,start,values,horizon):
    past=list(values);result=[]
    for _ in range(horizon):
        predicted=max(0,float(model.predict([features(start,len(past),past)])[0]))
        past.append(predicted);result.append(predicted)
    return result


def croston_sba(values,alpha=.1):
    first=next((i for i,v in enumerate(values) if v>0),None)
    if first is None:return 0.0
    demand=float(values[first]);interval=float(first+1);gap=1
    for value in values[first+1:]:
        if value>0:
            demand=alpha*value+(1-alpha)*demand
            interval=alpha*gap+(1-alpha)*interval;gap=1
        else:gap+=1
    return (1-alpha/2)*demand/interval


def baseline(values,horizon,method):
    if method=='croston_sba':return [croston_sba(values)]*horizon
    if method=='recent_mean':return [sum(values[-12:])/12]*horizon
    past=list(values);result=[]
    for _ in range(horizon):
        value=past[-12];past.append(value);result.append(value)
    return result


def errors(actual,predicted):
    total=sum(abs(a-p) for a,p in zip(actual,predicted));quantity=sum(actual)
    return {'mae':total/len(actual),'wape':total/quantity if quantity>0 else None}


def train(data):
    rows=validate(data);outputs=[];all_actual=[];all_model=[];all_baseline=[]
    for row in rows:
        start=date.fromisoformat(row['start']);values=row['values']
        split=len(values)-12;selection=split-6
        candidates=[]
        for alpha in (.1,1.,10.,100.):
            model=fit(start,values[:selection],alpha)
            predicted=ridge_forecast(model,start,values[:selection],6)
            candidates.append((errors(values[selection:split],predicted)['mae'],alpha))
        alpha=min(candidates)[1]
        method=min((errors(values[selection:split],baseline(values[:selection],6,m))['mae'],m)
                   for m in ('seasonal_naive','croston_sba','recent_mean'))[1]
        model=fit(start,values[:split],alpha)
        predicted=ridge_forecast(model,start,values[:split],12)
        control=baseline(values[:split],12,method)
        score=errors(values[split:],predicted);comparison=errors(values[split:],control)
        passed=(score['wape'] is not None and score['wape']<=.60
                and comparison['mae']>1e-9 and score['mae']<=comparison['mae']*.95)
        final=fit(start,values,alpha)
        future=ridge_forecast(final,start,values,3) if passed else baseline(values,3,method)
        outputs.append({'id':row['id'],'alpha':alpha,'baselineMethod':method,
            'trainingUntil':str(month(start,selection-1)),'validationMonths':6,'testMonths':12,
            'testFrom':str(month(start,split)),'testUntil':str(month(start,len(values)-1)),
            'evaluation':{'model':score,'baseline':comparison,'qualityGatePassed':passed},
            'recommendation':'ridge' if passed else method,
            'candidate':{'coefficients':final.coef_.tolist(),'intercept':float(final.intercept_)},
            'historicalHorizon':[{'month':str(month(start,len(values)+i)),'sales':round(v,4)} for i,v in enumerate(future)]})
        all_actual.extend(values[split:]);all_model.extend(predicted);all_baseline.extend(control)
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    model_error=errors(all_actual,all_model);baseline_error=errors(all_actual,all_baseline)
    metrics={'task':'monthly_car_parts_benchmark','frequency':'monthly','syntheticData':False,
        'benchmarkOnly':True,'productionEligible':False,'seriesCount':len(rows),
        'acceptedSeries':sum(r['evaluation']['qualityGatePassed'] for r in outputs),
        'meanModelMAE':model_error['mae'],'meanBaselineMAE':baseline_error['mae'],
        'modelWAPE':model_error['wape'],'baselineWAPE':baseline_error['wape'],
        'qualityGatePassed':model_error['wape'] is not None and model_error['wape']<=.60
            and baseline_error['mae']>1e-9 and model_error['mae']<=baseline_error['mae']*.95,
        'datasetSha256':digest,'source':data['source'],'sourceSha256':data['sourceSha256'],
        'limitations':['Historical anonymous monthly series from another business.',
            'No Friday/daily pattern or current workshop stock is inferred.',
            'Missing-value series were excluded; no unknown sales were replaced by zero.']}
    return {'schemaVersion':1,**metrics,'series':outputs},metrics


def main(dataset='/opt/ml/input/data/dataset',output='/opt/ml/model'):
    data=json.loads((Path(dataset)/'history.json').read_text())
    artifact,metrics=train(data)
    target=Path(output);target.mkdir(parents=True,exist_ok=True)
    (target/'benchmark.json').write_text(json.dumps(artifact,allow_nan=False))
    (target/'metrics.json').write_text(json.dumps(metrics,allow_nan=False))
    print(json.dumps(metrics,allow_nan=False),flush=True)


if __name__=='__main__':main()

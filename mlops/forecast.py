"""Daily usage forecasting, chronological validation and recursive held-out testing."""
import hashlib,json,math
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
MIN_ML_DAYS=112
HORIZON=37

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

def eligible(row):
    return (len(row['usage'])>=MIN_ML_DAYS and all(row['inStock'][-42:])
            and sum(all(row['inStock'][i-28:i+1]) for i in range(28,len(row['usage'])-42))>=40
            and sum(v>0 for v in row['usage'])>=20)

def baseline(values,dates,future):
    recent=list(zip(dates[-28:],values[-28:]))
    return [sum(v for d,v in recent if d.weekday()==day.weekday())/max(1,sum(d.weekday()==day.weekday() for d,_ in recent)) for day in future]

def features(day,past,annual):
    values=[float(day.weekday()==i) for i in range(7)]+[past[-7],sum(past[-7:])/7,sum(past[-28:])/28]
    if annual:
        angle=2*math.pi*(day.timetuple().tm_yday-1)/365.25
        values += [float(day.month==month) for month in range(1,13)]+[math.sin(angle),math.cos(angle)]
    return values

def fit(values,dates,mask,alpha,annual):
    from sklearn.linear_model import Ridge
    indexes=[i for i in range(28,len(values)) if all(mask[max(0,i-28):i+1])]
    if len(indexes)<40:raise ValueError('Too few uncensored training windows')
    model=Ridge(alpha=alpha)
    model.fit([features(dates[i],values[:i],annual) for i in indexes],[values[i] for i in indexes]);return model

def rollout(model,values,future,annual):
    history=list(values);maximum=max(1.,max(values[-90:])*3);result=[]
    for day in future:
        predicted=max(0.,min(maximum,float(model.predict([features(day,history,annual)])[0])))
        history.append(predicted);result.append(predicted)
    return result

def errors(actual,predicted):
    absolute=sum(abs(a-b) for a,b in zip(actual,predicted))
    return {'mae':absolute/len(actual),'wape':absolute/max(sum(actual),1e-9)}

def train(data):
    rows=validate(data);end=date.fromisoformat(data['historyUntil']);future=[end+timedelta(days=i) for i in range(HORIZON)];result=[]
    for row in rows:
        values,mask=row['usage'],row['inStock'];dates=[date.fromisoformat(row['start'])+timedelta(days=i) for i in range(len(values))]
        output={k:row[k] for k in ('id','sku','name','unit')}
        output.update(historyDays=len(values),status='insufficient_history',message='Need 28 complete confirmed days with recent stock availability.',daily=[])
        if len(values)<28 or not all(mask[-28:]):result.append(output);continue
        predictions=baseline(values,dates,future);output.update(status='weekday_baseline',message='Four-week weekday average; not an accepted ML model.')
        if eligible(row) and all(mask[-42:]):
            annual=len(values)-42>=730;split=len(values)-28
            try:
                candidates=[]
                for alpha in (.1,1.,10.,100.):
                    model=fit(values[:split-14],dates[:split-14],mask[:split-14],alpha,annual)
                    pred=rollout(model,values[:split-14],dates[split-14:split],annual)
                    candidates.append((errors(values[split-14:split],pred)['mae'],alpha))
                alpha=min(candidates)[1];model=fit(values[:split],dates[:split],mask[:split],alpha,annual)
                predicted=rollout(model,values[:split],dates[split:],annual)
                test=errors(values[split:],predicted);control=errors(values[split:],baseline(values[:split],dates[:split],dates[split:]))
                passed=test['wape']<=.60 and test['mae']<=control['mae']*.95 and control['mae']>1e-9
                output['evaluation']={'testDays':28,'ml':test,'baseline':control,'qualityGatePassed':passed,'annualFeatures':annual,'alpha':alpha}
                if passed:
                    model=fit(values,dates,mask,alpha,annual);predictions=rollout(model,values,future,annual)
                    output.update(status='trained_ml',message='Ridge model passed the held-out weekday-baseline gate.',model={'coefficients':model.coef_.tolist(),'intercept':float(model.intercept_),'annualFeatures':annual,'alpha':alpha})
                else:output['message']='ML did not beat the held-out weekday baseline by 5%; baseline retained.'
            except ValueError:output['message']='Insufficient uncensored windows for ML; weekday baseline retained.'
        output['daily']=[{'date':d.isoformat(),'quantity':round(v,4)} for d,v in zip(future,predictions)];result.append(output)
    encoded=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    return {'schemaVersion':1,'task':'stock_usage_forecast','timezone':'Asia/Colombo','trainedAt':datetime.now(timezone.utc).isoformat(),'historyUntil':end.isoformat(),'datasetSha256':hashlib.sha256(encoded).hexdigest(),'products':result,'qualityGatePassed':any(r['status']=='trained_ml' for r in result),'limitations':['Recorded outgoing usage, not unobserved demand.','End-of-day zero stock is censored; intraday stock-outs can remain undetected.','No automatic stock changes or purchase orders.']}

def main(dataset='/opt/ml/input/data/dataset',output='/opt/ml/model'):
    result=train(json.loads((Path(dataset)/'history.json').read_text()));Path(output).mkdir(parents=True,exist_ok=True)
    (Path(output)/'forecast.json').write_text(json.dumps(result,allow_nan=False))
    print(json.dumps({'task':result['task'],'qualityGatePassed':result['qualityGatePassed'],'counts':{s:sum(p['status']==s for p in result['products']) for s in ('trained_ml','weekday_baseline','insufficient_history')}}))
if __name__=='__main__':main()

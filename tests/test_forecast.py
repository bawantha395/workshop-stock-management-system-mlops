"""Forecast engine tests use a fake predictor; the real Chronos model runs in the nightly workflow."""
import hashlib,importlib.util,io,json,sys,time
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mlops'))
import forecast as engine
from forecast import forecast,validate

def snapshot(days=60,usage=None,mask=None):
    end=date(2026,10,26);start=end-timedelta(days=days)
    values=usage if usage is not None else [3*(2 if (start+timedelta(days=i)).weekday()==4 else 1) for i in range(days)]
    return {'schemaVersion':1,'timezone':'Asia/Colombo','historyConfirmed':True,'historyUntil':str(end),'asOf':datetime.now(timezone.utc).isoformat(),
            'products':[{'id':'p1','sku':'FILTER-1','name':'Filter','unit':'UNIT','start':str(start),'usage':values,'inStock':mask if mask is not None else [True]*days}]}

def weekly(series,horizon):
    """Stand-in for the model: repeat the last seven days."""
    return [[s[len(s)-7+(i%7)] for i in range(horizon)] for s in series]

def wrong(series,horizon):
    return [[100.]*horizon for _ in series]

def test_too_little_history_gets_no_forecast():
    row=forecast(snapshot(8),weekly)['products'][0]
    assert row['status']=='needs_more_history' and row['daily']==[]

def test_regular_use_is_forecast_for_37_days_and_keeps_the_friday_peak():
    result=forecast(snapshot(60),weekly);row=result['products'][0]
    assert row['status']=='forecast' and len(row['daily'])==37 and row['evaluation']['passed'] and row['evaluation']['wape']==0
    for day in row['daily']:assert day['quantity']==(6 if date.fromisoformat(day['date']).weekday()==4 else 3)
    assert result['model']['name']=='amazon/chronos-bolt-small'

def test_a_forecast_that_misses_the_back_test_is_not_released():
    row=forecast(snapshot(60),wrong)['products'][0]
    assert row['status']=='unreliable' and row['daily']==[] and not row['evaluation']['passed']

def test_model_never_sees_the_days_it_is_tested_on():
    seen=[]
    def spy(series,horizon):seen.append([len(s) for s in series]);return weekly(series,horizon)
    forecast(snapshot(60),spy)
    assert seen[0]==[60-engine.holdout_days(60)] and seen[1]==[60]

def test_item_with_no_recent_use_is_not_sent_to_the_model():
    calls=[]
    def spy(series,horizon):calls.append(series);return weekly(series,horizon)
    row=forecast(snapshot(60,usage=[5]*30+[0]*30),spy)['products'][0]
    assert row['status']=='not_moving' and all(d['quantity']==0 for d in row['daily']) and calls==[]

def test_days_out_of_stock_are_not_read_as_zero_demand():
    mask=[True]*50+[False]*10;usage=[4]*50+[0]*10;seen=[]
    def spy(series,horizon):seen.append(series[0]);return weekly(series,horizon)
    forecast(snapshot(60,usage=usage,mask=mask),spy)
    assert min(seen[-1])==4

def test_item_that_was_never_in_stock_gets_no_forecast():
    row=forecast(snapshot(60,mask=[False]*60),weekly)['products'][0]
    assert row['status']=='needs_more_history'

@pytest.mark.parametrize('change',[lambda d:d.update(historyConfirmed=False),lambda d:d['products'][0]['usage'].append(1),lambda d:d['products'][0]['usage'].__setitem__(0,float('nan')),lambda d:d['products'][0]['inStock'].__setitem__(0,1)])
def test_malformed_snapshots_rejected(change):
    data=snapshot();change(data)
    with pytest.raises(ValueError):validate(data)

def module():
    security_spec=importlib.util.spec_from_file_location('shared_security',ROOT/'services/vision/app/security.py');security=importlib.util.module_from_spec(security_spec);security_spec.loader.exec_module(security);sys.modules['shared_security']=security
    spec=importlib.util.spec_from_file_location('stock_forecast_service',ROOT/'services/forecast/app/main.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

ITEM={'id':'p1','sku':'FILTER-1','name':'Filter','unit':'UNIT','quantity':10,'reorder_level':5}

def test_projection_uses_live_stock_and_rounds_sealed_units():
    m=module();row=m.projection(forecast(snapshot(60),weekly),[ITEM],date(2026,10,26))['products'][0]
    assert row['status']=='forecast' and row['next7']==24 and row['suggestedTopUp7']==14 and row['reorderLevel']==5

def test_items_without_a_forecast_are_still_listed_with_their_reorder_level():
    m=module();result=m.projection(forecast(snapshot(8),weekly),[ITEM],date(2026,10,26))
    assert result['forecast']=='fresh' and result['products'][0]['status']=='needs_more_history' and result['products'][0]['reorderLevel']==5
    assert 'next7' not in result['products'][0]

def test_stale_forecast_is_ignored_but_items_remain_listed():
    m=module();result=m.projection(forecast(snapshot(60),weekly),[ITEM],date(2026,11,4))
    assert result['forecast']=='stale' and result['products'][0]['status']=='no_forecast'

def test_forecast_owner_auth_and_first_day_without_artifact(monkeypatch):
    from fastapi.testclient import TestClient
    from botocore.exceptions import ClientError
    m=module();s3=Mock();s3.get_object.side_effect=ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
    monkeypatch.setattr(m.httpx,'get',lambda *a,**kw:SimpleNamespace(raise_for_status=lambda:None,json=lambda:[ITEM]))
    app=m.create_app(m.Settings(auth_mode='local',environment='local',model_bucket='owned'),s3)
    with TestClient(app) as client:
        assert client.get('/api/forecast',headers={'X-Demo-User':'mechanic'}).status_code==403
        body=client.get('/api/forecast').json()
        assert body['status']=='ready' and body['forecast']=='not_trained' and body['products'][0]['status']=='no_forecast' and body['products'][0]['reorderLevel']==5
        assert client.get('/health/ready').status_code==200
        assert client.get('/metrics').status_code==401

def test_forecast_cognito_mechanic_cannot_read_owner_forecasts(monkeypatch):
    m=module();security=m.Security(m.Settings(cognito_client_ids='web',cognito_issuer='https://issuer'))
    security.keys={'keys':[]};security.expires=time.monotonic()+100
    monkeypatch.setattr(sys.modules['shared_security'].jwt,'decode',lambda *a,**kw:{'token_use':'access','client_id':'web','cognito:groups':['MECHANIC'],'sub':'mechanic'})
    with pytest.raises(m.HTTPException) as denied:
        security.staff(SimpleNamespace(headers={'Authorization':'Bearer token'}),owner=True)
    assert denied.value.status_code==403

def runner(monkeypatch,tmp_path,data,current=None):
    import run_forecast
    raw=json.dumps(data).encode();pointer={'key':'forecast/datasets/abc/history.json','sha256':hashlib.sha256(raw).hexdigest()}
    from botocore.exceptions import ClientError
    missing=ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
    s3=Mock();s3.get_object.side_effect=[{'Body':io.BytesIO(json.dumps(pointer).encode())},{'Body':io.BytesIO(raw)},missing]
    sts=Mock();sts.get_caller_identity.return_value={'Account':'123'}
    monkeypatch.setattr(run_forecast.boto3,'client',lambda name,**kw:{'s3':s3,'sts':sts}[name]);monkeypatch.chdir(tmp_path)
    return run_forecast,s3

def test_nightly_run_publishes_the_forecast_without_any_training_job(monkeypatch,tmp_path):
    run_forecast,s3=runner(monkeypatch,tmp_path,snapshot(60))
    result=run_forecast.execute({'region':'ap-southeast-2','model_bucket':'owned','account_id':'123'},publish=True,predict=weekly)
    assert result['published'] and result['counts']['forecast']==1
    assert any(call.kwargs['Key']=='forecast/current.json' for call in s3.put_object.call_args_list)

def test_nightly_run_without_publish_only_stores_the_release(monkeypatch,tmp_path):
    run_forecast,s3=runner(monkeypatch,tmp_path,snapshot(60))
    run_forecast.execute({'region':'ap-southeast-2','model_bucket':'owned','account_id':'123'},publish=False,predict=weekly)
    assert not any(call.kwargs['Key']=='forecast/current.json' for call in s3.put_object.call_args_list)

def test_no_exported_history_yet_is_reported_not_failed(monkeypatch,tmp_path):
    import run_forecast
    from botocore.exceptions import ClientError
    s3=Mock();s3.get_object.side_effect=ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
    sts=Mock();sts.get_caller_identity.return_value={'Account':'123'}
    monkeypatch.setattr(run_forecast.boto3,'client',lambda name,**kw:{'s3':s3,'sts':sts}[name]);monkeypatch.chdir(tmp_path)
    assert run_forecast.execute({'region':'r','model_bucket':'owned','account_id':'123'})['status']=='no_history'

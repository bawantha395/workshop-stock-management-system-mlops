"""Synthetic histories exercise correctness only; they are never shipped as workshop data."""
import importlib.util,io,json,sys
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mlops'))
from forecast import train,validate,eligible,features

def snapshot(days=160,trend=False):
    end=date(2026,10,26);start=end-timedelta(days=days)
    usage=[(3+(i*.12 if trend else 0))*(2 if (start+timedelta(days=i)).weekday()==4 else 1) for i in range(days)]
    return {'schemaVersion':1,'timezone':'Asia/Colombo','historyConfirmed':True,'historyUntil':str(end),'asOf':datetime.now(timezone.utc).isoformat(),'products':[{'id':'p1','sku':'FILTER-1','name':'Filter','unit':'UNIT','start':str(start),'usage':usage,'inStock':[True]*days}]}

def test_insufficient_history_does_not_invent_predictions():
    row=train(snapshot(8))['products'][0]
    assert row['status']=='insufficient_history' and row['daily']==[]
    assert not eligible(snapshot(8)['products'][0])

def test_weekday_baseline_preserves_friday_pattern_and_has_37_days():
    row=train(snapshot(35))['products'][0]
    assert row['status']=='weekday_baseline' and len(row['daily'])==37
    for day in row['daily']:
        assert day['quantity']==(6 if date.fromisoformat(day['date']).weekday()==4 else 3)

def test_ml_is_gated_against_independent_baseline():
    result=train(snapshot(200,trend=True));row=result['products'][0]
    assert row['evaluation']['testDays']==28
    assert row['status']=='trained_ml'
    assert row['evaluation']['ml']['mae']<=row['evaluation']['baseline']['mae']*.95
    assert 'model' in row
    assert row['evaluation']['annualFeatures'] is False
    assert all(d['quantity']>=0 for d in row['daily'])

def test_perfect_weekly_baseline_is_not_replaced_by_ml():
    row=train(snapshot())['products'][0]
    assert row['status']=='weekday_baseline' and not row['evaluation']['qualityGatePassed']

def test_test_period_does_not_choose_hyperparameters():
    data=snapshot(200,True);first=train(data)['products'][0]
    data['products'][0]['usage'][-28:]=[50]*28
    second=train(data)['products'][0]
    assert first['evaluation']['alpha']==second['evaluation']['alpha']

def test_censored_recent_stock_prevents_misleading_zero_demand():
    data=snapshot();data['products'][0]['inStock'][-1]=False
    assert train(data)['products'][0]['status']=='insufficient_history'

@pytest.mark.parametrize('change',[lambda d:d.update(historyConfirmed=False),lambda d:d['products'][0]['usage'].append(1),lambda d:d['products'][0]['usage'].__setitem__(0,float('nan')),lambda d:d['products'][0]['inStock'].__setitem__(0,1)])
def test_malformed_snapshots_rejected(change):
    data=snapshot();change(data)
    with pytest.raises(ValueError):validate(data)

def module():
    security_spec=importlib.util.spec_from_file_location('shared_security',ROOT/'services/vision/app/security.py');security=importlib.util.module_from_spec(security_spec);security_spec.loader.exec_module(security);sys.modules['shared_security']=security
    spec=importlib.util.spec_from_file_location('stock_forecast_service',ROOT/'services/forecast/app/main.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_projection_uses_live_stock_and_rounds_sealed_units():
    m=module();result=train(snapshot(35));row=m.projection(result,[{'id':'p1','sku':'FILTER-1','name':'Filter','unit':'UNIT','quantity':10}],date(2026,10,26))['products'][0]
    assert row['next7']==24 and row['suggestedTopUp7']==14

def test_stale_forecasts_do_not_recommend_reorders():
    m=module();assert m.projection(train(snapshot(35)),[],date(2026,11,4))['status']=='stale'

def test_forecast_owner_auth_and_missing_artifact():
    from fastapi.testclient import TestClient
    from botocore.exceptions import ClientError
    m=module();s3=Mock();s3.get_object.side_effect=ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
    app=m.create_app(m.Settings(auth_mode='local',environment='local',model_bucket='owned'),s3)
    with TestClient(app) as client:
        assert client.get('/api/forecast',headers={'X-Demo-User':'mechanic'}).status_code==403
        r=client.get('/api/forecast');assert r.status_code==200 and r.json()['status']=='not_trained'
        assert client.get('/health/ready').status_code==200
        assert client.get('/metrics').status_code==401

def test_not_enough_data_skips_paid_sagemaker(monkeypatch,tmp_path):
    import run_forecast
    data=snapshot(4);raw=json.dumps(data).encode();import hashlib
    pointer={'key':'forecast/datasets/abc/history.json','sha256':hashlib.sha256(raw).hexdigest()}
    s3=Mock();s3.get_object.side_effect=[{'Body':io.BytesIO(json.dumps(pointer).encode())},{'Body':io.BytesIO(raw)}]
    sm=Mock();sts=Mock();sts.get_caller_identity.return_value={'Account':'123'}
    monkeypatch.setattr(run_forecast.boto3,'client',lambda name,**kw:{'s3':s3,'sagemaker':sm,'sts':sts}[name]);monkeypatch.chdir(tmp_path)
    result=run_forecast.execute({'region':'ap-southeast-2','model_bucket':'owned','account_id':'123'})
    sm.create_training_job.assert_not_called();assert result['counts']['insufficient_history']==1 and result['published'] is False

def test_annual_features_require_two_years_before_validation_and_test():
    short=train(snapshot(750))['products'][0]
    long=train(snapshot(780))['products'][0]
    assert short['evaluation']['annualFeatures'] is False
    assert long['evaluation']['annualFeatures'] is True

def test_forecast_cognito_mechanic_cannot_read_owner_forecasts(monkeypatch):
    from types import SimpleNamespace
    import time
    m=module();security=m.Security(m.Settings(cognito_client_ids='web',cognito_issuer='https://issuer'))
    security.keys={'keys':[]};security.expires=time.monotonic()+100
    monkeypatch.setattr(sys.modules['shared_security'].jwt,'decode',lambda *a,**kw:{'token_use':'access','client_id':'web','cognito:groups':['MECHANIC'],'sub':'mechanic'})
    with pytest.raises(m.HTTPException) as denied:
        security.staff(SimpleNamespace(headers={'Authorization':'Bearer token'}),owner=True)
    assert denied.value.status_code==403

def test_sagemaker_train_gate_registry_and_publish_are_one_run(monkeypatch,tmp_path):
    import run_forecast,hashlib,tarfile
    data=snapshot(200,True);raw=json.dumps(data).encode();pointer={'key':'forecast/datasets/abc/history.json','sha256':hashlib.sha256(raw).hexdigest()}
    artifact=json.dumps(train(data)).encode();buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as tar:
        entry=tarfile.TarInfo('forecast.json');entry.size=len(artifact);tar.addfile(entry,io.BytesIO(artifact))
    from botocore.exceptions import ClientError
    s3=Mock();s3.get_object.side_effect=[{'Body':io.BytesIO(json.dumps(pointer).encode())},{'Body':io.BytesIO(raw)},{'Body':io.BytesIO(buffer.getvalue())},ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')]
    sm=Mock();sm.describe_training_job.return_value={'TrainingJobStatus':'Completed','ModelArtifacts':{'S3ModelArtifacts':'s3://owned/forecast/training/job/output/model.tar.gz'}}
    sm.create_model_package.return_value={'ModelPackageArn':'arn:aws:sagemaker:ap-southeast-2:123:model-package/stock-forecast/1'}
    sts=Mock();sts.get_caller_identity.return_value={'Account':'123'}
    monkeypatch.setattr(run_forecast.boto3,'client',lambda name,**kw:{'s3':s3,'sagemaker':sm,'sts':sts}[name]);monkeypatch.chdir(tmp_path)
    folder=tmp_path/'deploy/kubernetes/apps/overlays/dev';folder.mkdir(parents=True);(folder/'images.json').write_text(json.dumps({'ml-training':'123.dkr.ecr.ap-southeast-2.amazonaws.com/training@sha256:'+'a'*64}))
    result=run_forecast.execute({'region':'ap-southeast-2','model_bucket':'owned','account_id':'123','environment':'dev','name':'stock','training_role_arn':'training-role','forecast_model_package_group':'stock-forecast'},publish=True)
    args=sm.create_training_job.call_args.kwargs
    assert args['HyperParameters']=={'task':'stock_forecast'} and args['EnableNetworkIsolation'] is True
    assert args['StoppingCondition']=={'MaxRuntimeInSeconds':600}
    assert sm.create_model_package.call_args.kwargs['ModelApprovalStatus']=='Approved'
    assert result['published'] and result['counts']['trained_ml']==1
    assert any(call.kwargs['Key']=='forecast/current.json' for call in s3.put_object.call_args_list)

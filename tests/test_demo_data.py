"""Synthetic data practices the lifecycle; it is not production-quality evidence."""
import csv
import hashlib
import io
import json
import random
import sys
import tarfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mlops'))
from dataset import validate_manifest
from forecast import eligible,train,validate
from generate_demo_data import generate,history,illustration
from upload_dataset import upload
from review_model import review
from app.encoder import Encoder


def test_history_scenarios_cover_cold_start_baselines_and_trainable_data():
    end=date(2026,10,27)
    cold=history('cold_start',as_of=end);weekday=history('weekday_baseline',as_of=end)
    seasonal=history('seasonal_mixed',as_of=end)
    assert len(validate(cold))==9 and not any(eligible(row) for row in cold['products'])
    assert len(validate(weekday))==12 and all(len(row['usage'])==56 for row in weekday['products'])
    assert all(row['status']=='weekday_baseline' for row in train(weekday)['products'])
    assert len(validate(seasonal))==24
    assert len(seasonal['products'][0]['usage'])==1095
    assert sum(eligible(row) for row in seasonal['products'])>0
    assert not eligible(seasonal['products'][20]) and not eligible(seasonal['products'][22])
    assert all(data['synthetic'] is True for data in (cold,weekday,seasonal))


def test_synthetic_seasonal_profile_has_friday_and_december_peaks():
    row=history('seasonal_mixed',as_of=date(2026,10,27))['products'][2]
    start=date.fromisoformat(row['start'])
    from datetime import timedelta
    days=[start+timedelta(days=i) for i in range(len(row['usage']))]
    def mean(predicate):
        values=[v for day,v in zip(days,row['usage']) if predicate(day)]
        return sum(values)/len(values)
    assert mean(lambda d:d.weekday()==4)>mean(lambda d:d.weekday()==2)*1.5
    assert mean(lambda d:d.month==12)>mean(lambda d:d.month==11)*1.4


def test_seed_reproducibility_and_variation_are_explicit():
    end=date(2026,10,27)
    assert history('seasonal_mixed',31,end)==history('seasonal_mixed',31,end)
    assert history('seasonal_mixed',31,end)!=history('seasonal_mixed',32,end)
    assert illustration(2,random.Random(31)).tobytes()==illustration(2,random.Random(31)).tobytes()
    assert illustration(2,random.Random(31)).tobytes()!=illustration(2,random.Random(32)).tobytes()


@pytest.fixture(scope='module')
def fixtures(tmp_path_factory):
    path=tmp_path_factory.mktemp('demo-data')
    generate(path,20261027,date(2026,10,27))
    return path


def test_photo_splits_and_checksums_have_no_duplicate_image_bytes(fixtures):
    root=fixtures/'photos'
    rows=list(csv.DictReader((root/'manifest.csv').open()));validate_manifest(rows)
    assert len(rows)==216 and len({row['sku'] for row in rows})==12
    assert all(sum(r['split']==name for r in rows)==72 for name in ('train','validation','test'))
    checks=json.loads((root/'dataset-checksums.json').read_text())
    hashes=[hashlib.sha256((root/r['file']).read_bytes()).hexdigest() for r in rows]
    assert len(set(hashes))==216
    assert all(checks[row['file']]==digest for row,digest in zip(rows,hashes))


def test_synthetic_photos_cannot_use_the_real_workshop_upload_or_training_path(fixtures,tmp_path):
    s3=Mock()
    with pytest.raises(ValueError,match='demo workflow'):upload(fixtures/'photos','owned','ap-southeast-2',s3)
    s3.put_object.assert_not_called()
    from train import train as photo_train
    with pytest.raises(ValueError,match='production candidate'):
        photo_train(fixtures/'photos','unused',tmp_path)


def test_demo_uploads_are_isolated_from_live_dataset_and_release_prefixes(fixtures):
    import run_demo_training as demo
    class S3:
        def __init__(self):self.keys=[]
        def put_object(self,**kwargs):self.keys.append(kwargs['Key'])
    s3=S3();uri=demo.upload_demo(fixtures,'owned',s3)
    assert uri.startswith('s3://owned/demo/datasets/')
    assert all(key.startswith('demo/datasets/') for key in s3.keys)
    assert not any('forecast/current.json' in key or key.startswith('releases/') for key in s3.keys)


def test_demo_training_registers_only_a_marked_pending_package(monkeypatch):
    import run_demo_training as demo
    content=json.dumps({'syntheticData':True,'qualityGatePassed':True,'products':[{'status':'trained_ml'}]}).encode()
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        entry=tarfile.TarInfo('forecast.json');entry.size=len(content);archive.addfile(entry,io.BytesIO(content))
    class S3:
        def get_object(self,**kwargs):return {'Body':io.BytesIO(buffer.getvalue())}
        def put_object(self,**kwargs):assert kwargs['Key'].startswith('demo/')
    sm=Mock();sm.create_model_package.return_value={'ModelPackageArn':'demo-package'}
    monkeypatch.setattr(demo,'wait_for_job',lambda *args:{'ModelArtifacts':{'S3ModelArtifacts':'s3://owned/demo/training/job/output/model.tar.gz'}})
    c={'name':'stocklane-dev','model_bucket':'owned','training_role_arn':'training-role',
       'forecast_model_package_group':'stocklane-dev-stock-forecast'}
    result=demo.train_one('forecast',c,sm,S3(),'image@sha256:'+'a'*64,'s3://owned/demo/datasets/test/',None)
    request=sm.create_training_job.call_args.kwargs
    assert request['HyperParameters']['demo_mode']=='true'
    assert request['StoppingCondition']['MaxRuntimeInSeconds']==600
    assert request['EnableNetworkIsolation'] is True
    package=sm.create_model_package.call_args.kwargs
    assert package['ModelApprovalStatus']=='PendingManualApproval'
    assert package['CustomerMetadataProperties']['syntheticData']=='true'
    assert result['productionEligible'] is False


def test_demo_artifact_cannot_point_to_the_live_training_prefix():
    import run_demo_training as demo
    s3=Mock()
    with pytest.raises(ValueError,match='isolated prefix'):
        demo.read_artifact(s3,'owned','s3://owned/training/prod/model.tar.gz','metrics.json')
    s3.get_object.assert_not_called()


def test_registry_cannot_approve_a_synthetic_demo_for_production():
    config={'region':'ap-southeast-2','account_id':'123456789012','model_package_group':'stocklane-visual-sku'}
    sm=Mock();sm.describe_model_package.return_value={'ModelPackageStatus':'Completed',
        'CustomerMetadataProperties':{'syntheticData':'true'}}
    arn='arn:aws:sagemaker:ap-southeast-2:123456789012:model-package/stocklane-visual-sku/1'
    with pytest.raises(ValueError,match='cannot be approved'):review(arn,'Approved',config,sm)
    sm.update_model_package.assert_not_called()


def test_live_vision_cannot_load_a_demo_encoder(tmp_path):
    (tmp_path/'model.json').write_text(json.dumps({'syntheticData':True}))
    with pytest.raises(RuntimeError,match='live workshop'):Encoder(tmp_path)


def test_live_forecast_cannot_serve_synthetic_projections():
    from test_forecast import module
    model=train(history('weekday_baseline',as_of=date(2026,10,27)))
    with pytest.raises(ValueError,match='Synthetic demo'):module().projection(model,[],date(2026,10,27))


def test_production_forecast_runner_refuses_dummy_data_before_training_or_publication(monkeypatch):
    import run_forecast
    data=history('seasonal_mixed',as_of=date(2026,10,27));raw=json.dumps(data).encode()
    pointer={'key':'forecast/datasets/example/history.json','sha256':hashlib.sha256(raw).hexdigest()}
    s3=Mock();s3.get_object.side_effect=[{'Body':io.BytesIO(json.dumps(pointer).encode())},{'Body':io.BytesIO(raw)}]
    sm=Mock();sts=Mock();sts.get_caller_identity.return_value={'Account':'123456789012'}
    monkeypatch.setattr(run_forecast.boto3,'client',lambda name,**kwargs:{'s3':s3,'sagemaker':sm,'sts':sts}[name])
    with pytest.raises(ValueError,match='live forecast'):
        run_forecast.execute({'region':'ap-southeast-2','model_bucket':'owned','account_id':'123456789012'},True)
    sm.create_training_job.assert_not_called();s3.put_object.assert_not_called()

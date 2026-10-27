"""Real-data provenance, chronological evaluation and benchmark isolation contracts."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
from unittest.mock import Mock

import botocore.session
from botocore.exceptions import ClientError
from botocore.validate import validate_parameters
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mlops'))
sys.path.insert(0,str(ROOT/'scripts'))
import monthly_parts_benchmark as monthly
import prepare_public_data as public
import run_public_training as runner


def source_series(name,values):
    return name+':1998-01-01 00-00-00:'+','.join(map(str,values))


def test_monthly_parser_preserves_observations_dates_and_real_zeros():
    text='@frequency monthly\n@data\n'+'\n'.join(
        source_series('T'+str(i),[0,2,1]*17) for i in range(3))
    rows,selection=public.parse_monthly(text.encode(),3)
    assert all(row['start']=='1998-01-01' and row['values']==[0,2,1]*17 for row in rows)
    assert selection['excludedMissingSeries']==0
    assert monthly.month(monthly.date(1998,1,1),50).isoformat()=='2002-03-01'


def test_missing_histories_are_excluded_instead_of_imputed_and_selection_ignores_test_sales():
    lines=[source_series('T'+str(i),[0,2,1]*17) for i in range(7)]
    missing=source_series('MISSING',[1]*50+['?'])
    raw=('@frequency monthly\n'+ '\n'.join(lines+[missing])).encode()
    rows,selection=public.parse_monthly(raw,3)
    changed=('@frequency monthly\n'+'\n'.join(
        source_series('T'+str(i),[0,2,1]*13+[200+i]*12) for i in range(7))+'\n'+missing).encode()
    other,_=public.parse_monthly(changed,3)
    expected=sorted(('T'+str(i) for i in range(7)),key=lambda x:hashlib.sha256(x.encode()).hexdigest())[:3]
    assert [r['id'] for r in rows]==[r['id'] for r in other]==expected
    assert selection['excludedMissingSeries']==1
    assert selection['eligibleCompleteSeries']==7


def test_pinned_sources_are_licensed_and_photo_product_identities_do_not_cross_splits():
    lock=json.loads((ROOT/'mlops/public-data-sources.lock.json').read_text())
    assert lock['syntheticData'] is False and lock['benchmarkOnly'] is True
    assert lock['photo']['license']=='CC-BY-4.0' and lock['history']['license']=='CC-BY-4.0'
    images=lock['photo']['images'];splits={}
    for row in images:
        assert row['productId'] not in splits or splits[row['productId']]==row['split']
        splits[row['productId']]=row['split']
        assert len(row['sha256'])==64 and row['url'].startswith('https://amazon-berkeley-objects.s3.us-east-1.amazonaws.com/')
    assert set(splits.values())=={'train','validation','test'}
    assert len({row['sourceImageId'] for row in images})==len(images)
    assert len({row['sha256'] for row in images})==len(images)
    rejected={row['productId'] for row in lock['photo'].get('excludedAfterVisualReview',[])}
    assert rejected.isdisjoint(splits)


def test_download_verifies_cached_bytes_and_rejects_unknown_origins(tmp_path):
    content=b'real source fixture';digest=hashlib.sha256(content).hexdigest()
    (tmp_path/digest).write_bytes(content)
    url='https://zenodo.org/approved'
    assert public.download(url,digest,tmp_path)==content
    (tmp_path/digest).write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='verification'):public.download(url,digest,tmp_path)
    with pytest.raises(ValueError,match='host'):public.download('https://unapproved.example/data',digest,tmp_path)


def monthly_fixture():
    return {'schemaVersion':1,'frequency':'monthly','benchmarkOnly':True,'syntheticData':False,
        'source':'unit-test-source','sourceSha256':'a'*64,
        'series':[{'id':'T'+str(i),'start':'1998-01-01','values':[0,2+i,1,0,3,2]*8} for i in range(3)]}


def test_held_out_sales_cannot_select_ridge_alpha_or_baseline():
    data=monthly_fixture();original,_=monthly.train(data)
    changed=copy.deepcopy(data)
    for row in changed['series']:row['values'][-12:]=[value*10+3 for value in row['values'][-12:]]
    modified,_=monthly.train(changed)
    assert [(row['alpha'],row['baselineMethod']) for row in original['series']]==[
        (row['alpha'],row['baselineMethod']) for row in modified['series']]
    assert original['series'][0]['evaluation']!=modified['series'][0]['evaluation']
    assert original['benchmarkOnly'] is True and original['productionEligible'] is False


def test_zero_demand_does_not_produce_nan_or_infinite_wape():
    data=monthly_fixture()
    for row in data['series']:row['values'][-12:]=[0]*12
    artifact,metrics=monthly.train(data)
    assert metrics['modelWAPE'] is None and metrics['baselineWAPE'] is None
    assert metrics['qualityGatePassed'] is False
    json.dumps(artifact,allow_nan=False)


@pytest.mark.parametrize('bad',[-1,None,float('nan'),True])
def test_invalid_monthly_observations_are_rejected(bad):
    data=monthly_fixture();data['series'][0]['values'][0]=bad
    with pytest.raises(ValueError,match='Missing or invalid'):monthly.validate(data)


def test_monthly_data_is_not_accepted_as_daily_workshop_history():
    data=monthly_fixture();data['frequency']='daily'
    with pytest.raises(ValueError,match='monthly'):monthly.validate(data)


def test_public_photos_require_the_explicit_benchmark_training_path(tmp_path):
    from train import train
    from upload_dataset import upload
    (tmp_path/'dataset-metadata.json').write_text(json.dumps({'benchmarkOnly':True,'synthetic':False}))
    with pytest.raises(ValueError,match='public-data workflow'):train(tmp_path,'unused',tmp_path/'model')
    s3=Mock()
    with pytest.raises(ValueError,match='benchmark'):upload(tmp_path,'owned','ap-southeast-2',s3)
    s3.put_object.assert_not_called()


@pytest.mark.parametrize('task',['photo','forecast'])
def test_real_training_uses_valid_aws_requests_and_registers_failed_gates_as_benchmark_only(task,monkeypatch):
    metrics={'benchmarkOnly':True,'syntheticData':False,'qualityGatePassed':False}
    buffer=io.BytesIO();content=json.dumps(metrics).encode()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        entry=tarfile.TarInfo('metrics.json');entry.size=len(content);archive.addfile(entry,io.BytesIO(content))
    s3=Mock();s3.get_object.return_value={'Body':io.BytesIO(buffer.getvalue())}
    sm=Mock();job_arn='arn:aws:sagemaker:ap-southeast-2:123456789012:training-job/test'
    sm.create_training_job.return_value={'TrainingJobArn':job_arn}
    sm.create_model_package.return_value={'ModelPackageArn':'registered-package'}
    monkeypatch.setattr(runner,'wait_for_job',lambda *args:{'TrainingJobStatus':'Completed',
        'ModelArtifacts':{'S3ModelArtifacts':'s3://owned/benchmarks/public/training/job/output/model.tar.gz'}})
    config={'name':'stocklane-dev','model_bucket':'owned','training_role_arn':'arn:aws:iam::123456789012:role/training',
        'model_package_group':'stocklane-dev-visual-sku','forecast_model_package_group':'stocklane-dev-stock-forecast'}
    result=runner.train_one(task,config,sm,s3,'123456789012.dkr.ecr.ap-southeast-2.amazonaws.com/training@sha256:'+'a'*64,
        's3://owned/benchmarks/public/datasets/data/','s3://owned/encoders/approved/','b'*64,'c'*64,{})
    schema=botocore.session.get_session().get_service_model('sagemaker')
    validate_parameters(sm.create_training_job.call_args.kwargs,schema.operation_model('CreateTrainingJob').input_shape)
    validate_parameters(sm.create_model_package.call_args.kwargs,schema.operation_model('CreateModelPackage').input_shape)
    request=sm.create_training_job.call_args.kwargs
    assert request['HyperParameters']['benchmark_mode']=='true' and request['EnableNetworkIsolation'] is True
    assert {x['ChannelName'] for x in request['InputDataConfig']}==({'dataset','encoder'} if task=='photo' else {'dataset'})
    package=sm.create_model_package.call_args.kwargs
    assert package['ModelApprovalStatus']=='PendingManualApproval'
    assert package['CustomerMetadataProperties']['benchmarkOnly']=='true'
    assert package['CustomerMetadataProperties']['syntheticData']=='false'
    assert result['creationConfirmed'] is True and result['trainingJobArn']==job_arn
    assert result['trainingJobStatus']=='Completed' and result['qualityGatePassed'] is False
    assert result['productionEligible'] is False
    assert all(call.kwargs['Key'].startswith('benchmarks/public/') for call in s3.put_object.call_args_list)


def test_failed_job_creation_is_not_reported_as_created():
    sm=Mock();sm.create_training_job.side_effect=ClientError({'Error':{'Code':'ResourceLimitExceeded'}},'CreateTrainingJob')
    result={};config={'name':'stocklane-dev','training_role_arn':'role','model_bucket':'owned'}
    with pytest.raises(ClientError):runner.train_one('forecast',config,sm,Mock(),'image','s3://owned/data/',None,'a'*64,'b'*64,result)
    assert result['creationConfirmed'] is False and 'trainingJobArn' not in result
    sm.create_model_package.assert_not_called()


def test_artifact_from_live_prefix_cannot_be_registered_as_a_public_benchmark():
    s3=Mock()
    with pytest.raises(ValueError,match='location'):runner.read_metrics(s3,'owned','s3://owned/training/live/model.tar.gz')
    s3.get_object.assert_not_called()


def test_live_approval_promotion_and_inference_reject_public_benchmarks(tmp_path,monkeypatch):
    from review_model import review
    import promote
    from app.encoder import Encoder
    from test_forecast import module
    config={'region':'ap-southeast-2','account_id':'123456789012','model_package_group':'stocklane-dev-visual-sku'}
    arn='arn:aws:sagemaker:ap-southeast-2:123456789012:model-package/stocklane-dev-visual-sku/1'
    sm=Mock();sm.describe_model_package.return_value={'CustomerMetadataProperties':{'benchmarkOnly':'true'}}
    with pytest.raises(ValueError,match='workshop validation'):review(arn,'Approved',config,sm)
    sm.update_model_package.assert_not_called()
    monkeypatch.setattr(promote.boto3,'client',lambda name,**kwargs:sm if name=='sagemaker' else Mock())
    with pytest.raises(RuntimeError,match='workshop models'):promote.promote(arn,'ap-southeast-2','s3://owned/releases/')
    (tmp_path/'model.json').write_text(json.dumps({'benchmarkOnly':True}))
    with pytest.raises(RuntimeError,match='workshop validation'):Encoder(tmp_path)
    with pytest.raises(ValueError,match='benchmark'):module().projection({'benchmarkOnly':True},[])


def test_console_approval_cannot_make_a_public_benchmark_look_production_ready():
    import check_readiness
    sm=Mock();sm.list_model_packages.return_value={'ModelPackageSummaryList':[{
        'ModelPackageArn':'public','ModelPackageVersion':1,'ModelPackageStatus':'Completed','ModelApprovalStatus':'Approved'}]}
    sm.describe_model_package.return_value={'CustomerMetadataProperties':{'syntheticData':'false','benchmarkOnly':'true'}}
    result=check_readiness.check_registry(sm,'group')
    assert result['status']=='public_benchmark_only' and result['deployedVersionVerified'] is False

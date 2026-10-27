import io
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import check_readiness as readiness

NOW=datetime(2026,10,27,10,tzinfo=timezone.utc)
C={'account_id':'123456789012','region':'ap-southeast-2','environment':'dev',
   'name':'stocklane-dev','model_bucket':'example-models','cluster_name':'stocklane-dev',
   'workload_namespace':'stocklane-dev'}


def forecast(status='insufficient_history'):
    return {'schemaVersion':1,'task':'stock_usage_forecast','trainedAt':'2026-10-27T08:00:00Z',
        'historyUntil':'2026-10-27','products':[{'status':status} for _ in range(9)],
        'trainingJob':None,'modelPackageArn':None,'qualityGatePassed':False}


def test_published_insufficient_history_is_not_a_trained_model():
    result=readiness.summarize_forecast(forecast(),NOW)
    assert result['status']=='insufficient_history'
    assert result['counts']=={'trained_ml':0,'weekday_baseline':0,'insufficient_history':9}
    assert result['trainingJob'] is None


def test_baseline_and_stale_results_are_labelled_separately():
    model=forecast('weekday_baseline')
    assert readiness.summarize_forecast(model,NOW)['status']=='baseline_only'
    model['historyUntil']='2026-10-01'
    assert readiness.summarize_forecast(model,NOW)['status']=='stale'


def test_ml_label_without_training_lineage_is_rejected_as_evidence():
    assert readiness.summarize_forecast(forecast('trained_ml'),NOW)['status']=='invalid_ml_lineage'


def test_unknown_method_and_future_timestamp_do_not_receive_ready_status():
    with pytest.raises(ValueError):readiness.summarize_forecast(forecast('invented'),NOW)
    model=forecast();model['trainedAt']='2027-01-01T00:00:00Z'
    with pytest.raises(ValueError):readiness.summarize_forecast(model,NOW)


def test_approved_registry_version_does_not_prove_it_is_deployed():
    class SM:
        def describe_model_package(self,**kwargs):return {'CustomerMetadataProperties':{}}
        def list_model_packages(self,**kwargs):
            return {'ModelPackageSummaryList':[{'ModelPackageArn':'example','ModelPackageVersion':1,
                'ModelPackageStatus':'Completed','ModelApprovalStatus':'Approved'}]}
    result=readiness.check_registry(SM(),'demo-group')
    assert result['status']=='approved_candidate_exists'
    assert result['deployedVersionVerified'] is False


def test_a_demo_package_is_not_reported_as_a_production_candidate_even_after_console_approval():
    class SM:
        def describe_model_package(self,**kwargs):return {'CustomerMetadataProperties':{'syntheticData':'true'}}
        def list_model_packages(self,**kwargs):
            return {'ModelPackageSummaryList':[{'ModelPackageArn':'example','ModelPackageVersion':1,
                'ModelPackageStatus':'Completed','ModelApprovalStatus':'Approved'}]}
    assert readiness.check_registry(SM(),'demo-group')['status']=='demo_only'


def test_aws_permission_failure_is_unverified_not_missing_or_healthy():
    def denied():raise ClientError({'Error':{'Code':'AccessDenied','Message':'do not print credentials'}},'ListModelPackages')
    assert readiness.attempt(denied)=={'status':'unverified','errorCode':'AccessDenied'}


class SQS:
    def __init__(self,dead=0):self.dead=dead
    def get_queue_attributes(self,QueueUrl,AttributeNames):
        if QueueUrl.endswith('-dlq'):return {'Attributes':{'ApproximateNumberOfMessages':str(self.dead)}}
        return {'Attributes':{'QueueArn':'arn:aws:sqs:ap-southeast-2:123456789012:stocklane-dev-stock',
            'ApproximateNumberOfMessages':'0','ApproximateNumberOfMessagesNotVisible':'0',
            'RedrivePolicy':json.dumps({'deadLetterTargetArn':'arn:aws:sqs:ap-southeast-2:123456789012:stocklane-dev-stock-dlq','maxReceiveCount':5})}}
    def get_queue_url(self,**kwargs):return {'QueueUrl':'https://sqs.ap-southeast-2.amazonaws.com/123456789012/stocklane-dev-stock-dlq'}


class CloudWatch:
    def get_metric_statistics(self,**kwargs):return {'Datapoints':[]}


def test_idle_queue_is_not_reported_as_proven_event_delivery():
    result=readiness.check_queue(SQS(),CloudWatch(),'https://sqs.ap-southeast-2.amazonaws.com/123456789012/stocklane-dev-stock',C,NOW)
    assert result['status']=='configured'
    assert result['activity']['NumberOfMessagesDeleted']==0
    assert 'do not prove' in result['note']


def test_dead_letters_require_attention():
    result=readiness.check_queue(SQS(dead=2),CloudWatch(),'https://sqs.ap-southeast-2.amazonaws.com/123456789012/stocklane-dev-stock',C,NOW)
    assert result['status']=='dead_letters_present'


def test_other_account_queue_is_never_inspected():
    with pytest.raises(ValueError,match='scope'):
        readiness.check_queue(SQS(),CloudWatch(),'https://sqs.ap-southeast-2.amazonaws.com/999999999999/stock',C,NOW)


def test_kubernetes_probe_targets_the_actual_vision_container_without_mutations():
    calls=[]
    def runner(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(returncode=0,stdout=json.dumps({'bedrock':{'status':'invocation_verified'}}))
    result=readiness.workload_probe(C,True,runner)
    assert result['bedrock']['status']=='invocation_verified'
    assert calls[0][0][:3]==['aws','eks','update-kubeconfig']
    assert 'deployment/vision' in calls[1][0] and '--probe-bedrock' in calls[1][0]
    assert 'settings.internal_token' in calls[1][1]['input']
    assert 'print(settings' not in calls[1][1]['input']


def test_text_probe_requires_actual_workload_identity(monkeypatch):
    args=SimpleNamespace(probe_bedrock=True,kubernetes=False)
    with pytest.raises(ValueError,match='real Vision IAM role'):readiness.main(args)

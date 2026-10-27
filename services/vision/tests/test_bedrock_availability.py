import json
from types import SimpleNamespace

import fakeredis
import pytest
import redis
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient

from app import bedrock
from app.config import Settings
from app.main import create_app


def provider_error(code,message='provider detail must not reach the user'):
    return ClientError({'Error':{'Code':code,'Message':message}},'Converse')


@pytest.mark.parametrize('error,code,retryable,status',[
    (provider_error('ThrottlingException','Too many tokens per day'),'AI_PROVIDER_QUOTA',False,503),
    (provider_error('ThrottlingException','Too many requests'),'AI_PROVIDER_BUSY',True,503),
    (provider_error('ServiceQuotaExceededException'),'AI_PROVIDER_QUOTA',False,503),
    (provider_error('AccessDeniedException'),'AI_ACCESS_DENIED',False,503),
    (provider_error('ValidationException'),'AI_MODEL_CONFIGURATION',False,503),
    (provider_error('ResourceNotFoundException'),'AI_MODEL_CONFIGURATION',False,503),
    (EndpointConnectionError(endpoint_url='https://private.example'),'AI_PROVIDER_TIMEOUT',True,503),
    (ValueError('invalid JSON'),'AI_INVALID_RESPONSE',False,502),
])
def test_provider_failure_is_sanitized_and_actionable(error,code,retryable,status):
    problem=bedrock.failure(error)
    assert (problem.code,problem.retryable,problem.status)==(code,retryable,status)
    assert 'provider detail' not in problem.message and 'private.example' not in problem.message


def test_propose_preserves_quota_classification(monkeypatch):
    class Client:
        def converse(self,**kwargs):raise provider_error('ThrottlingException','Too many tokens per day')
    monkeypatch.setattr(bedrock.boto3,'client',lambda *args,**kwargs:Client())
    with pytest.raises(bedrock.BedrockUnavailable) as caught:
        bedrock.propose(SimpleNamespace(bedrock_model_id='amazon.nova-lite-v1:0',aws_region='ap-southeast-2'),b'photo')
    assert caught.value.code=='AI_PROVIDER_QUOTA'


@pytest.fixture
def ai_client(tmp_path,monkeypatch):
    shared=fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis,'from_url',lambda *args,**kwargs:shared)
    settings=Settings(environment='local',auth_mode='local',internal_token='x'*32,
        database_url='sqlite:///'+str(tmp_path/'vision.db'),files_root=str(tmp_path/'photos'),
        model_dir=str(tmp_path/'no-model'),bedrock_model_id='amazon.nova-lite-v1:0')
    with TestClient(create_app(settings)) as client:yield client


def save_photo(client):
    from test_vision import photo
    return client.app.state.store.save_image(photo())


def test_configuration_is_not_reported_as_verified_access(ai_client):
    result=ai_client.get('/api/vision/status').json()
    assert result['bedrockConfigured'] is True
    assert result['bedrockAccess']['state']=='not_verified'
    assert result['bedrockAccess']['checkedAt'] is None


def test_quota_error_creates_no_draft_and_is_visible_in_status(ai_client,monkeypatch,caplog):
    import app.main as main
    def fail(*args):raise provider_error('ThrottlingException','Too many tokens per day SECRET-SENTINEL')
    monkeypatch.setattr(main,'propose',fail)
    response=ai_client.post('/api/vision/drafts',json={'imageId':save_photo(ai_client)})
    assert response.status_code==503
    assert response.json()['code']=='AI_PROVIDER_QUOTA'
    assert response.json()['retryable'] is False
    assert 'Retry-After' not in response.headers
    assert ai_client.get('/api/vision/drafts').json()==[]
    assert ai_client.get('/api/vision/status').json()['bedrockAccess']['errorCode']=='AI_PROVIDER_QUOTA'
    assert 'SECRET-SENTINEL' not in response.text+caplog.text
    metrics=ai_client.get('/metrics',headers={'Authorization':'Bearer '+'x'*32}).text
    assert 'stocklane_ai_drafts_total{outcome="AI_PROVIDER_QUOTA"} 1.0' in metrics


def test_verified_access_requires_an_actual_successful_invocation(ai_client,monkeypatch):
    import app.main as main
    calls=[]
    def propose(*args):calls.append(1);return {'name':'Example filter'},'bedrock'
    monkeypatch.setattr(main,'propose',propose)
    image=save_photo(ai_client)
    assert ai_client.post('/api/vision/drafts',json={'imageId':image}).status_code==200
    assert ai_client.post('/api/vision/drafts',json={'imageId':image}).status_code==200
    state=ai_client.get('/api/vision/status').json()['bedrockAccess']
    assert state['state']=='invocation_verified' and state['scope']=='this_replica'
    assert state['checkedAt'] and state['errorCode'] is None
    assert len(calls)==1

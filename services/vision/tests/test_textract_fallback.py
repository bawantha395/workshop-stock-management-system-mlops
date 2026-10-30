from types import SimpleNamespace

import fakeredis
import pytest
import redis
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app import textract
from app.config import Settings
from app.main import create_app


def quota_error():
    return ClientError({'Error': {'Code': 'ThrottlingException', 'Message': 'Too many tokens per day'}}, 'Converse')


# ---- reading label text ----------------------------------------------------------------------

@pytest.mark.parametrize('lines,expected', [
    (['MOBIL 1', 'FULLY SYNTHETIC', 'ENGINE OIL', '5W-30', '4 LITRES', 'P/N 153048', 'www.mobil.com'],
     {'name': 'Mobil Engine Oil', 'brand': 'Mobil', 'partNumber': '153048', 'category': 'Engine oil',
      'grade': '5W-30', 'capacity': '4L'}),
    (['Toyota Genuine Parts', 'OIL FILTER', '90915-YZZE1', 'Made in Japan', 'Qty 1 pc'],
     {'name': 'Toyota Oil Filter', 'brand': 'Toyota', 'partNumber': '90915-YZZE1', 'category': 'Filters'}),
    (['Denso', 'Iridium TT', 'Spark Plug', 'IK20TT', 'Batch 12/10/2025'],
     {'name': 'Denso Spark Plug', 'brand': 'Denso', 'partNumber': 'IK20TT', 'category': 'Spark plugs'}),
    (['hello', '12', 'x'], {}),
])
def test_label_text_becomes_catalogue_fields(lines, expected):
    assert textract.parse_lines(lines) == expected


def test_fields_are_bounded_and_never_include_quantities_or_prices():
    fields = textract.parse_lines(['Castrol ' + 'EDGE ' * 80, 'LKR 5,000', 'Quantity 500'])
    assert set(fields) <= set(textract.LIMITS)
    assert all(len(value) <= textract.LIMITS[key] for key, value in fields.items())


def test_only_confident_lines_are_used_and_the_region_is_configurable(monkeypatch):
    seen = {}
    class Client:
        def detect_document_text(self, **kwargs):
            seen['document'] = kwargs['Document']
            return {'Blocks': [{'BlockType': 'LINE', 'Text': 'Bosch', 'Confidence': 99},
                               {'BlockType': 'WORD', 'Text': 'ignored', 'Confidence': 99},
                               {'BlockType': 'LINE', 'Text': 'blurry', 'Confidence': 20}]}
    def client(name, **kwargs):
        seen.update(name=name, region=kwargs['region_name'])
        return Client()
    monkeypatch.setattr(textract.boto3, 'client', client)
    lines = textract.read_lines(SimpleNamespace(aws_region='ap-southeast-2', textract_region='us-east-1'), b'photo')
    assert lines == ['Bosch']
    assert seen == {'name': 'textract', 'region': 'us-east-1', 'document': {'Bytes': b'photo'}}
    textract.read_lines(SimpleNamespace(aws_region='ap-southeast-2'), b'photo')
    assert seen['region'] == 'ap-southeast-2'


# ---- the draft endpoint ----------------------------------------------------------------------

def make_client(tmp_path, monkeypatch, fallback):
    shared = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis, 'from_url', lambda *args, **kwargs: shared)
    settings = Settings(environment='local', auth_mode='local', internal_token='x' * 32,
        database_url='sqlite:///' + str(tmp_path / 'vision.db'), files_root=str(tmp_path / 'photos'),
        model_dir=str(tmp_path / 'no-model'), bedrock_model_id='amazon.nova-lite-v1:0', textract_fallback=fallback)
    return TestClient(create_app(settings))


def photo_id(client):
    from test_vision import photo
    return client.app.state.store.save_image(photo())


def test_label_text_is_used_when_bedrock_is_unavailable(tmp_path, monkeypatch):
    import app.main as main
    def fail(*args):
        raise quota_error()
    monkeypatch.setattr(main, 'propose', fail)
    monkeypatch.setattr(textract, 'propose', lambda settings, image: {'name': 'Toyota Oil Filter', 'brand': 'Toyota'})
    with make_client(tmp_path, monkeypatch, True) as client:
        response = client.post('/api/vision/drafts', json={'imageId': photo_id(client)})
        assert response.status_code == 200
        body = response.json()
        assert body['source'] == 'textract' and body['fields'] == {} and body['status'] == 'PENDING'
        # The person sees clearly that AI suggestions were not available, and why.
        assert body['ai']['status'] == 'unavailable' and body['ai']['code'] == 'AI_PROVIDER_QUOTA'
        assert body['suggestions'] == {'name': 'Toyota Oil Filter', 'brand': 'Toyota'}
        # The status page still reports the real Bedrock problem.
        assert client.get('/api/vision/status').json()['bedrockAccess']['errorCode'] == 'AI_PROVIDER_QUOTA'
        metrics = client.get('/metrics', headers={'Authorization': 'Bearer ' + 'x' * 32}).text
        assert 'stocklane_ai_drafts_total{outcome="textract"} 1.0' in metrics


@pytest.mark.parametrize('fallback,reader', [
    (False, lambda settings, image: {'name': 'never used'}),                       # switched off
    (True, lambda settings, image: {}),                                            # nothing readable
    (True, lambda settings, image: (_ for _ in ()).throw(RuntimeError('SECRET'))),  # Textract also fails
])
def test_the_original_bedrock_error_is_shown_when_the_fallback_cannot_help(tmp_path, monkeypatch, fallback, reader):
    import app.main as main
    def fail(*args):
        raise quota_error()
    monkeypatch.setattr(main, 'propose', fail)
    monkeypatch.setattr(textract, 'propose', reader)
    with make_client(tmp_path, monkeypatch, fallback) as client:
        response = client.post('/api/vision/drafts', json={'imageId': photo_id(client)})
        assert response.status_code == 503 and response.json()['code'] == 'AI_PROVIDER_QUOTA'
        assert 'SECRET' not in response.text
        assert client.get('/api/vision/drafts').json() == []


def test_label_text_comes_first_and_the_llm_only_suggests_missing_fields(tmp_path, monkeypatch):
    import app.main as main
    seen = {}
    def suggest(settings, image, known):
        seen['known'] = dict(known)
        return {'name': 'Castrol GTX 10W-40 1L', 'brand': 'Not Castrol', 'category': 'Engine oil'}, 'bedrock'
    monkeypatch.setattr(main, 'propose', suggest)
    monkeypatch.setattr(textract, 'propose', lambda settings, image: {'brand': 'Castrol', 'grade': '10W-40'})
    with make_client(tmp_path, monkeypatch, True) as client:
        body = client.post('/api/vision/drafts', json={'imageId': photo_id(client)}).json()
        assert seen['known'] == {'brand': 'Castrol', 'grade': '10W-40'}
        assert body['source'] == 'textract' and body['fields'] == {}
        # Label text and model output are both reviewable suggestions.
        assert body['suggestions'] == {'brand': 'Castrol', 'grade': '10W-40', 'name': 'Castrol GTX 10W-40 1L', 'category': 'Engine oil'}
        assert client.get('/api/vision/status').json()['bedrockAccess']['state'] == 'invocation_verified'
        assert body['ai'] == {'status': 'used'}


def test_label_text_still_works_when_the_daily_ai_limit_is_reached(tmp_path, monkeypatch):
    import app.main as main
    calls = []
    monkeypatch.setattr(main, 'propose', lambda *args: calls.append(1) or ({'category': 'Oil filter'}, 'bedrock'))
    monkeypatch.setattr(textract, 'propose', lambda settings, image: {'brand': 'Toyota'})
    shared = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis, 'from_url', lambda *args, **kwargs: shared)
    settings = Settings(environment='local', auth_mode='local', internal_token='x' * 32,
        database_url='sqlite:///' + str(tmp_path / 'vision.db'), files_root=str(tmp_path / 'photos'),
        model_dir=str(tmp_path / 'no-model'), bedrock_model_id='amazon.nova-lite-v1:0', textract_fallback=True,
        bedrock_daily_request_limit=0)
    with TestClient(create_app(settings)) as client:
        response = client.post('/api/vision/drafts', json={'imageId': photo_id(client)})
        assert response.status_code == 200 and response.json()['fields'] == {}
        assert response.json()['suggestions'] == {'brand': 'Toyota'} and calls == []
        assert response.json()['ai'] == {'status': 'limit_reached'}

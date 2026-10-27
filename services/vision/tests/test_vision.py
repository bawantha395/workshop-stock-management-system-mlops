from pathlib import Path
import io
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from app.config import Settings
from app.main import create_app
from app.encoder import Encoder

ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture
def client(tmp_path):
    s=Settings(environment='local',auth_mode='local',internal_token='test-service-token-at-least-32-characters',database_url='sqlite:///'+str(tmp_path/'vision.db'),files_root=str(tmp_path/'images'),model_dir=str(ROOT/'models/baseline'),redis_url='redis://127.0.0.1:1/0')
    with TestClient(create_app(s)) as c:yield c

def photo():
    im=Image.new('RGB',(320,400),'#e8eee7');d=ImageDraw.Draw(im);d.rectangle((90,70,220,340),fill='#728b56');d.rectangle((100,160,210,280),fill='#f4e8c4');d.text((112,200),'5W-30 4L',fill='black');b=io.BytesIO();im.save(b,format='JPEG');return b.getvalue()

def upload(client,data=None):return client.post('/api/vision/match',files={'file':('item.jpg',data or photo(),'image/jpeg')})

def test_model_is_real_and_ready(client):
    r=client.get('/health/ready');assert r.status_code==200;assert 'mobilenetv2' in r.json()['modelVersion']

def test_unseen_item_is_not_auto_approved(client):
    r=upload(client);assert r.status_code==200;assert r.json()['state']=='UNKNOWN';assert r.json()['autoPostEligible'] is False

def test_approved_catalogue_photo_is_retrieved(client):
    r=upload(client).json();product={'id':str(uuid.uuid4()),'sku':'MOB-4L','name':'Mobil 4L','image_id':r['imageId']}
    event={'eventId':str(uuid.uuid4()),'type':'CATALOGUE_APPROVED','payload':product}
    h={'X-Internal-Token':'test-service-token-at-least-32-characters'}
    assert client.post('/internal/events',json=event,headers=h).status_code==200
    assert client.post('/internal/events',json=event,headers=h).status_code==200
    candidates=upload(client).json()['candidates'];assert len(candidates)==1;assert candidates[0]['product']['sku']=='MOB-4L';assert candidates[0]['similarity']>.999

def test_internal_events_require_secret(client):
    assert client.post('/internal/events',json={}).status_code==401

def test_bad_photo_is_rejected(client):
    assert upload(client,b'not an image').status_code==422

def test_image_path_is_validated(client):
    assert client.get('/api/vision/images/not-an-id.jpg').status_code==404

def test_manual_draft_does_not_invent_fields(client):
    image=upload(client).json()['imageId'];r=client.post('/api/vision/drafts',json={'imageId':image});assert r.status_code==200;assert r.json()['source']=='manual';assert r.json()['fields']=={};assert r.json()['status']=='PENDING'

def test_reject_draft_does_not_create_catalogue_reference(client):
    image=upload(client).json()['imageId'];draft=client.post('/api/vision/drafts',json={'imageId':image}).json();assert client.patch('/api/vision/drafts/'+draft['id'],json={'status':'REJECTED'}).status_code==200;assert upload(client).json()['candidates']==[]

def test_local_auth_is_not_a_cloud_fallback():
    with pytest.raises(RuntimeError):Settings(environment='cloud',auth_mode='local',internal_token='x'*32).check()

def test_model_checksum_is_enforced(tmp_path):
    (tmp_path/'encoder.onnx').write_bytes(b'changed');(tmp_path/'model.json').write_text(json.dumps({'sha256':'bad'}))
    with pytest.raises(RuntimeError,match='checksum'):Encoder(tmp_path)

def test_camera_retry_does_not_duplicate_inbox(client):
    event=str(uuid.uuid4());metadata={'event_id':event,'direction':'IN','station_id':'test-tray','job_id':''}
    def send():return client.post('/api/vision/captures',data=metadata,files={'file':('item.jpg',photo(),'image/jpeg')})
    assert send().status_code==200;assert send().status_code==200
    records=client.get('/api/vision/captures').json();assert len(records)==1;assert records[0]['status']=='PENDING'

def test_camera_reused_id_with_different_evidence_is_rejected(client):
    event=str(uuid.uuid4());metadata={'event_id':event,'direction':'IN','station_id':'test-tray'}
    assert client.post('/api/vision/captures',data=metadata,files={'file':('item.jpg',photo(),'image/jpeg')}).status_code==200
    metadata['direction']='OUT'
    assert client.post('/api/vision/captures',data=metadata,files={'file':('item.jpg',photo(),'image/jpeg')}).status_code==409

def test_capture_movement_requires_a_staff_confirmed_ledger_entry(client):
    metadata={'event_id':str(uuid.uuid4()),'direction':'OUT','station_id':'test-tray','job_id':''}
    response=client.post('/api/vision/captures',data=metadata,files={'file':('item.jpg',photo(),'image/jpeg')})
    assert response.status_code==200;assert response.json()['job_id'] is None
    assert response.json()['status']=='PENDING'

def test_metrics_require_service_identity(client):
    assert client.get('/metrics').status_code==401
    response=client.get('/metrics',headers={'Authorization':'Bearer test-service-token-at-least-32-characters'})
    assert response.status_code==200;assert 'stocklane_http_requests' in response.text

def test_cached_photo_never_merges_distinct_delivery_events(tmp_path,monkeypatch):
    import fakeredis,redis
    shared=fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis,'from_url',lambda *a,**kw:shared)
    s=Settings(environment='local',auth_mode='local',internal_token='test-service-token-at-least-32-characters',database_url='sqlite:///'+str(tmp_path/'cache.db'),files_root=str(tmp_path/'images'),model_dir=str(ROOT/'models/baseline'))
    calls=[];original=Encoder.encode
    def encode(self,data):calls.append(1);return original(self,data)
    monkeypatch.setattr(Encoder,'encode',encode)
    with TestClient(create_app(s)) as client:
        for _ in range(2):
            metadata={'event_id':str(uuid.uuid4()),'direction':'IN','station_id':'same-tray'}
            assert client.post('/api/vision/captures',data=metadata,files={'file':('item.jpg',photo(),'image/jpeg')}).status_code==200
        assert len(calls)==1
        assert len(client.get('/api/vision/captures').json())==2

def test_low_similarity_cannot_become_a_photo_match(client,monkeypatch):
    monkeypatch.setattr(client.app.state.store,'candidates',lambda *args:[{'similarity':0.40,'product':{'id':str(uuid.uuid4())},'imageId':'unused'}])
    response=upload(client)
    assert response.status_code==200
    assert response.json()['candidates']==[]
    assert response.json()['state']=='UNKNOWN'
    assert response.json()['autoPostEligible'] is False


def test_qr_endpoint_does_not_persist_a_capture_or_change_stock(client):
    from test_qr import qr_image
    value='stocklane:v1:3f2b8c1e-5a47-4d9e-9b6a-0c1d2e3f4a5b'
    response=client.post('/api/vision/qr',files={'file':('qr.png',qr_image(value),'image/png')})
    assert response.status_code==200
    assert response.json()=={'value':value}
    assert client.get('/api/vision/captures').json()==[]

def test_bedrock_daily_limit_applies_on_cache_misses_only(tmp_path,monkeypatch):
    import redis,fakeredis
    import app.main as main
    shared=fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis,'from_url',lambda *a,**kw:shared)
    calls=[]
    def propose(*args):calls.append(1);return {'name':'Filter'},'bedrock'
    monkeypatch.setattr(main,'propose',propose)
    settings=Settings(environment='local',auth_mode='local',internal_token='x'*32,database_url='sqlite:///'+str(tmp_path/'ai.db'),files_root=str(tmp_path/'images'),model_dir=str(ROOT/'models/baseline'),bedrock_model_id='amazon.nova-lite-v1:0',bedrock_daily_request_limit=1)
    with TestClient(create_app(settings)) as client:
        first=upload(client).json()['imageId']
        assert client.post('/api/vision/drafts',json={'imageId':first}).status_code==200
        assert client.post('/api/vision/drafts',json={'imageId':first}).status_code==200
        fresh=io.BytesIO();Image.new('RGB',(320,400),'#4477aa').save(fresh,format='JPEG')
        second=upload(client,fresh.getvalue()).json()['imageId']
        assert client.post('/api/vision/drafts',json={'imageId':second}).status_code==429
    assert len(calls)==1

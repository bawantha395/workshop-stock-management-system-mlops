import base64,time
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt
from starlette.requests import Request
from fastapi import HTTPException
from app.config import Settings
from app.security import Security

ISSUER='https://cognito-idp.eu-west-1.amazonaws.com/test-pool'

@pytest.fixture(scope='module')
def keys():
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    numbers=private.public_key().public_numbers()
    def b64(x):return base64.urlsafe_b64encode(x.to_bytes((x.bit_length()+7)//8,'big')).decode().rstrip('=')
    pem=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    return pem,{'keys':[{'kty':'RSA','kid':'test-key','use':'sig','alg':'RS256','n':b64(numbers.n),'e':b64(numbers.e)}]}

def check(keys,override=None,capture=False):
    private,public=keys
    claims={'iss':ISSUER,'sub':'test-owner','iat':int(time.time()),'exp':int(time.time())+300,'client_id':'web-client','token_use':'access','cognito:groups':['OWNER']}
    claims.update(override or {})
    token=jwt.encode(claims,private,algorithm='RS256',headers={'kid':'test-key'})
    security=Security(Settings(cognito_issuer=ISSUER,cognito_client_ids='web-client,camera-client'))
    security.keys=public;security.expires=time.monotonic()+300
    request=Request({'type':'http','headers':[(b'authorization',('Bearer '+token).encode())]})
    return security.staff(request,capture=capture)

def test_valid_staff_access_token(keys):assert check(keys)=='test-owner'

@pytest.mark.parametrize('override',[{'token_use':'id'},{'client_id':'another-app'},{'iss':'https://another-issuer.example'},{'exp':int(time.time())-100}])
def test_wrong_token_claims_are_rejected(keys,override):
    with pytest.raises(HTTPException) as e:check(keys,override)
    assert e.value.status_code==401

def test_camera_token_cannot_approve_catalogue(keys):
    claims={'sub':'camera-client','client_id':'camera-client','cognito:groups':[],'scope':'stocklane/capture'}
    assert check(keys,claims,capture=True)=='camera-client'
    with pytest.raises(HTTPException) as e:check(keys,claims,capture=False)
    assert e.value.status_code==403

def test_unsigned_algorithm_is_not_accepted(keys):
    private,public=keys
    security=Security(Settings(cognito_issuer=ISSUER,cognito_client_ids='web-client'));security.keys=public;security.expires=time.monotonic()+300
    token=jwt.encode({'iss':ISSUER,'exp':int(time.time())+300,'iat':int(time.time())},'wrong-key',algorithm='HS256')
    with pytest.raises(HTTPException) as e:security.staff(Request({'type':'http','headers':[(b'authorization',('Bearer '+token).encode())]}))
    assert e.value.status_code==401

def test_metrics_token_is_not_a_production_capture_read_capability():
    s=Settings(auth_mode='cognito',environment='cloud',internal_token='metrics-'+'m'*40,vision_read_token='read-'+'r'*40)
    sec=Security(s)
    def request(token,method='GET',path='/internal/captures/test'):
        return Request({'type':'http','method':method,'path':path,'scheme':'http','server':('test',80),'headers':[(b'x-internal-token',token.encode())]})
    sec.internal(request(s.vision_read_token))
    with pytest.raises(HTTPException) as e:sec.internal(request(s.internal_token))
    assert e.value.status_code==401
    with pytest.raises(HTTPException) as e:sec.internal(request(s.vision_read_token,'POST','/internal/events'))
    assert e.value.status_code==403

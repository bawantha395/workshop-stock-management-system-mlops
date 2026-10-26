import json
from types import SimpleNamespace
from app import bedrock
from app.encoder import Encoder

def test_label_fields_are_restricted_and_request_is_bounded(monkeypatch):
    calls=[]
    class Client:
        def converse(self,**kw):
            calls.append(kw)
            return {'output':{'message':{'content':[{'text':json.dumps({'name':'Filter','partNumber':'AC-123','quantity':'500','approval':'yes'})}]}},'usage':{'inputTokens':50,'outputTokens':20}}
    monkeypatch.setattr(bedrock.boto3,'client',lambda *a,**kw:Client())
    fields,source=bedrock.propose(SimpleNamespace(bedrock_model_id='amazon.nova-lite-v1:0',aws_region='ap-southeast-2'),b'image')
    assert fields=={'name':'Filter','partNumber':'AC-123'} and source=='bedrock'
    assert calls[0]['inferenceConfig']=={'maxTokens':450,'temperature':0}

def test_calibrated_model_uses_its_validated_threshold():
    encoder=object.__new__(Encoder);encoder.manifest={'calibration':{'coefficient':20,'intercept':-17,'threshold':.9}}
    assert not encoder.accepts(.92,.92)
    assert encoder.accepts(1,.92)
    encoder.manifest={}
    assert encoder.accepts(.95,.92) and not encoder.accepts(.8,.92)

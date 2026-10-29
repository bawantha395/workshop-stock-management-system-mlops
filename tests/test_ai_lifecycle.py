import io,json,sys,tarfile,hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mlops'))
from stage_encoder import stage
from upload_dataset import upload

class MemoryS3:
    def __init__(self,values=None):self.values=values or {};self.puts=[]
    def get_object(self,*,Bucket,Key):return {'Body':io.BytesIO(self.values[Key])}
    def put_object(self,**kw):self.values[kw['Key']]=kw['Body'];self.puts.append(kw)

def test_staging_verifies_archive_and_encoder_before_upload():
    encoder=b'example-encoder';manifest=json.dumps({'sha256':hashlib.sha256(encoder).hexdigest()}).encode();buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as tar:
        for name,data in [('encoder.onnx',encoder),('model.json',manifest)]:
            info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
    archive=buffer.getvalue();s3=MemoryS3({'releases/test.tar.gz':archive});release={'model':{'uri':'s3://models/releases/test.tar.gz','sha256':'bad'}}
    with pytest.raises(ValueError,match='checksum'):stage(release,'models',s3)
    assert not s3.puts
    release['model']['sha256']=hashlib.sha256(archive).hexdigest()
    uri=stage(release,'models',s3)
    assert uri.startswith('s3://models/encoders/')
    assert len(s3.puts)==2 and all(p['IfNoneMatch']=='*' for p in s3.puts)

def test_dataset_validation_happens_before_any_upload(tmp_path):
    (tmp_path/'manifest.csv').write_text('file,sku,session,split\na.jpg,A,s1,train\n')
    s3=MemoryS3()
    with pytest.raises(ValueError,match='60'):upload(tmp_path,'models','ap-southeast-2',s3)
    assert s3.puts==[]

def test_dataset_upload_is_content_addressed_and_has_per_file_checksums(tmp_path):
    rows=['file,sku,session,split']
    for i in range(60):
        split=['train','validation','test'][i//20]
        name=f'item-{i}.jpg';(tmp_path/name).write_bytes(f'unit-test-file-{i}'.encode())
        rows.append(f'{name},SKU-{i%3},{split}-session,{split}')
    (tmp_path/'manifest.csv').write_text('\n'.join(rows)+'\n')
    s3=MemoryS3();result=upload(tmp_path,'models','ap-southeast-2',s3)
    assert result['imageCount']==60 and result['datasetUri'].startswith('s3://models/datasets/')
    prefix=result['datasetUri'].split('s3://models/')[1]
    index=json.loads(s3.values[prefix+'dataset-checksums.json'])
    assert index['item-0.jpg']==hashlib.sha256(b'unit-test-file-0').hexdigest()
    assert len(s3.puts)==62 and all(p['IfNoneMatch']=='*' for p in s3.puts)

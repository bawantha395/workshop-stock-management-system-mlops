"""Hands-off operation: nightly forecast, automatic photo-model decisions, and GitOps release."""
import io,json,sys,tarfile
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mlops'))
import auto_promote  # noqa: E402


def workflow(name):
    return yaml.safe_load((ROOT/'.github/workflows'/name).read_text())


def test_forecast_runs_every_night_for_every_deployed_environment():
    flow=workflow('forecast.yml');job=flow['jobs']['train']
    assert flow[True]['schedule']==[{'cron':'30 20 * * *'}]  # 02:00 Asia/Colombo
    assert '["dev","staging","prod"]' in job['strategy']['matrix']['environment']
    text=(ROOT/'.github/workflows/forecast.yml').read_text()
    assert "github.event_name == 'schedule' || inputs.publish" in text and 'nightly forecast skipped' in text
    exporter=(ROOT/'services/inventory/src/main/java/com/stocklane/inventory/service/ForecastExportService.java').read_text()
    assert '@Scheduled(cron="${app.forecast.export-cron:0 30 1 * * *}",zone="Asia/Colombo")' in exporter


def test_forecast_without_exported_history_is_a_quiet_no_op(tmp_path,monkeypatch):
    import run_forecast
    from botocore.exceptions import ClientError
    class S3:
        def get_object(self,**kw):raise ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
    sts=type('STS',(),{'get_caller_identity':lambda self:{'Account':'123'}})()
    monkeypatch.setattr(run_forecast.boto3,'client',lambda name,**kw:{'s3':S3(),'sagemaker':object(),'sts':sts}[name]);monkeypatch.chdir(tmp_path)
    report=run_forecast.execute({'region':'ap-southeast-2','model_bucket':'owned','account_id':'123'},publish=True)
    assert report['status']=='no_history' and report['published'] is False


class Registry:
    def __init__(self,current=None):self.updates=[];self.current=current
    def describe_model_package(self,ModelPackageName):
        return {'InferenceSpecification':{'Containers':[{'ModelDataUrl':'s3://models/training/current/model.tar.gz'}]}}
    def update_model_package(self,**kw):self.updates.append(kw)


class Store:
    def __init__(self,metrics):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as tar:
            raw=json.dumps(metrics).encode();info=tarfile.TarInfo('metrics.json');info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
        self.archive=data.getvalue()
    def get_object(self,Bucket,Key):return {'Body':io.BytesIO(self.archive)}


def report(f1,precision=.99):
    return {'modelPackageArn':'arn:new','metrics':{'qualityGatePassed':True,'f1':f1,'precision':precision}}


def test_first_passing_photo_model_replaces_the_baseline_automatically(monkeypatch):
    monkeypatch.setattr(auto_promote,'served_package',lambda environment:None)
    sm=Registry();result=auto_promote.decide(report(.7),'dev','ap-southeast-2',sm,Store({}))
    assert result['decision']=='approved' and sm.updates[0]['ModelApprovalStatus']=='Approved'
    assert 'baseline' in sm.updates[0]['ApprovalDescription']


def test_photo_model_must_beat_the_served_model_or_it_is_rejected(monkeypatch):
    monkeypatch.setattr(auto_promote,'served_package',lambda environment:'arn:current')
    sm=Registry();result=auto_promote.decide(report(.6),'prod','ap-southeast-2',sm,Store({'f1':.8}))
    assert result['decision']=='rejected' and sm.updates[0]['ModelApprovalStatus']=='Rejected'
    sm=Registry();assert auto_promote.decide(report(.9),'prod','ap-southeast-2',sm,Store({'f1':.8}))['decision']=='approved'
    sm=Registry();assert auto_promote.decide(report(.95,precision=.9),'prod','ap-southeast-2',sm,Store({'f1':.1}))['decision']=='rejected'


def test_approved_photo_models_are_released_through_gitops_in_every_environment():
    release=workflow('release-model.yml')
    assert release['jobs']['release']['uses']=='./.github/workflows/_release.yml'
    assert release['concurrency']['group']=='stocklane-aws'  # queues behind Deploy, never races it
    for name in ('train.yml','train-car-parts.yml'):
        text=(ROOT/'.github/workflows'/name).read_text();flow=workflow(name)
        assert 'mlops/auto_promote.py' in text and 'gh workflow run release-model.yml --ref main' in text
        assert flow['permissions']['actions']=='write'


def test_photo_model_retrains_weekly_on_confirmed_photos_only_when_they_changed():
    flow=workflow('train.yml');text=(ROOT/'.github/workflows/train.yml').read_text()
    assert flow[True]['schedule']==[{'cron':'0 21 * * 6'}]  # Sunday 02:30 Asia/Colombo
    assert '["dev","staging","prod"]' in flow['jobs']['train']['strategy']['matrix']['environment']
    assert 'mlops/workshop_dataset.py next' in text and 'mlops/workshop_dataset.py mark' in text
    import workshop_dataset
    from botocore.exceptions import ClientError
    class S3:
        def __init__(self):self.objects={}
        def get_object(self,Bucket,Key):
            if Key not in self.objects:raise ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
            return {'Body':io.BytesIO(self.objects[Key])}
        def put_object(self,Bucket,Key,Body,ContentType=None):self.objects[Key]=Body
    s3=S3()
    assert workshop_dataset.next_dataset(s3,'models')[0]==''
    s3.objects['datasets/workshop/latest.json']=json.dumps({'datasetUri':'s3://models/datasets/v1/','datasetVersion':'v1','images':80,'items':5}).encode()
    uri,_=workshop_dataset.next_dataset(s3,'models');assert uri=='s3://models/datasets/v1/'
    workshop_dataset.mark(s3,'models',uri)
    assert workshop_dataset.next_dataset(s3,'models')[0]==''


def test_confirmed_photos_export_in_the_trainers_dataset_format(monkeypatch):
    sys.path.insert(0,str(ROOT/'services/vision'))
    from app import dataset_export
    from dataset import validate_manifest
    refs=[{'product_id':f'p{k}','image_id':f'{k}{i:03d}abcdefabcdefabcdef.jpg','product':json.dumps({'sku':f'SKU-{k}'})} for k in range(5) for i in range(20)]
    refs+=refs[:3]  # the same photo indexed for another model version
    rows=dataset_export.manifest_rows(refs)
    assert len(rows)==100 and dataset_export.ready(rows) is None
    validate_manifest(rows)
    assert dataset_export.ready(rows[:30]).startswith('Need at least 60')
    class Store:
        class engine:
            @staticmethod
            def connect():
                class C:
                    def __enter__(self):return self
                    def __exit__(self,*a):return False
                    def execute(self,q):
                        class R:
                            def mappings(self_inner):return refs
                        return R()
                return C()
        refs=type('T',(),{'c':type('C',(),{'product_id':None,'image_id':None,'product':None})()})()
        def image(self,image_id):return b'jpeg-'+image_id.encode()
    puts={}
    class S3:
        def put_object(self,Bucket,Key,Body,**kw):puts[Key]=Body
    import app.dataset_export as module
    monkeypatch.setattr(module,'select',lambda *a:None)
    result=module.export(Store(),S3(),'models')
    assert result['exported'] and result['images']==100 and result['items']==5
    prefix='datasets/'+result['datasetVersion']+'/'
    assert prefix+'manifest.csv' in puts and prefix+'dataset-checksums.json' in puts
    assert json.loads(puts[prefix+'dataset-metadata.json'])['dataPurpose']=='workshop_confirmed'
    assert json.loads(puts['datasets/workshop/latest.json'])['datasetUri']=='s3://models/'+prefix


def test_counter_handover_is_wired_end_to_end():
    controller=(ROOT/'services/inventory/src/main/java/com/stocklane/inventory/controller/InventoryController.java').read_text()
    assert '@PostMapping("/api/inventory/people") @PreAuthorize("hasRole(\'OWNER\')")' in controller
    assert '@GetMapping("/api/inventory/people/{id}/handovers")' in controller
    migration=(ROOT/'services/inventory/src/main/resources/db/migration/V6__counter_handover.sql').read_text()
    assert 'receiver_id' in migration and 'CREATE TABLE people' in migration
    workshop=(ROOT/'services/workshop/src/main/java/com/stocklane/workshop/service/WorkshopService.java').read_text()
    assert '"RETURN".equals(p.get("kind"))&&p.get("job_id")==null' in workshop
    policy=(ROOT/'infra/terraform/modules/workload-identity/main.tf').read_text()
    assert 'Resource = "${local.models_arn}/datasets/*"' in policy

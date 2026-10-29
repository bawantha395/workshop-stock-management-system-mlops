"""Real-data preparation: UCI Online Retail II sales import and Kaggle car-part photos."""
import csv,io,json,sys,zipfile
from datetime import date,datetime,timedelta
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'mlops'),str(ROOT/'mlops'/'real_data')]
import online_retail  # noqa: E402
import car_parts_photos  # noqa: E402


def retail_rows(first=date(2009,12,1),last=date(2011,12,9)):
    day=first;n=0
    while day<=last:
        if day.weekday()!=5:
            for code,qty in (('85123A',12+3*(day.weekday()==3)),('22423',5),('47566',4),('POST',1),('21212',2)):
                n+=1;yield (str(n),code,'WHITE HANGING HEART T-LIGHT HOLDER' if code=='85123A' else 'Item '+code,qty,day,2.55)
            if day.weekday()==0:n+=1;yield ('C'+str(n),'22423','Item 22423',-5,day,2.55)
        day+=timedelta(days=1)
    yield ('X1','85123A','huge order',80995,last,2.08);yield ('C99','85123A','huge order',-80995,last,2.08)


def test_retail_import_keeps_real_values_and_aligns_whole_weeks_to_yesterday():
    sales,names,prices,first,last,count=online_retail.aggregate(retail_rows())
    assert 'POST' not in sales and count>3000
    assert date(2011,12,9) in sales['85123A'] and sales['85123A'][date(2011,12,9)]==12  # same-day cancellation nets out
    assert all(d.weekday()!=0 for d in sales['22423'])  # Monday: 5 sold, 5 cancelled
    codes=online_retail.select(sales,first,last,3)
    assert codes==['21212','47566','85123A']  # most selling days, then code
    payload=online_retail.build(sales,names,prices,first,last,codes)
    product=next(p for p in payload['products'] if p['sku']=='UCI-85123A')
    assert product['name']=='White Hanging Heart T-Light Holder' and payload['dateAlignment']=='whole-weeks-to-yesterday'
    assert {date.fromisoformat(s['date']):s['quantity'] for s in product['sales']}==sales['85123A']  # original dates and values
    assert product['openingDate']=='2009-11-30' and product['openingQuantity']>sum(sales['85123A'].values())
    today=date(2026,10,29);aligned,shift=online_retail.align(payload,today)
    end=date(2011,12,7)
    assert shift==5439 and shift%7==0 and 'dateAlignment' not in aligned and str(shift) in aligned['note']
    moved=next(p for p in aligned['products'] if p['sku']=='UCI-85123A')
    assert moved['sales'][-1]['date']=='2026-10-28' and moved['openingDate']==(date(2009,11,30)+timedelta(days=shift)).isoformat()
    assert {date.fromisoformat(s['date'])-timedelta(days=shift):s['quantity'] for s in moved['sales']}=={d:q for d,q in sales['85123A'].items() if d<=end}


def test_retail_preflight_runs_the_production_forecast_code():
    pytest.importorskip('sklearn')
    sales,names,prices,first,last,_=online_retail.aggregate(retail_rows())
    today=date(2026,10,29)
    payload=online_retail.build(sales,names,prices,first,last,online_retail.select(sales,first,last,3))
    result=online_retail.preflight(payload,today)
    assert result['historyUntilExclusive']=='2026-10-29' and sum(result['counts'].values())==3
    assert set(result['counts'])<= {'trained_ml','weekday_baseline','insufficient_history'}


def test_committed_real_file_is_the_full_uci_data_and_matches_the_web_alignment():
    folder=ROOT/'datasets/real-data/online-retail-ii'
    payload=json.loads((folder/'sales-history-import.json').read_text());summary=json.loads((folder/'preflight.json').read_text())
    assert summary['transactionsRead']==1067371 and summary['sourcePeriod']==['2009-12-01','2011-12-09']
    assert payload['license']=='CC BY 4.0' and '10.24432/C5CG6D' in payload['sourceUrl'] and len(payload['products'])==40
    assert len(payload['sourceSha256'])==64 and 'CC BY 4.0' in (folder/'ATTRIBUTION.txt').read_text()
    _,shift=online_retail.align(payload,date(2026,10,29))
    assert shift==5439  # apps/web/tests/history-import.test.mjs expects the same shift for this date


def test_retail_workbook_reader_uses_both_sheets():
    openpyxl=pytest.importorskip('openpyxl')
    book=openpyxl.Workbook();book.remove(book.active)
    for name,day in (('Year 2009-2010',datetime(2009,12,1,9)),('Year 2010-2011',datetime(2011,12,9,9))):
        sheet=book.create_sheet(name);sheet.append(['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country'])
        sheet.append(['489434','85048','15CM CHRISTMAS GLASS BALL 20 LIGHTS',12,day,6.95,13085,'United Kingdom'])
    workbook=io.BytesIO();book.save(workbook);archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('online_retail_II.xlsx',workbook.getvalue())
    rows=list(online_retail.read_rows(archive.getvalue()))
    assert [r[4] for r in rows]==[date(2009,12,1),date(2011,12,9)] and rows[0][1]=='85048' and rows[0][3]==12


def car_archive(path,per_split={'train':8,'valid':6,'test':6}):
    from PIL import Image
    with zipfile.ZipFile(path,'w') as z:
        for s,(split,count) in enumerate(per_split.items()):
            for k,part in enumerate(['BRAKE PAD','SPARK PLUG','OIL FILTER','RADIATOR']):
                for i in range(count):
                    image=Image.new('RGB',(64,64),(k*60,i*20,s*80));data=io.BytesIO();image.save(data,'PNG')
                    z.writestr(f'car parts/{split}/{part}/{i}.png',data.getvalue())
        z.writestr('car parts/test/BRAKE PAD/copy.png',z.read('car parts/valid/BRAKE PAD/0.png'))
        z.writestr('car parts/README.txt','not an image')


def test_car_part_archive_becomes_a_reviewed_real_dataset(tmp_path):
    from dataset import validate_manifest
    car_archive(tmp_path/'archive.zip')
    summary=car_parts_photos.build(tmp_path/'archive.zip',tmp_path/'out',5,set(),'Kaggle: 50 Types of Car Parts','https://www.kaggle.com/datasets/example/parts','CC0: Public Domain',root='car parts')
    assert summary['bySplit']=={'train':20,'validation':24,'test':24} and summary['duplicatesDropped']==1
    rows=list(csv.DictReader((tmp_path/'out/photos/manifest.csv').open()))
    validate_manifest(rows)
    assert len({r['session'] for r in rows})==len(rows) and {r['sku'] for r in rows}=={'CP-BRAKE-PAD','CP-SPARK-PLUG','CP-OIL-FILTER','CP-RADIATOR'}
    metadata=json.loads((tmp_path/'out/photos/dataset-metadata.json').read_text())
    assert metadata['synthetic'] is False and metadata['benchmarkOnly'] is False and metadata['dataPurpose']=='reference_catalogue'
    assert metadata['license']=='CC0: Public Domain' and len(metadata['archiveSha256'])==64


def test_car_part_dataset_upload_keeps_its_provenance(tmp_path):
    from upload_dataset import upload
    car_archive(tmp_path/'archive.zip')
    car_parts_photos.build(tmp_path/'archive.zip',tmp_path/'out',5,set(),'Kaggle','https://www.kaggle.com/datasets/example/parts','CC0')
    class S3:
        def __init__(self):self.keys={}
        def put_object(self,Bucket,Key,Body,IfNoneMatch):self.keys[Key]=Body
    s3=S3();result=upload(tmp_path/'out/photos','bucket','ap-southeast-2',s3)
    prefix='datasets/'+result['datasetVersion']+'/'
    assert prefix+'dataset-metadata.json' in s3.keys and prefix+'manifest.csv' in s3.keys
    assert 'dataset-metadata.json' in json.loads(s3.keys[prefix+'dataset-checksums.json'])


def test_large_splits_sample_pairs_uniformly_and_small_splits_keep_every_pair():
    pytest.importorskip('numpy')
    from train import pair_indexes
    assert pair_indexes(10)==[(i,j) for i in range(10) for j in range(i+1,10)]
    sampled=pair_indexes(400)
    assert len(sampled)==20000==len(set(sampled)) and sampled==pair_indexes(400)
    assert max(i for i,_ in sampled)>350 and all(i<j for i,j in sampled)


def test_owner_import_endpoint_is_wired_and_documented():
    controller=(ROOT/'services/inventory/src/main/java/com/stocklane/inventory/controller/InventoryController.java').read_text()
    assert '@PostMapping("/api/inventory/imports/sales-history") @PreAuthorize("hasRole(\'OWNER\')")' in controller
    web=(ROOT/'apps/web/src/StockReport.tsx').read_text()
    assert '/api/inventory/imports/sales-history' in web and 'the license allows this use' in web
    docs=(ROOT/'docs/REAL_DATA.md').read_text()
    for text in ('10.24432/C5CG6D','CC BY 4.0','whole weeks','opening balance','datasets/real-data/online-retail-ii','KAGGLE_KEY','Apache 2.0'):
        assert text in docs


def test_car_part_workflow_downloads_with_secrets_and_gates_before_paid_training():
    import yaml
    text=(ROOT/'.github/workflows/train-car-parts.yml').read_text();flow=yaml.safe_load(text)
    steps=flow['jobs']['train']['steps'];names=[s.get('name','') for s in steps]
    assert flow['jobs']['train']['environment']=='aws-training' and flow['jobs']['train']['if']=="github.ref == 'refs/heads/main'"
    download=next(s for s in steps if s.get('name','').startswith('Download'))
    assert download['env']['KAGGLE_KEY']=='${{ secrets.KAGGLE_KEY }}' and 'set -x' not in download['run'] and 'echo "$KAGGLE_KEY' not in download['run']
    assert names.index('Build the reviewed dataset, run the quality gate, upload')<names.index('Train on SageMaker and register pending approval (only when the local gate passed)')
    assert "if not summary['preflight'].get('qualityGatePassed')" in text and 'role: github-training' in text

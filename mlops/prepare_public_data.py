"""Prepare checksum-pinned real public imagery and monthly car-parts sales.

The lock file names the selected original images. No generated/augmented photos,
imputed history, moved dates or invented manufacturer/SKU mapping is introduced.
Public data is a benchmark and never an automatic live workshop release.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import urllib.parse
import urllib.request
import zipfile

from PIL import Image

ROOT=Path(__file__).resolve().parent
HOSTS={'amazon-berkeley-objects.s3.us-east-1.amazonaws.com','zenodo.org'}


def download(url,digest,cache,max_bytes=8*1024*1024):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in HOSTS:raise ValueError('Unapproved public dataset host')
    path=Path(cache)/digest;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raw=path.read_bytes()
    else:
        with urllib.request.urlopen(url,timeout=45) as response:
            if urllib.parse.urlsplit(response.geturl()).hostname not in HOSTS:raise ValueError('Unexpected dataset redirect')
            raw=response.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError('Public source exceeds its size limit')
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Public source checksum changed; review before updating the lock')
        path.write_bytes(raw)
    if len(raw)>max_bytes or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Cached public source failed verification')
    return raw


def parse_monthly(raw,max_series=64):
    if not 3<=max_series<=256:raise ValueError('Select 3 to 256 series')
    text=raw.decode('utf-8-sig')
    if '@frequency monthly' not in text:raise ValueError('The source must remain monthly')
    records=[];missing=0;insufficient=0
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith(('#','@')):continue
        name,start,encoded=line.split(':',2);parts=encoded.split(',')
        if '?' in parts:missing+=1;continue
        values=[float(v) for v in parts]
        if any(not math.isfinite(v) or v<0 for v in values):raise ValueError('Invalid source sales')
        if len(values)<48 or sum(v>0 for v in values[:-18])<6:insufficient+=1;continue
        records.append({'id':name,'start':start.split()[0],'values':values})
    # Selection uses only training-period availability/activity, never test error.
    # Source file order is not a representative sample. A fixed ID hash selects
    # across the archive without inspecting held-out demand or model errors.
    records.sort(key=lambda row:hashlib.sha256(row['id'].encode()).hexdigest())
    selected=records[:max_series]
    if len(selected)<max_series:raise ValueError('Too few complete eligible real histories')
    return selected,{'excludedMissingSeries':missing,'excludedSparseTrainingSeries':insufficient,
        'eligibleCompleteSeries':len(records),'selectedSeries':len(selected)}


def prepare(destination,lock_path=None,cache=None):
    lock_path=Path(lock_path or ROOT/'public-data-sources.lock.json')
    raw_lock=lock_path.read_bytes();lock=json.loads(raw_lock)
    if lock.get('purpose')!='public_data_benchmark' or lock.get('syntheticData') is not False:
        raise ValueError('Expected a real public-data source lock')
    target=Path(destination);target.mkdir(parents=True,exist_ok=True)
    cache=Path(cache or target.parent/'public-download-cache')
    images=lock['photo']['images'];seen_ids=set();seen_hashes=set();product_splits={}
    rows=[];checks={}
    def fetch(record):
        raw=download(record['url'],record['sha256'],cache)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {'JPEG','PNG'} or min(image.size)<32:raise ValueError('Invalid source image')
            image.verify()
        return record,raw
    with ThreadPoolExecutor(max_workers=6) as pool:
        for record,raw in pool.map(fetch,images):
            if record['sourceImageId'] in seen_ids or record['sha256'] in seen_hashes:raise ValueError('Duplicate public photo')
            seen_ids.add(record['sourceImageId']);seen_hashes.add(record['sha256'])
            product=record['productId'];split=record['split']
            if split not in {'train','validation','test'}:raise ValueError('Invalid public split')
            if product in product_splits and product_splits[product]!=split:raise ValueError('Public product identity leaks across splits')
            product_splits[product]=split
            relative=Path(record['file'])
            if relative.is_absolute() or '..' in relative.parts or '\\' in record['file']:raise ValueError('Invalid source image path')
            path=target/'photos'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            rows.append({'file':relative.as_posix(),'sku':product,'session':'source-product:'+product,'split':split})
            checks[relative.as_posix()]=record['sha256']
    from dataset import validate_manifest
    validate_manifest(rows)
    with (target/'photos/manifest.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['file','sku','session','split']);writer.writeheader();writer.writerows(rows)
    checks['manifest.csv']=hashlib.sha256((target/'photos/manifest.csv').read_bytes()).hexdigest()
    (target/'photos/dataset-checksums.json').write_text(json.dumps(checks,sort_keys=True))
    metadata={'synthetic':False,'realData':True,'benchmarkOnly':True,'dataPurpose':'public_data_benchmark',
        'source':'Amazon Berkeley Objects','sourceUrl':lock['photo']['sourceUrl'],
        'sourceLockSha256':hashlib.sha256(raw_lock).hexdigest(),'license':lock['photo']['license'],
        'captureSessionsProvided':False,'splitGrouping':'product_identity',
        'note':'session stores a product grouping key, not a claimed physical capture session.'}
    (target/'photos/dataset-metadata.json').write_text(json.dumps(metadata,indent=2))
    products={r['productId']:{k:r[k] for k in ('productId','title','productType')} for r in images}
    (target/'photo-products.json').write_text(json.dumps(list(products.values()),indent=2,ensure_ascii=False))
    history=lock['history']
    zipped=download(history['downloadUrl'],history['sha256'],cache,max_bytes=1024*1024)
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        member=archive.getinfo(history['member'])
        if member.file_size>2*1024*1024:raise ValueError('History member is unexpectedly large')
        series,selection=parse_monthly(archive.read(member),history['maxSeries'])
    snapshot={'schemaVersion':1,'task':'monthly_car_parts_benchmark','frequency':'monthly',
        'benchmarkOnly':True,'syntheticData':False,'productionEligible':False,
        'source':history['sourceUrl'],'sourceSha256':history['sha256'],
        'availability':'not provided by the source; no stock availability is inferred',
        'selection':selection,'series':series}
    folder=target/'monthly-history';folder.mkdir(exist_ok=True)
    (folder/'history.json').write_text(json.dumps(snapshot,separators=(',',':')))
    from datetime import date
    with (folder/'observed-monthly-sales.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['sourceSeriesId','month','observedSales'])
        for row in series:
            start=date.fromisoformat(row['start'])
            for i,value in enumerate(row['values']):
                period=start.year*12+start.month-1+i
                writer.writerow([row['id'],str(date(period//12,period%12+1,1)),value])
    (target/'source-lock.json').write_bytes(raw_lock)
    license_text=download(lock['photo']['licenseFileUrl'],lock['photo']['licenseSha256'],cache,max_bytes=64000)
    (target/'LICENSE-CC-BY-4.0.txt').write_bytes(license_text)
    credits='''# Public dataset attribution

Images: Amazon Berkeley Objects (ABO), Amazon.com. Accessed 2026-10-27 from
https://registry.opendata.aws/amazon-berkeley-objects/.
See Collins et al., ABO, CVPR 2022 and the official source for dataset authorship.

Monthly history: Godahewa, Bergmeir, Webb, Hyndman and Montero-Manso,
Monash Time Series Forecasting Repository, Car Parts Dataset (with Missing Values),
DOI 10.5281/zenodo.4656022; original R expsmooth carparts data.

Both publishers identify their releases as CC BY 4.0. Sources and checksums are
listed in source-lock.json. This subset selects and renames original images,
builds product-disjoint manifests, and selects complete monthly histories.
Image bytes and observed monthly values are preserved. Missing values are not
replaced with zero. No endorsement by the dataset publishers is implied.
'''
    (target/'ATTRIBUTION.md').write_text(credits)
    return {'syntheticData':False,'benchmarkOnly':True,'productionEligible':False,
        'photoImages':len(rows),'photoProducts':len(products),'photoSplitGrouping':'product_identity',
        'monthlySeries':len(series),'monthlyObservations':sum(len(r['values']) for r in series),
        'frequency':'monthly','originalPeriod':[history['originalStart'],history['originalEnd']],
        'sourceLockSha256':hashlib.sha256(raw_lock).hexdigest(),**selection}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='artifacts/public-training-data')
    parser.add_argument('--cache',default='artifacts/public-download-cache')
    args=parser.parse_args();print(json.dumps(prepare(args.output,cache=args.cache),indent=2))

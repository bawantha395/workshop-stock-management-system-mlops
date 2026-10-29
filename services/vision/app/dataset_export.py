"""Self-learning photo model: export the staff-confirmed photos as a reviewed dataset.

Every photo a person confirmed (a new item's photo, or a part identified by photo at the
storeroom counter) is a reference image. Once a week this turns them into the same reviewed
dataset format the production training uses (manifest.csv, checksums, provenance) and writes
it to the models bucket under a content-addressed prefix, plus datasets/workshop/latest.json.
The scheduled "Train reviewed workshop model" workflow trains on it and promotes the model
only if it beats the one in use. Nothing is exported until the dataset meets the same minimum
the trainer enforces, so an early shop simply waits.
"""
import csv,hashlib,io,json,logging
from datetime import datetime,timezone
from sqlalchemy import select

log=logging.getLogger(__name__)
MAX_PER_ITEM=40
MAX_IMAGES=2000
POINTER='datasets/workshop/latest.json'


def split_of(image_id):
    bucket=int(hashlib.sha256(image_id.encode()).hexdigest(),16)%10
    return 'train' if bucket<6 else 'validation' if bucket<8 else 'test'


def manifest_rows(references):
    """One row per confirmed photo; each photo is its own capture session, split by a stable hash."""
    seen=set();per_item={};rows=[]
    for ref in sorted(references,key=lambda r:(r['product_id'],r['image_id'])):
        if (ref['product_id'],ref['image_id']) in seen:continue
        seen.add((ref['product_id'],ref['image_id']))
        sku=json.loads(ref['product']).get('sku') or ref['product_id']
        if per_item.get(sku,0)>=MAX_PER_ITEM:continue
        per_item[sku]=per_item.get(sku,0)+1
        rows.append({'file':'images/'+ref['image_id'],'sku':sku,'session':'photo:'+ref['image_id'][:16],'split':split_of(ref['image_id'])})
    return rows[:MAX_IMAGES]


def ready(rows):
    """Same minimum as mlops/dataset.py: 60 photos, and 15 photos over 3 items in every split."""
    if len(rows)<60:return 'Need at least 60 confirmed photos (have '+str(len(rows))+')'
    for split in ('train','validation','test'):
        group=[r for r in rows if r['split']==split]
        if len(group)<15 or len({r['sku'] for r in group})<3:return 'Not enough confirmed photos for the '+split+' split yet'
    return None


def export(store,s3,bucket,now=None):
    with store.engine.connect() as c:
        references=[dict(r) for r in c.execute(select(store.refs.c.product_id,store.refs.c.image_id,store.refs.c.product)).mappings()]
    rows=manifest_rows(references);problem=ready(rows)
    if problem:
        log.info('Training dataset not exported: %s',problem);return {'exported':False,'reason':problem}
    files={}
    for row in rows:files[row['file']]=store.image(row['file'].removeprefix('images/'))
    manifest=io.StringIO();writer=csv.DictWriter(manifest,fieldnames=['file','sku','session','split']);writer.writeheader();writer.writerows(rows)
    files['manifest.csv']=manifest.getvalue().encode()
    files['dataset-metadata.json']=json.dumps({'dataPurpose':'workshop_confirmed',
        'source':'Stocklane staff-confirmed photos','captureSessionsProvided':False,
        'note':'Every photo was confirmed by a person (new item or counter handover).'},indent=2).encode()
    checks={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    index=json.dumps(checks,sort_keys=True).encode();version=hashlib.sha256(index).hexdigest()
    files['dataset-checksums.json']=index
    prefix='datasets/'+version+'/'
    for name,data in files.items():
        try:s3.put_object(Bucket=bucket,Key=prefix+name,Body=data,IfNoneMatch='*')
        except Exception as error:
            if getattr(error,'response',{}).get('Error',{}).get('Code') not in {'PreconditionFailed','412'}:raise
    pointer={'datasetUri':'s3://'+bucket+'/'+prefix,'datasetVersion':version,'images':len(rows),
        'items':len({r['sku'] for r in rows}),'exportedAt':(now or datetime.now(timezone.utc)).isoformat()}
    s3.put_object(Bucket=bucket,Key=POINTER,Body=json.dumps(pointer).encode(),ContentType='application/json')
    log.info('Training dataset exported version=%s images=%d',version,len(rows))
    return {'exported':True,**pointer}

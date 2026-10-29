#!/usr/bin/env python3
"""Build a reviewed photo dataset from a downloaded Kaggle car-part image archive.

The archive must contain train/, valid/ (or validation/) and test/ folders with one
sub-folder per part type, for example the Kaggle dataset "50 Types of Car Parts".
The workflow "Train photo model on real car-part photos" downloads it with your Kaggle API
token and runs this script; you can also run it yourself on a downloaded archive.

What this script does, and every choice it makes:
  * each part-type folder becomes one stock item (SKU CP-<FOLDER NAME>);
  * the archive's own train/validation/test split is kept, so test photos are never seen
    in training;
  * the photos come from many different sources, so each photo is its own capture
    session; byte-identical duplicates are dropped (first split wins);
  * at most --per-class-train training photos per part keep the dataset under the 2000
    image upload limit; validation and test photos are all kept;
  * provenance (source, URL, license, archive SHA-256) is written to dataset-metadata.json.

It then runs the same training code SageMaker runs, locally, and prints the quality-gate
result. With --upload it stores the dataset in your models bucket and prints the
dataset URI for the "Train and register model" workflow.

CloudShell:
  python3 -m pip install onnx opencv-python-headless pillow scikit-learn boto3
  python3 scripts/download_model.py
  python3 mlops/real_data/car_parts_photos.py --archive ~/archive.zip \
      --source-url https://www.kaggle.com/datasets/<owner>/<dataset> --license "<license shown on Kaggle>"
"""
import argparse,csv,hashlib,io,json,re,sys,tempfile,zipfile
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPLITS={'train':'train','valid':'validation','validation':'validation','test':'test'}
IMAGE=re.compile(r'\.(jpe?g|png)$',re.I)


def entries(archive,root=None):
    """(split, part type, member name) for every image under <root>/<split>/<part type>/."""
    found=[];roots=set()
    for name in archive.namelist():
        parts=name.split('/')
        if len(parts)<3 or not IMAGE.search(parts[-1]):continue
        split=SPLITS.get(parts[-3].lower())
        if not split:continue
        top='/'.join(parts[:-3]);roots.add(top)
        if root is None or top==root.strip('/'):found.append((split,parts[-2].strip(),name))
    if root is None and len(roots)>1:raise ValueError('The archive has several copies; choose one with --root: '+', '.join(sorted(repr(r) for r in roots)))
    if not found:raise ValueError('No train/valid/test photos found'+(f' under {root!r}; available: '+', '.join(sorted(repr(r) for r in roots)) if root else ''))
    return found


def sku(part):
    slug=re.sub(r'[^A-Z0-9]+','-',part.upper()).strip('-')
    if not slug:raise ValueError(f'Unusable part folder name: {part!r}')
    return 'CP-'+slug[:60]


def build(archive_path,out,per_class_train,classes,source_name,source_url,license_name,root=None):
    raw=Path(archive_path).read_bytes();archive_sha=hashlib.sha256(raw).hexdigest()
    out=Path(out);(out/'photos').mkdir(parents=True,exist_ok=True)
    rows=[];checks={};seen=set();kept=defaultdict(int);duplicates=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        found=sorted(entries(archive,root),key=lambda e:(['train','validation','test'].index(e[0]),e[1],e[2]))
        parts=sorted({part for _,part,_ in found})
        if classes:
            missing=sorted(set(classes)-set(parts))
            if missing:raise ValueError('Part folders not found: '+', '.join(missing))
            parts=[p for p in parts if p in classes]
        if len(parts)<3:raise ValueError('Need at least 3 part types; is this the right archive?')
        skus={part:sku(part) for part in parts}
        if len(set(skus.values()))!=len(skus):raise ValueError('Two part folders map to the same SKU')
        for split,part,name in found:
            if part not in skus:continue
            if split=='train' and kept[(split,part)]>=per_class_train:continue
            data=archive.read(name);digest=hashlib.sha256(data).hexdigest()
            if digest in seen:duplicates+=1;continue
            seen.add(digest);kept[(split,part)]+=1
            relative=f'{split}/{skus[part]}/{digest[:16]}{Path(name).suffix.lower()}'
            target=out/'photos'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            rows.append({'file':relative,'sku':skus[part],'session':'photo:'+digest[:16],'split':split});checks[relative]=digest
    with (out/'photos'/'manifest.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['file','sku','session','split']);writer.writeheader();writer.writerows(rows)
    metadata={'synthetic':False,'realData':True,'benchmarkOnly':False,'dataPurpose':'reference_catalogue',
        'source':source_name,'sourceUrl':source_url,'license':license_name,'archiveSha256':archive_sha,
        'captureSessionsProvided':False,'splitSource':'archive train/valid/test folders',
        'note':'Each part type is one stock item. Photos come from many sources, so each photo is its own session.'}
    (out/'photos'/'dataset-metadata.json').write_text(json.dumps(metadata,indent=2))
    (out/'photos'/'parts.json').write_text(json.dumps([{'sku':skus[p],'partType':p} for p in parts],indent=2))
    counts={split:sum(1 for r in rows if r['split']==split) for split in ('train','validation','test')}
    return {'archiveSha256':archive_sha,'partTypes':len(parts),'images':len(rows),'bySplit':counts,'duplicatesDropped':duplicates}


def preflight(dataset,encoder):
    sys.path[:0]=[str(ROOT/'mlops'),str(ROOT/'services'/'vision')]
    from dataset import validate_manifest
    from train import train
    validate_manifest(list(csv.DictReader((Path(dataset)/'manifest.csv').open())))
    with tempfile.TemporaryDirectory() as output:
        try:return train(dataset,encoder,output,job_name='cloudshell-preflight')
        except ValueError as error:
            metrics=Path(output)/'metrics.json'
            result=json.loads(metrics.read_text()) if metrics.exists() else {'qualityGatePassed':False}
            result['gateMessage']=str(error);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive',required=True,help='Kaggle archive .zip you downloaded')
    parser.add_argument('--source-url',required=True,help='Kaggle dataset page you downloaded it from')
    parser.add_argument('--license',required=True,help='License exactly as shown on the dataset page')
    parser.add_argument('--source-name',default='Kaggle: 50 Types of Car Parts')
    parser.add_argument('--out',default='real-data/car-parts')
    parser.add_argument('--per-class-train',type=int,default=20)
    parser.add_argument('--classes',nargs='*',help='Optional part folder names to keep (default: all)')
    parser.add_argument('--root',help='Folder inside the archive that holds train/valid/test, when it has several copies')
    parser.add_argument('--encoder',default=str(ROOT/'models'/'baseline'))
    parser.add_argument('--skip-preflight',action='store_true')
    parser.add_argument('--upload',action='store_true',help='Upload to the models bucket after the preflight')
    parser.add_argument('--bucket',help='Models bucket, for example stocklane-dev-models-<account id>')
    parser.add_argument('--region',default='ap-southeast-2')
    args=parser.parse_args()
    if not args.source_url.startswith('https://'):parser.error('--source-url must be the https dataset page')
    if not 5<=args.per_class_train<=200:parser.error('--per-class-train must be 5 to 200')
    if args.upload and not args.bucket:parser.error('--upload needs --bucket')
    summary=build(args.archive,args.out,args.per_class_train,set(args.classes or []),args.source_name,args.source_url,args.license,args.root)
    dataset=Path(args.out)/'photos'
    if not args.skip_preflight:
        if not (Path(args.encoder)/'encoder.onnx').exists():parser.error('Run python3 scripts/download_model.py first (or pass --skip-preflight)')
        print('Running the photo quality gate locally on',summary['images'],'images...',flush=True)
        summary['preflight']=preflight(dataset,args.encoder)
    if args.upload:
        sys.path.insert(0,str(ROOT/'mlops'))
        from upload_dataset import upload
        summary['upload']=upload(dataset,args.bucket,args.region)
    (Path(args.out)/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
    if 'upload' in summary:print('\nRun GitHub Actions -> "Train and register model" with dataset_uri =',summary['upload']['datasetUri'])

if __name__=='__main__':main()

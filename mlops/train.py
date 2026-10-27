"""Train a same-SKU pair calibrator on frozen MobileNet image embeddings.

The ImageNet encoder is pretrained, not fine-tuned in this milestone. The
logistic calibrator is trained on reviewed workshop examples. No fabricated
dataset or synthetic images may be used to pass the release quality gate.
"""
import csv,hashlib,itertools,json,os,shutil
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score,recall_score,f1_score
from app.encoder import Encoder

from dataset import validate_manifest

def pairs(rows,vectors):
    features=[];labels=[]
    for i,j in itertools.combinations(range(len(rows)),2):
        features.append([float(np.dot(vectors[i],vectors[j]))]);labels.append(int(rows[i]['sku']==rows[j]['sku']))
        if len(labels)>=20000:break
    if len(set(labels))!=2:raise ValueError('Both same-SKU and different-SKU pairs are needed')
    return np.array(features),np.array(labels)

def train(dataset_dir,encoder_dir,output_dir,job_name='local-calibration',demo_mode=False,benchmark_mode=False):
    dataset_dir=Path(dataset_dir).resolve();output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    metadata=dataset_dir/'dataset-metadata.json'
    provenance=json.loads(metadata.read_text()) if metadata.exists() else {}
    synthetic=provenance.get('synthetic') is True
    benchmark=provenance.get('benchmarkOnly') is True
    if demo_mode and benchmark_mode:raise ValueError('Select one training purpose')
    if synthetic and not demo_mode:raise ValueError('Synthetic fixtures require the demo training workflow; they cannot train a production candidate')
    if demo_mode and not synthetic:raise ValueError('Demo mode requires an explicitly marked synthetic dataset')
    if benchmark and not benchmark_mode:raise ValueError('Public benchmark images require the public-data workflow')
    if benchmark_mode and (not benchmark or synthetic):raise ValueError('Benchmark mode requires marked real public images')
    manifest=dataset_dir/'manifest.csv';rows=list(csv.DictReader(manifest.open()));validate_manifest(rows)
    checksums=json.loads((dataset_dir/'dataset-checksums.json').read_text()) if (dataset_dir/'dataset-checksums.json').exists() else None
    encoder=Encoder(encoder_dir);vectors={};seen_hashes=set()
    for row in rows:
        p=(dataset_dir/row['file']).resolve()
        if dataset_dir not in p.parents or not p.is_file():raise ValueError('Image path must stay inside the reviewed dataset')
        raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if checksums and checksums.get(row['file'])!=digest:raise ValueError('Reviewed dataset checksum mismatch')
        if digest in seen_hashes:raise ValueError('Duplicate image bytes in the dataset; deduplicate before training')
        seen_hashes.add(digest);vectors[row['file']]=encoder.encode(raw)
    data={}
    for split in ['train','validation','test']:
        group=[r for r in rows if r['split']==split];data[split]=pairs(group,[vectors[r['file']] for r in group])
    clf=LogisticRegression(class_weight='balanced',random_state=42,max_iter=1000).fit(*data['train'])
    meaningful=float(clf.coef_[0][0])>0
    if not meaningful and not benchmark:raise ValueError('The dataset does not support meaningful same-SKU similarity calibration')
    vx,vy=data['validation'];scores=clf.predict_proba(vx)[:,1]
    chosen=None
    for threshold in np.linspace(.5,.999,100):
        pred=scores>=threshold
        if pred.sum()>=10 and precision_score(vy,pred,zero_division=0)>=.98:
            chosen=float(threshold);break
    validation_passed=chosen is not None
    if chosen is None:
        if not benchmark:raise ValueError('Validation precision gate failed. Collect clearer examples; do not lower it silently.')
        chosen=.5  # Report a rejected benchmark candidate; never relax a release gate.
    tx,ty=data['test'];pred=clf.predict_proba(tx)[:,1]>=chosen
    metrics={'precision':float(precision_score(ty,pred,zero_division=0)),'recall':float(recall_score(ty,pred,zero_division=0)),'f1':float(f1_score(ty,pred,zero_division=0)),'testPairs':len(ty),'testPredictedPositive':int(pred.sum()),'imageCount':len(rows),'datasetSha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'encoderSha256':encoder.sha,'job':job_name}
    metrics['qualityGatePassed']=meaningful and validation_passed and metrics['precision']>=.98 and metrics['recall']>=.5 and metrics['testPredictedPositive']>=10
    metrics['syntheticData']=synthetic
    metrics['benchmarkOnly']=benchmark
    metrics['validationGatePassed']=validation_passed
    if benchmark:metrics['sourceLockSha256']=provenance['sourceLockSha256']
    (output_dir/'metrics.json').write_text(json.dumps(metrics,indent=2))
    print(json.dumps(metrics),flush=True)
    if not metrics['qualityGatePassed'] and not benchmark:raise ValueError('Independent test quality gate failed; this bundle must not be registered or released')
    shutil.copy2(Path(encoder_dir)/'encoder.onnx',output_dir/'encoder.onnx')
    version=('public-calibrator-' if benchmark else 'demo-calibrator-' if synthetic else 'workshop-calibrator-')+hashlib.sha256((manifest.read_text()+job_name).encode()).hexdigest()[:12]
    model=dict(encoder.manifest,version=version,workshopCalibrated=not(synthetic or benchmark),syntheticData=synthetic,benchmarkOnly=benchmark,autoPosting=False)
    model['calibration']={'coefficient':float(clf.coef_[0][0]),'intercept':float(clf.intercept_[0]),'threshold':chosen}
    (output_dir/'model.json').write_text(json.dumps(model,indent=2))
    return metrics

if __name__=='__main__':
    train(os.environ.get('SM_CHANNEL_DATASET','data/reviewed'),os.environ.get('SM_CHANNEL_ENCODER','models/baseline'),os.environ.get('SM_MODEL_DIR','artifacts/model'),os.environ.get('TRAINING_JOB_NAME','local-calibration'))

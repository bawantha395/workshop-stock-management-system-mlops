#!/usr/bin/env python3
"""Fetch a 14 MB pretrained model, verify bytes, export its 1280-D encoder.

ONNX Model Zoo MobileNetV2 (ImageNet). Not a workshop-trained classifier.
"""
from pathlib import Path
import hashlib
import json
import tempfile
import urllib.request
import onnx

ROOT=Path(__file__).resolve().parent.parent
URL='https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/mobilenet/model/mobilenetv2-12.onnx'
SHA='c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5'

def prepare(source=None,destination=None):
    target=Path(destination) if destination else ROOT/'models'/'baseline'
    target.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(source) if source else Path(tmp)/'upstream.onnx'
        if not source:urllib.request.urlretrieve(URL,path)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise RuntimeError('Upstream model checksum mismatch')
        onnx.utils.extract_model(str(path),str(target/'encoder.onnx'),['input'],['472'],check_model=False)
        model=onnx.load(target/'encoder.onnx')
        del model.graph.output[:]
        model.graph.output.append(onnx.helper.make_tensor_value_info('472',onnx.TensorProto.FLOAT,['batch_size',1280]))
        onnx.checker.check_model(model)
        onnx.save(model,target/'encoder.onnx')
    digest=hashlib.sha256((target/'encoder.onnx').read_bytes()).hexdigest()
    manifest={'version':'mobilenetv2-imagenet-baseline-v1','sha256':digest,'dimension':1280,'preprocessing':'rgb-exif-resize256-center224-imagenet-v1','workshopCalibrated':False,'autoPosting':False,'source':URL,'sourceSha256':SHA}
    (target/'model.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Installed encoder:',target,'sha256:',digest)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--source');parser.add_argument('--destination')
    args=parser.parse_args();prepare(args.source,args.destination)

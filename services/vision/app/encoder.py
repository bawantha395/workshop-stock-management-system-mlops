import hashlib
import io
import json
from pathlib import Path
import warnings
import numpy as np
import cv2
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 20_000_000

def decode(data: bytes):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {'JPEG','PNG'}:raise ValueError('Use JPEG or PNG')
                source.load()
                return ImageOps.exif_transpose(source).convert('RGB')
    except (Image.DecompressionBombError,Image.DecompressionBombWarning) as e:
        raise ValueError('Image pixel dimensions are too large') from e

class Encoder:
    def __init__(self, model_dir):
        folder = Path(model_dir)
        self.manifest = json.loads((folder / 'model.json').read_text())
        path = folder / 'encoder.onnx'
        self.sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.sha != self.manifest['sha256']:
            raise RuntimeError('Model checksum does not match its release manifest')
        cv2.setNumThreads(2)
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        import threading
        self.lock = threading.Lock()
        self.version = self.manifest['version'] + ':' + self.sha[:12]
        self.preprocessing = 'rgb-exif-resize256-center224-imagenet-v1'

    def encode(self, data):
        im = decode(data)
        w, h = im.size
        if min(w, h) < 32:
            raise ValueError('Use a clear image at least 32 pixels wide and high')
        scale = 256 / min(w, h)
        im = im.resize((round(w*scale), round(h*scale)), Image.Resampling.BILINEAR)
        left, top = (im.width-224)//2, (im.height-224)//2
        arr = np.asarray(im.crop((left, top, left+224, top+224)), dtype=np.float32)/255
        arr = (arr - np.array([.485,.456,.406],dtype=np.float32))/np.array([.229,.224,.225],dtype=np.float32)
        arr = np.transpose(arr, (2,0,1))[None].astype(np.float32)
        with self.lock:
            self.net.setInput(arr)
            out = self.net.forward().reshape(-1)
        norm = float(np.linalg.norm(out))
        if not np.isfinite(out).all() or norm <= 0 or len(out) != 1280:
            raise ValueError('Invalid encoder output')
        return (out/norm).tolist()

    def same_sku_estimate(self,similarity):
        calibration=self.manifest.get('calibration')
        if not calibration:return None
        logit=calibration['coefficient']*float(similarity)+calibration['intercept']
        return round(float(1/(1+np.exp(-np.clip(logit,-50,50)))),4)

    def accepts(self, similarity, baseline_threshold):
        calibration = self.manifest.get('calibration')
        if not calibration:
            return similarity >= baseline_threshold
        logit = calibration['coefficient'] * float(similarity) + calibration['intercept']
        estimate = float(1 / (1 + np.exp(-np.clip(logit, -50, 50))))
        return estimate >= calibration['threshold']

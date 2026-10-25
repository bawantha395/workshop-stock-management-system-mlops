#!/usr/bin/env python3
"""Controlled-tray capture agent. Captures create pending evidence, never stock.

Start with an EMPTY tray. Remove the item fully between captures. Detection
thresholds require testing on the actual camera, tray and lighting.
"""
import argparse,json,os,sqlite3,threading,time,uuid
from pathlib import Path
from urllib.parse import urlparse
import cv2
import numpy as np
import httpx

class Spool:
    def __init__(self,path):
        self.path=str(path)
        with self.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS spool(id TEXT PRIMARY KEY,image BLOB NOT NULL,metadata TEXT NOT NULL,sent INTEGER DEFAULT 0)')
    def connect(self):return sqlite3.connect(self.path,timeout=15)
    def add(self,image,metadata):
        event=str(uuid.uuid4())
        with self.connect() as c:c.execute('INSERT INTO spool(id,image,metadata) VALUES(?,?,?)',(event,image,json.dumps(metadata)))
        return event
    def pending(self):
        with self.connect() as c:return c.execute('SELECT id,image,metadata FROM spool WHERE sent=0 ORDER BY rowid LIMIT 10').fetchall()
    def acknowledge(self,event):
        with self.connect() as c:c.execute('UPDATE spool SET sent=1 WHERE id=?',(event,))

class Sender:
    def __init__(self,args,spool):self.a=args;self.spool=spool;self.token='';self.expires=0
    def headers(self):
        if self.a.local:return {'X-Demo-User':'mechanic'}
        if time.monotonic()>self.expires:
            secret=os.environ.get('CAMERA_CLIENT_SECRET')
            if not secret:raise RuntimeError('Set CAMERA_CLIENT_SECRET in this machine environment')
            r=httpx.post(self.a.token_url,auth=(self.a.client_id,secret),data={'grant_type':'client_credentials','scope':'stocklane/capture'},timeout=10)
            r.raise_for_status();data=r.json();self.token=data['access_token'];self.expires=time.monotonic()+int(data['expires_in'])-30
        return {'Authorization':'Bearer '+self.token}
    def flush(self):
        for event,image,metadata in self.spool.pending():
            try:
                r=httpx.post(self.a.api_url.rstrip('/')+'/api/vision/captures',headers=self.headers(),data=dict(json.loads(metadata),event_id=event),files={'file':('capture.jpg',image,'image/jpeg')},timeout=20)
                if r.status_code==401:self.expires=0
                r.raise_for_status();self.spool.acknowledge(event);print('Capture queued for mechanic review:',event,flush=True)
            except Exception:print('Capture remains in the durable local spool; will retry.',flush=True);break

def main(args):
    if args.local:
        if urlparse(args.api_url).hostname not in {'localhost','127.0.0.1'}:raise ValueError('Local identities are restricted to loopback targets')
    elif not args.api_url.startswith('https://') or not args.token_url.startswith('https://'):raise ValueError('Cloud capture and token URLs must use HTTPS')
    Path(args.spool).parent.mkdir(parents=True,exist_ok=True)
    spool=Spool(args.spool);sender=Sender(args,spool);stop=threading.Event()
    def worker():
        while not stop.is_set():sender.flush();stop.wait(3)
    t=threading.Thread(target=worker,daemon=True);t.start()
    camera=cv2.VideoCapture(args.camera)
    if not camera.isOpened():raise RuntimeError('Camera is unavailable')
    background=None;prior=None;stable=0;clear=0;armed=True
    print('Keep the tray empty for the first reference frame.',flush=True)
    try:
        while True:
            ok,frame=camera.read()
            if not ok:raise RuntimeError('Camera frame could not be read')
            if args.roi:
                x,y,w,h=args.roi;frame=frame[y:y+h,x:x+w]
                if frame.size==0:raise ValueError('ROI is outside the camera frame')
            small=cv2.resize(frame,(320,240));gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
            gray=cv2.GaussianBlur(gray,(9,9),0)
            if background is None:background=gray.copy();prior=gray;time.sleep(.1);continue
            occupancy=float(np.mean(cv2.absdiff(gray,background)>25))
            motion=float(np.mean(cv2.absdiff(gray,prior)));prior=gray
            stable=stable+1 if occupancy>args.presence and motion<1.5 else 0
            clear=clear+1 if occupancy<.02 else 0
            if clear>=12:armed=True
            sharpness=cv2.Laplacian(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var()
            if armed and stable>=8 and sharpness>args.sharpness:
                ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,92])
                if ok:
                    event=spool.add(encoded.tobytes(),{'direction':args.direction,'station_id':args.station,'job_id':args.job_id or ''});print('Captured encounter:',event,flush=True);armed=False
            if args.show:
                cv2.imshow('Stocklane tray - Q to quit',frame)
                if cv2.waitKey(1)&255==ord('q'):break
            time.sleep(.08)
    finally:
        stop.set();t.join(timeout=25);camera.release();cv2.destroyAllWindows()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--camera',type=int,default=0);p.add_argument('--api-url',required=True);p.add_argument('--direction',choices=['IN','OUT'],required=True);p.add_argument('--station',required=True);p.add_argument('--job-id');p.add_argument('--local',action='store_true');p.add_argument('--token-url',default='');p.add_argument('--client-id',default='');p.add_argument('--spool',default='.data/camera-spool.db');p.add_argument('--presence',type=float,default=.06);p.add_argument('--sharpness',type=float,default=60);p.add_argument('--roi',nargs=4,type=int);p.add_argument('--show',action='store_true')
    try:main(p.parse_args())
    except KeyboardInterrupt:pass

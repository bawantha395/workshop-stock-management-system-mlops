#!/usr/bin/env python3
"""Exercise real HTTP services. Use only against an isolated local test database."""
import json,base64,struct,zlib,io
import uuid
import urllib.request
import urllib.error
from decimal import Decimal

INV='http://localhost:8081/api/inventory'
WORK='http://localhost:8082/api/workshop'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def call(url,body=None,key=None,expected=200,method=None):
    h={'Content-Type':'application/json','X-Demo-User':'owner'}
    if key:h['Idempotency-Key']=key
    req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers=h,method=method)
    try:
        with opener.open(req,timeout=15) as r:
            data=r.read();assert r.status==expected
            return json.loads(data) if r.headers.get_content_type()=='application/json' else data
    except urllib.error.HTTPError as e:
        if e.code!=expected:raise AssertionError(f'{url}: {e.code}: '+e.read().decode()) from e
        return None

def key():return str(uuid.uuid4())

def camera_capture(direction,job_id=''):
    # Deterministic test PNG, generated with the standard library only.
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    pixels=b''.join(b'\0'+bytes([50+y,130,85])*64 for y in range(64))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
    event=key();boundary='stocklane-'+uuid.uuid4().hex;parts=[]
    for field,value in {'event_id':event,'direction':direction,'station_id':'http-smoke-tray','job_id':job_id}.items():parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+png+f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request('http://localhost:8083/api/vision/captures',data=b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with opener.open(req,timeout=20) as r:return json.loads(r.read())

def main():
    k=key();p={'sku':'TEST-'+key()[:8].upper(),'name':'Test oil 4L','category':'Engine oil','brand':'Test','grade':'5W-30','capacity':'4L','barcode':None,'unit':'UNIT','openingQuantity':50,'sellingPrice':5000,'reorderLevel':5,'imageId':None}
    product=call(INV+'/products',p,k);assert call(INV+'/products',p,k)['id']==product['id']
    def move(kind,q,job=None,issue=None,k=None):return call(INV+'/movements',{'kind':kind,'quantity':q,'productId':product['id'],'jobId':job,'issueId':issue,'note':'HTTP smoke test'},k or key())
    receiptKey=key();receipt=move('RECEIPT',10,k=receiptKey);assert move('RECEIPT',10,k=receiptKey)['id']==receipt['id'];assert Decimal(str(receipt['balance']))==60
    job=call(WORK+'/jobs',{'customer':'TEST CUSTOMER','vehicle':'Mitsubishi Montero','registration':'TEST-0001','phone':'','summary':'Automated local verification'},key())
    issue=move('ISSUE',2,job['id']);assert Decimal(str(issue['balance']))==58
    returned=move('RETURN',1,job['id'],issue['id']);assert Decimal(str(returned['balance']))==59
    snap=call(INV+'/jobs/'+job['id']+'/snapshot');assert Decimal(str(snap['lines'][0]['quantity']))==1
    invoice=call(WORK+'/jobs/'+job['id']+'/invoice',{'labour':1500},key());assert Decimal(str(invoice['total']))==6500
    pdf=call(WORK+'/invoices/'+invoice['id']+'/pdf');assert pdf.startswith(b'%PDF')
    call(INV+'/movements',{'kind':'ISSUE','quantity':1,'productId':product['id'],'jobId':job['id'],'issueId':None,'note':'blocked after invoice'},key(),409)
    print('PASS: 50 + 10 - 2 + 1 = 59 units; bill = one bottle + labour = LKR 6,500; PDF generated; later issues blocked.')
    incoming=camera_capture('IN');cameraKey=key()
    cameraProduct=call(INV+'/products',dict(p,sku='CAM-'+key()[:8],openingQuantity=2,imageId=incoming['image_id'],sourceCaptureId=incoming['id']),cameraKey)
    recorded=call(INV+'/captures/'+incoming['id']+'/movement')['movement'];assert recorded['kind']=='RECEIPT'
    assert call('http://localhost:8083/api/vision/captures/'+incoming['id'],{'movementId':recorded['id']},method='PATCH')['status']=='POSTED'
    call(INV+'/movements',{'kind':'RECEIPT','quantity':2,'productId':cameraProduct['id'],'jobId':None,'issueId':None,'note':'duplicate encounter','sourceCaptureId':incoming['id']},key(),409)
    cameraJob=call(WORK+'/jobs',{'customer':'CAMERA TEST','vehicle':'Montero','registration':'CAM-0001','phone':'','summary':'Captured issue transport test'},key())
    outgoing=camera_capture('OUT',cameraJob['id'])
    issue=call(INV+'/movements',{'kind':'ISSUE','quantity':1,'productId':cameraProduct['id'],'jobId':cameraJob['id'],'issueId':None,'note':'confirmed camera','sourceCaptureId':outgoing['id']},key())
    assert Decimal(str(issue['balance']))==1
    assert call('http://localhost:8083/api/vision/captures/'+outgoing['id'],{'movementId':issue['id']},method='PATCH')['status']=='POSTED'
    print('PASS: camera IN/OUT inbox, verified source metadata, unique capture posting and job linkage.')

if __name__=='__main__':main()

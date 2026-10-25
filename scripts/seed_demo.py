#!/usr/bin/env python3
"""Optional local fixture data, never run automatically against a real workshop."""
import io,json,time,uuid,urllib.request,urllib.error,os
from PIL import Image,ImageDraw

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(service,path,body=None):
    base=os.environ.get({8081:'INVENTORY_URL',8082:'WORKSHOP_URL',8083:'VISION_URL'}[service],f'http://localhost:{service}')
    req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Idempotency-Key':str(uuid.uuid4()),'X-Demo-User':'owner'})
    with opener.open(req,timeout=20) as r:return json.loads(r.read())

def image_photo(label,color):
    im=Image.new('RGB',(420,520),'#f0f2ed');d=ImageDraw.Draw(im);d.rounded_rectangle((125,105,310,450),radius=20,fill=color);d.rounded_rectangle((140,70,220,125),radius=6,fill='#34493b');d.rounded_rectangle((146,250,290,390),radius=5,fill='#e8e4c6');d.text((166,280),label,fill='#344538');d.text((163,345),'DEMO REFERENCE',fill='#62756a');out=io.BytesIO();im.save(out,format='JPEG');return out.getvalue()

def photo_match(data):
    boundary='stocklane-'+uuid.uuid4().hex
    content=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="demo.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request(os.environ.get('VISION_URL','http://localhost:8083')+'/api/vision/match',data=content,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with opener.open(req,timeout=20) as r:return json.loads(r.read())

def main():
    if os.environ.get('ENVIRONMENT','local')!='local':raise RuntimeError('Sample data is restricted to local development')
    products=call(8081,'/api/inventory/products');existing={p['sku'] for p in products}
    samples=[('MOB-5W30-4L','Mobil Super 5W-30 4L','Engine oil','Mobil','5W-30','4L',50,14800,10,'#7e8e5e'),('SHELL-10W40-4L','Shell Helix HX7 10W-40','Engine oil','Shell','10W-40','4L',12,12500,5,'#7f868c'),('CASTROL-5W30-1L','Castrol MAGNATEC 5W-30','Engine oil','Castrol','5W-30','1L',3,4500,5,'#6b8e6a'),('MON-OIL-FILTER','Montero engine oil filter','Filters','Workshop sample','CONFIRM-PART-NO','',2,3200,5,'#59646b'),('MON-AIR-FILTER','Montero air filter','Filters','Workshop sample','CONFIRM-PART-NO','',8,5400,3,'#c29c71'),('BRAKE-FLUID-1L','DOT 4 brake fluid 1L','Fluids','Workshop sample','DOT 4','1L',15,2800,4,'#6d758a')]
    for sku,name,category,brand,grade,size,count,price,reorder,color in samples:
        if sku in existing:continue
        match=photo_match(image_photo(grade+'\n'+size,color))
        p=call(8081,'/api/inventory/products',{'sku':sku,'name':name,'category':category,'brand':brand,'grade':grade,'capacity':size,'barcode':None,'unit':'UNIT','openingQuantity':count,'sellingPrice':price,'reorderLevel':reorder,'imageId':match['imageId']})
        print('Added demo SKU:',p['sku'])
    jobs=call(8082,'/api/workshop/jobs')
    if not any(j['registration']=='DEMO-4821' for j in jobs):
        call(8082,'/api/workshop/jobs',{'customer':'Demo - Nimal Perera','vehicle':'Mitsubishi Montero Sport','registration':'DEMO-4821','phone':'Demo record','summary':'Engine oil service and filter replacement.'})
        call(8082,'/api/workshop/jobs',{'customer':'Demo - Kasun Silva','vehicle':'Mitsubishi Montero V78','registration':'DEMO-1635','phone':'Demo record','summary':'Brake inspection and fluid replacement.'})
    drafts=call(8083,'/api/vision/drafts')
    if not drafts:
        match=photo_match(image_photo('UNFAMILIAR\n8L','#b4a47f'));call(8083,'/api/vision/drafts',{'imageId':match['imageId']})
    print('Local demo fixtures ready. References are synthetic illustrations, not model accuracy evidence.')

if __name__=='__main__':main()

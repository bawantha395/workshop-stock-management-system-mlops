from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import hashlib
import json
import logging
import threading
import uuid
from pathlib import Path
import boto3
import httpx
import redis
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, insert, update
from sqlalchemy.exc import IntegrityError
from .config import Settings
from .security import Security
from .storage import Store
from .encoder import Encoder
from .qr import product_qr
from .bedrock import propose, PROMPT_VERSION

log = logging.getLogger('stocklane.vision')

def create_app(settings=None):
    s = settings or Settings()
    s.check()
    security = Security(s)
    store = Store(s)
    encoder = Encoder(s.model_dir) if (Path(s.model_dir)/'model.json').exists() else None
    cache = redis.Redis.from_url(s.redis_url, socket_connect_timeout=.25, socket_timeout=.25,decode_responses=True)
    stop = threading.Event()

    def embedding(image):
        if encoder is None:
            raise HTTPException(503, 'Image model is not installed. Run scripts/download_model.py first.')
        key='stocklane:embedding:'+encoder.version+':'+encoder.preprocessing+':'+hashlib.sha256(image).hexdigest()
        try:
            hit=cache.get(key)
            if hit:
                cache_events.labels('hit').inc();return json.loads(hit)
        except (redis.RedisError,ValueError):cache_events.labels('error').inc()
        cache_events.labels('miss').inc()
        result=encoder.encode(image)
        try:cache.set(key,json.dumps(result),ex=1800)
        except redis.RedisError:pass
        return result

    def consume(event):
        if event.get('type')!='CATALOGUE_APPROVED':raise ValueError('Unexpected event type')
        product=event['payload'];image_id=product.get('image_id')
        if not image_id:return
        vector=embedding(store.image(image_id))
        event_hash=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
        try:store.index(product,image_id,encoder.version,vector,event['eventId'],event_hash)
        except IntegrityError:
            with store.engine.connect() as c:
                seen=c.execute(select(store.events).where(store.events.c.event_id==event['eventId'])).mappings().first()
                if not seen or seen['payload_hash']!=event_hash:raise

    def queue_worker():
        client=boto3.client('sqs',region_name=s.aws_region)
        while not stop.is_set():
            try:
                messages=client.receive_message(QueueUrl=s.catalogue_queue_url,MaxNumberOfMessages=5,WaitTimeSeconds=2).get('Messages',[])
                for message in messages:
                    try:
                        consume(json.loads(message['Body']))
                        client.delete_message(QueueUrl=s.catalogue_queue_url,ReceiptHandle=message['ReceiptHandle'])
                    except Exception:log.exception('Catalogue event remains queued for retry')
            except Exception:
                log.exception('Catalogue queue polling failed')
                stop.wait(3)

    def reconcile_vectors():
        if encoder is None:return
        with store.engine.connect() as c:
            rows=c.execute(select(store.refs)).mappings().all()
        current={(r['product_id'],r['image_id']) for r in rows if r['model_version']==encoder.version}
        for row in rows:
            key=(row['product_id'],row['image_id'])
            if key in current:continue
            store.index(json.loads(row['product']),row['image_id'],encoder.version,embedding(store.image(row['image_id'])))
            current.add(key)

    def reconcile_worker():
        while not stop.wait(30):
            try:reconcile_vectors()
            except Exception:log.exception('Versioned reference reconciliation will retry')

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(reconcile_vectors)
        reconciler=threading.Thread(target=reconcile_worker,daemon=True);reconciler.start()
        thread=None
        if s.catalogue_queue_url:
            thread=threading.Thread(target=queue_worker,daemon=True);thread.start()
        yield
        stop.set()
        if thread:await asyncio.to_thread(thread.join,5)
        await asyncio.to_thread(reconciler.join,5)
        store.engine.dispose()

    app=FastAPI(title='Stocklane Vision',version='0.1.0',lifespan=lifespan,docs_url='/api/vision/docs' if s.environment=='local' else None,openapi_url='/api/vision/openapi.json' if s.environment=='local' else None)
    app.state.store=store;app.state.embedding=embedding;app.state.consume=consume
    app.add_middleware(CORSMiddleware,allow_origins=[s.web_origin],allow_methods=['GET','POST','PATCH','OPTIONS'],allow_headers=['Authorization','Content-Type','Idempotency-Key','X-Demo-User'])
    from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    import time,hmac
    registry=CollectorRegistry()
    requests=Counter('stocklane_http_requests_total','HTTP requests',['method','route','status'],registry=registry)
    latency=Histogram('stocklane_http_request_seconds','Request latency',['route'],registry=registry)
    cache_events=Counter('stocklane_embedding_cache_total','Embedding cache results',['result'],registry=registry)
    @app.middleware('http')
    async def observe(request,call_next):
        started=time.perf_counter();response=await call_next(request)
        route=getattr(request.scope.get('route'),'path','unmatched')
        requests.labels(request.method,route,str(response.status_code)).inc();latency.labels(route).observe(time.perf_counter()-started)
        return response
    @app.get('/metrics')
    def metrics(request:Request):
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+s.internal_token):raise HTTPException(401,'Service identity required')
        return Response(generate_latest(registry),media_type=CONTENT_TYPE_LATEST)

    @app.get('/health/live')
    def live():return {'status':'UP'}

    @app.get('/health/ready')
    def ready():
        with store.engine.connect() as c:
            from sqlalchemy import text
            c.execute(text('SELECT 1'))
        if encoder is None:raise HTTPException(503,'Image model has not been installed')
        return {'status':'UP','modelVersion':encoder.version}

    @app.get('/api/vision/status')
    def status(request:Request):
        security.staff(request)
        try:cache_ok=cache.ping()
        except redis.RedisError:cache_ok=False
        return {'modelReady':encoder is not None,'modelVersion':encoder.version if encoder else None,'bedrockConfigured':bool(s.bedrock_model_id),'cacheAvailable':cache_ok,'automaticPosting':False,'mode':s.auth_mode}

    @app.post('/api/vision/qr')
    async def read_qr(request:Request,file:UploadFile=File(...)):
        security.staff(request)
        data=await file.read(s.max_upload_bytes+1)
        if len(data)>s.max_upload_bytes:raise HTTPException(413,'Image exceeds the upload limit')
        try:value=await asyncio.to_thread(product_qr,data)
        except (ValueError,OSError):raise HTTPException(422,'Use a clear photo with a valid Stocklane QR') from None
        return {'value':value}

    @app.post('/api/vision/match')
    async def match(request:Request,file:UploadFile=File(...)):
        security.staff(request,capture=True)
        data=await file.read(s.max_upload_bytes+1)
        if len(data)>s.max_upload_bytes:raise HTTPException(413,'Image exceeds the 8 MB upload limit')
        try:
            image_id=await asyncio.to_thread(store.save_image,data)
            image=await asyncio.to_thread(store.image,image_id)
            vector=await asyncio.to_thread(embedding,image)
            candidates=await asyncio.to_thread(store.candidates,encoder.version,vector)
            candidates=[candidate for candidate in candidates if encoder.accepts(candidate['similarity'],s.match_threshold)]
            for candidate in candidates:candidate['sameSkuEstimate']=encoder.same_sku_estimate(candidate['similarity'])
        except HTTPException:raise
        except (ValueError,OSError):raise HTTPException(422,'Use a clear JPEG or PNG photo of one item') from None
        # Baseline similarity is deliberately not presented as an accuracy percentage.
        state='REVIEW' if candidates else 'UNKNOWN'
        return {'imageId':image_id,'state':state,'modelVersion':encoder.version,'candidates':candidates,'autoPostEligible':False,'message':'Check brand, grade and capacity before confirming.' if candidates else 'No approved reference match yet. Create a review draft.'}

    @app.get('/api/vision/images/{image_id}')
    def image(image_id:str,request:Request):
        security.staff(request)
        try:return Response(store.image(image_id),media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Image not found') from None

    @app.post('/api/vision/captures')
    async def capture(request:Request,file:UploadFile=File(...),event_id:str=Form(...),direction:str=Form(...),station_id:str=Form(...),job_id:str=Form('')):
        security.staff(request,capture=True)
        try:uuid.UUID(event_id)
        except ValueError:raise HTTPException(400,'Invalid event ID') from None
        if direction not in {'IN','OUT'} or len(station_id)>80:raise HTTPException(400,'Invalid capture station metadata')
        if job_id:
            try:uuid.UUID(job_id)
            except ValueError:raise HTTPException(400,'Invalid job ID') from None
        data=await file.read(s.max_upload_bytes+1)
        if len(data)>s.max_upload_bytes:raise HTTPException(413,'Image is too large')
        fingerprint=hashlib.sha256(data+json.dumps([direction,station_id,job_id]).encode()).hexdigest()
        with store.engine.connect() as c:
            seen=c.execute(select(store.captures).where(store.captures.c.id==event_id)).mappings().first()
            if seen:
                if seen['request_hash']!=fingerprint:raise HTTPException(409,'Capture ID reused with different evidence')
                return dict(seen,result=json.loads(seen['result']))
        try:
            image_id=await asyncio.to_thread(store.save_image,data)
            qr_value=await asyncio.to_thread(product_qr,data)
            identified=None
            if qr_value:
                product=await asyncio.to_thread(verified_product,qr_value.removeprefix('stocklane:v1:'))
                identified=product['id'];candidates=[]
            else:
                vector=await asyncio.to_thread(embedding,store.image(image_id))
                candidates=await asyncio.to_thread(store.candidates,encoder.version,vector)
                candidates=[candidate for candidate in candidates if encoder.accepts(candidate['similarity'],s.match_threshold)]
                for candidate in candidates:candidate['sameSkuEstimate']=encoder.same_sku_estimate(candidate['similarity'])
        except (ValueError,OSError):raise HTTPException(422,'Invalid item photo') from None
        result={'imageId':image_id,'state':'REVIEW' if candidates or identified else 'UNKNOWN','modelVersion':encoder.version,'candidates':candidates,'identifiedProductId':identified,'qrValue':qr_value,'autoPostEligible':False,'message':'QR identified the product. Confirm quantity.' if identified else 'Review this captured movement and confirm its quantity.'}
        row={'id':event_id,'request_hash':fingerprint,'image_id':image_id,'direction':direction,'job_id':job_id or None,'station_id':station_id,'status':'PENDING','result':json.dumps(result),'created_at':datetime.now(timezone.utc).isoformat(),'movement_id':None}
        try:
            with store.engine.begin() as c:c.execute(insert(store.captures).values(**row))
        except IntegrityError:
            with store.engine.connect() as c:
                seen=c.execute(select(store.captures).where(store.captures.c.id==event_id)).mappings().one()
                if seen['request_hash']!=fingerprint:raise HTTPException(409,'Capture ID reused') from None
                row=dict(seen)
        return dict(row,result=json.loads(row['result']))

    @app.get('/api/vision/captures')
    def capture_inbox(request:Request):
        security.staff(request)
        with store.engine.connect() as c:
            return [dict(r,result=json.loads(r['result'])) for r in c.execute(select(store.captures).order_by(store.captures.c.created_at.desc()).limit(100)).mappings()]

    @app.get('/internal/captures/{event_id}')
    def internal_capture(event_id:str,request:Request):
        security.internal(request)
        with store.engine.connect() as c:
            row=c.execute(select(store.captures).where(store.captures.c.id==event_id)).mappings().first()
            if not row:raise HTTPException(404,'Capture not found')
            return {k:row[k] for k in ['id','status','direction','job_id','image_id']}

    class CaptureResolution(BaseModel):movementId:str

    @app.patch('/api/vision/captures/{event_id}')
    def resolve_capture(event_id:str,body:CaptureResolution,request:Request):
        security.staff(request)
        with store.engine.begin() as c:
            row=c.execute(select(store.captures).where(store.captures.c.id==event_id)).mappings().first()
            if not row:raise HTTPException(404,'Capture not found')
            r=httpx.get(s.inventory_url+'/internal/movements/'+body.movementId,headers={'X-Internal-Token':s.inventory_read_token or s.internal_token},timeout=5,trust_env=False)
            if r.status_code!=200:raise HTTPException(409,'A confirmed inventory movement is required')
            movement=r.json()
            if movement.get('source_capture_id')!=event_id or movement.get('kind')!=('RECEIPT' if row['direction']=='IN' else ('ISSUE' if row['job_id'] else 'STOCK_OUT')):
                raise HTTPException(409,'Movement is not linked to this capture')
            if row['job_id'] and movement.get('job_id')!=row['job_id']:raise HTTPException(409,'Movement belongs to another job')
            c.execute(update(store.captures).where(store.captures.c.id==event_id).values(status='POSTED',movement_id=body.movementId))
        return {'status':'POSTED'}

    @app.post('/internal/events')
    def event(request:Request,event:dict):
        security.internal(request)
        try:consume(event)
        except ValueError as e:raise HTTPException(409,str(e)) from None
        return {'accepted':True}

    class ReferenceInput(BaseModel):
        productId:str
        imageId:str

    def verified_product(product_id):
        try:
            r=httpx.get(s.inventory_url+'/internal/products/'+product_id,headers={'X-Internal-Token':s.inventory_read_token or s.internal_token},timeout=5,trust_env=False)
            if r.status_code==404:raise HTTPException(404,'Approved product not found')
            r.raise_for_status()
            product=r.json()
            if product.get('archived'):raise HTTPException(409,'Product is archived')
            return product
        except httpx.HTTPError:raise HTTPException(503,'Inventory is unavailable; retry this reference update') from None

    @app.post('/api/vision/references')
    def reference(request:Request,body:ReferenceInput):
        security.staff(request)
        product=verified_product(body.productId)
        try:vector=embedding(store.image(body.imageId))
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Photo not found') from None
        store.index(product,body.imageId,encoder.version,vector)
        return {'indexed':True,'modelVersion':encoder.version}

    class DraftInput(BaseModel):imageId:str

    @app.post('/api/vision/drafts')
    def draft(request:Request,body:DraftInput):
        actor=security.staff(request)
        try:image=store.image(body.imageId)
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Photo not found') from None
        key='stocklane:draft:'+s.bedrock_model_id+':'+PROMPT_VERSION+':'+body.imageId
        fields=None;source='manual'
        try:
            hit=cache.get(key)
            if hit:fields,source=json.loads(hit)
        except (redis.RedisError,ValueError):pass
        if fields is None:
            if s.bedrock_model_id:
                try:
                    day=datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    limit_key='stocklane:bedrock:daily:'+day
                    used=cache.incr(limit_key)
                    if used==1:cache.expire(limit_key,172800)
                    if used>s.bedrock_daily_request_limit:raise HTTPException(429,'Daily AI suggestion limit reached. Register manually or retry tomorrow UTC.')
                except redis.RedisError:raise HTTPException(503,'AI usage control is unavailable. Enter the details manually.') from None
            try:fields,source=propose(s,image)
            except Exception:raise HTTPException(503,'AI drafting is unavailable. Retry or enter the product manually.') from None
            try:cache.set(key,json.dumps([fields,source]),ex=900)
            except redis.RedisError:pass
        row={'id':str(uuid.uuid4()),'image_id':body.imageId,'fields':json.dumps(fields),'source':source,'status':'PENDING','created_at':datetime.now(timezone.utc).isoformat(),'actor':actor,'product_id':None}
        with store.engine.begin() as c:c.execute(insert(store.drafts).values(**row))
        return dict(row,fields=fields)

    @app.get('/api/vision/drafts')
    def drafts(request:Request):
        security.staff(request)
        with store.engine.connect() as c:
            rows=c.execute(select(store.drafts).order_by(store.drafts.c.created_at.desc()).limit(100)).mappings()
            return [dict(r,fields=json.loads(r['fields'])) for r in rows]

    class Resolution(BaseModel):
        status:str
        productId:str|None=None

    @app.patch('/api/vision/drafts/{draft_id}')
    def resolve(draft_id:str,body:Resolution,request:Request):
        security.staff(request)
        if body.status not in {'APPROVED','REJECTED'}:raise HTTPException(400,'Invalid draft resolution')
        with store.engine.begin() as c:
            row=c.execute(select(store.drafts).where(store.drafts.c.id==draft_id)).mappings().first()
            if not row:raise HTTPException(404,'Draft not found')
            if row['status']!='PENDING':
                if row['status']==body.status and row['product_id']==body.productId:return {'status':body.status}
                raise HTTPException(409,'This draft was already resolved')
            if body.status=='APPROVED':
                if not body.productId:raise HTTPException(400,'An approved product is required')
                product=verified_product(body.productId)
                # Link/index only an explicitly staff-approved item, never an LLM decision.
                vector=embedding(store.image(row['image_id']))
                store.index(product,row['image_id'],encoder.version,vector)
            c.execute(update(store.drafts).where(store.drafts.c.id==draft_id).values(status=body.status,product_id=body.productId))
        return {'status':body.status}

    return app

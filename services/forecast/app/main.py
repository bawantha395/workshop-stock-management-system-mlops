"""Independent forecast read service. Inventory alone owns stock writes/history.
Reads a validated, versioned batch model artifact; no SageMaker hosted endpoint.
"""
import json,math,threading,time
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
import boto3,httpx
from botocore.exceptions import ClientError,BotoCoreError
from fastapi import FastAPI,Request,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic_settings import BaseSettings,SettingsConfigDict
from prometheus_client import CollectorRegistry,Counter,Gauge,generate_latest,CONTENT_TYPE_LATEST
from shared_security import Security

class Settings(BaseSettings):
    model_config=SettingsConfigDict(extra='ignore')
    auth_mode:str='cognito'
    environment:str='cloud'
    cognito_issuer:str=''
    cognito_client_ids:str=''
    web_origin:str='http://localhost:4173'
    inventory_url:str='http://inventory:8081'
    inventory_read_token:str=''
    internal_token:str=''
    model_bucket:str=''
    aws_region:str='ap-southeast-2'

USABLE={'forecast','not_moving'}
KNOWN=USABLE|{'needs_more_history','unreliable'}

def projection(model,products,today=None):
    """Join the nightly forecast with live stock. Items without a usable forecast are still listed
    (with their reorder level) so the app can always give a plain answer."""
    today=today or datetime.now(ZoneInfo('Asia/Colombo')).date()
    state='not_trained';forecasts={};result={}
    if model:
        if model.get('schemaVersion')!=1 or model.get('task')!='stock_usage_forecast':raise ValueError('Invalid forecast schema')
        end=date.fromisoformat(model['historyUntil'])
        if datetime.fromisoformat(model['generatedAt'].replace('Z','+00:00'))>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('Future model timestamp')
        if today-timedelta(days=7)<=end<=today:
            state='fresh';forecasts={p['id']:p for p in model['products']}
            result.update(generatedAt=model['generatedAt'],historyUntil=model['historyUntil'],datasetSha256=model['datasetSha256'],model=model.get('model'))
        else:state='stale'
    rows=[]
    for item in products:
        row={k:item.get(k) for k in ('id','sku','name','unit')};row['availableNow']=float(item['quantity']);row['reorderLevel']=float(item.get('reorder_level') or 0)
        forecast=forecasts.get(item['id'])
        if forecast and forecast['status'] not in KNOWN:raise ValueError('Unknown forecast status')
        if not forecast or forecast['status'] not in USABLE:
            row.update(status=forecast['status'] if forecast else 'no_forecast',message=forecast['message'] if forecast else 'No forecast yet; the reorder level is used.');rows.append(row);continue
        selected={date.fromisoformat(d['date']):float(d['quantity']) for d in forecast['daily']}
        days=[today+timedelta(days=i) for i in range(30)]
        if any(d not in selected or not math.isfinite(selected[d]) or selected[d]<0 for d in days):raise ValueError('Incomplete forecast horizon')
        next7=sum(selected[d] for d in days[:7]);next30=sum(selected[d] for d in days);topup=max(0,next7-row['availableNow'])
        row.update(status=forecast['status'],message=forecast['message'],historyDays=forecast['historyDays'],next7=round(next7,3),next30=round(next30,3),suggestedTopUp7=math.ceil(topup) if item['unit']=='UNIT' else math.ceil(topup*1000)/1000)
        rows.append(row)
    return {'status':'ready','forecast':state,'products':rows,**result}

def create_app(settings=None,s3=None):
    s=settings or Settings()
    if s.auth_mode=='local' and s.environment!='local':raise RuntimeError('Local authentication requires a local environment')
    if s.auth_mode!='local' and (not s.cognito_issuer or not s.cognito_client_ids or len(s.inventory_read_token)<32):raise RuntimeError('Configure Cognito and the inventory read capability')
    security=Security(s);app=FastAPI(docs_url=None,openapi_url=None)
    app.add_middleware(CORSMiddleware,allow_origins=[s.web_origin],allow_methods=['GET'],allow_headers=['Authorization','X-Demo-User'])
    registry=CollectorRegistry();calls=Counter('stocklane_forecast_requests_total','Forecast requests',['outcome'],registry=registry)
    age=Gauge('stocklane_forecast_history_age_days','Age of forecast training history',registry=registry)
    lock=threading.Lock();cached={'until':0,'value':None}
    @lru_cache(maxsize=1)
    def storage():return s3 or boto3.client('s3',region_name=s.aws_region,config=__import__('botocore.config',fromlist=['Config']).Config(connect_timeout=3,read_timeout=5,retries={'total_max_attempts':1}))
    @app.get('/health/live')
    @app.get('/health/ready')
    def health():return {'status':'UP'}  # Not-trained is a valid business state, not a crash.
    @app.get('/metrics')
    def metrics(request:Request):
        import hmac
        if not s.internal_token or not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+s.internal_token):raise HTTPException(401,'Invalid metrics identity')
        return Response(generate_latest(registry),media_type=CONTENT_TYPE_LATEST)
    @app.get('/api/forecast')
    def forecast(request:Request):
        security.staff(request,owner=True)
        try:
            model=None
            if s.model_bucket:
                with lock:
                    if time.monotonic()>cached['until']:
                        try:
                            response=storage().get_object(Bucket=s.model_bucket,Key='forecast/current.json')
                            with response['Body'] as body:raw=body.read(12*1024*1024+1)
                            if len(raw)>12*1024*1024:raise ValueError('Forecast artifact too large')
                            cached.update(value=json.loads(raw),until=time.monotonic()+60)
                        except ClientError as error:
                            if error.response['Error']['Code'] not in {'NoSuchKey','404'}:raise
                            cached.update(value=None,until=time.monotonic()+60)
                    model=cached['value']
            response=httpx.get(s.inventory_url+'/internal/catalogue',headers={'X-Internal-Token':s.inventory_read_token or s.internal_token},timeout=8,trust_env=False);response.raise_for_status()
            result=projection(model,response.json());calls.labels(result['forecast']).inc()
            if model:age.set((datetime.now(ZoneInfo('Asia/Colombo')).date()-date.fromisoformat(model['historyUntil'])).days)
            return result
        except (ValueError,KeyError,TypeError,ClientError,BotoCoreError,httpx.HTTPError):
            calls.labels('error').inc();raise HTTPException(503,'Forecast results are unavailable. Verify the pipeline, S3 permissions and Inventory connectivity.') from None
    return app

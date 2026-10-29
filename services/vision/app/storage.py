import hashlib
import json
from pathlib import Path
import re
import boto3
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, select, delete
from sqlalchemy.types import UserDefinedType

class Vector(UserDefinedType):
    cache_ok = True
    def get_col_spec(self, **kw):
        return 'vector(1280)'

class Store:
    def __init__(self, settings):
        self.s = settings
        if settings.database_url.startswith('sqlite:///'):
            Path(settings.database_url[len('sqlite:///'):]).parent.mkdir(parents=True,exist_ok=True)
        self.engine = create_engine(settings.database_url, pool_pre_ping=True)
        self.pg = self.engine.dialect.name == 'postgresql'
        m = MetaData(schema='vision' if self.pg else None)
        self.refs = Table('reference_images',m,Column('product_id',String(36),primary_key=True),Column('image_id',String(100),primary_key=True),Column('model_version',String(160),primary_key=True),Column('embedding',Vector() if self.pg else Text,nullable=False),Column('product',Text,nullable=False))
        self.events = Table('processed_events',m,Column('event_id',String(36),primary_key=True),Column('payload_hash',String(64),nullable=False))
        self.drafts = Table('drafts',m,Column('id',String(36),primary_key=True),Column('image_id',String(100),nullable=False),Column('fields',Text,nullable=False),Column('source',String(40),nullable=False),Column('status',String(20),nullable=False),Column('created_at',String(40),nullable=False),Column('actor',String(180),nullable=False),Column('product_id',String(36)))
        if self.pg:
            from sqlalchemy import text
            with self.engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(118945890)'))
                m.create_all(c)
        else:m.create_all(self.engine)

    def save_image(self, data):
        from .encoder import decode
        import io
        im = decode(data)
        im.thumbnail((1600,1600))
        out = io.BytesIO(); im.save(out, format='JPEG',quality=94)
        normalized = out.getvalue()
        image_id = hashlib.sha256(normalized).hexdigest()+'.jpg'
        if self.s.media_bucket:
            boto3.client('s3',region_name=self.s.aws_region).put_object(Bucket=self.s.media_bucket,Key='images/'+image_id,Body=normalized,ContentType='image/jpeg')
        else:
            path = Path(self.s.files_root)/image_id
            if not path.exists():path.write_bytes(normalized)
        return image_id

    def image(self, image_id):
        if not re.fullmatch(r'[a-f0-9]{64}\.jpg',image_id):
            raise ValueError('Invalid image reference')
        if self.s.media_bucket:
            return boto3.client('s3',region_name=self.s.aws_region).get_object(Bucket=self.s.media_bucket,Key='images/'+image_id)['Body'].read()
        return (Path(self.s.files_root)/image_id).read_bytes()

    def index(self, product, image_id, version, embedding, event_id=None, event_hash=None):
        from sqlalchemy import insert
        product={k:product.get(k) for k in ['id','sku','name','category','brand','grade','capacity','barcode','unit','image_id']}
        with self.engine.begin() as c:
            if event_id:
                seen=c.execute(select(self.events).where(self.events.c.event_id==event_id)).mappings().first()
                if seen:
                    if seen['payload_hash'] != event_hash:raise ValueError('Event ID reused with different content')
                    return
            c.execute(delete(self.refs).where(self.refs.c.product_id==product['id'],self.refs.c.image_id==image_id,self.refs.c.model_version==version))
            c.execute(insert(self.refs).values(product_id=product['id'],image_id=image_id,model_version=version,embedding=json.dumps(embedding),product=json.dumps(product,default=str)))
            if event_id:c.execute(insert(self.events).values(event_id=event_id,payload_hash=event_hash))

    def candidates(self, version, embedding):
        import numpy as np
        with self.engine.connect() as c:
            if self.pg:
                from sqlalchemy import text
                rows=c.execute(text('SELECT product_id,image_id,product,1-(embedding <=> CAST(:v AS vector)) AS similarity FROM vision.reference_images WHERE model_version=:version ORDER BY embedding <=> CAST(:v AS vector) LIMIT 20'),{'v':json.dumps(embedding),'version':version}).mappings()
                ranked=[dict(r) for r in rows]
            else:
                rows=c.execute(select(self.refs).where(self.refs.c.model_version==version).limit(10000)).mappings()
                ranked=[dict(r,similarity=float(np.dot(embedding,json.loads(r['embedding'])))) for r in rows]
                ranked.sort(key=lambda r:r['similarity'],reverse=True)
        best={}
        for r in ranked:
            if r['product_id'] not in best:
                best[r['product_id']]={'product':json.loads(r['product']),'imageId':r['image_id'],'similarity':round(float(r['similarity']),4)}
        return list(best.values())[:5]

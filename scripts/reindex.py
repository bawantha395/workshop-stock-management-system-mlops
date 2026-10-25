"""Build this release's versioned vectors before Argo CD deploys it.
Old-version vectors remain available for rollback.
"""
import json,os
import httpx
from sqlalchemy import select
from app.config import Settings
from app.encoder import Encoder
from app.storage import Store
s=Settings();store=Store(s);encoder=Encoder(s.model_dir)
with store.engine.connect() as c:
    refs=c.execute(select(store.refs.c.product_id,store.refs.c.image_id).distinct()).all()
for product_id,image_id in refs:
    r=httpx.get(s.inventory_url+'/internal/products/'+product_id,headers={'X-Internal-Token':s.inventory_read_token or s.internal_token},timeout=10,trust_env=False);r.raise_for_status()
    store.index(r.json(),image_id,encoder.version,encoder.encode(store.image(image_id)))
print(json.dumps({'modelVersion':encoder.version,'referencesIndexed':len(refs)}))

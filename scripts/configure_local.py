#!/usr/bin/env python3
"""Create unique local-only credentials without printing them."""
import secrets,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
target=root/'.env'
if target.exists():
    print('.env already exists; kept its current credentials.')
else:
    names=['POSTGRES_PASSWORD','INVENTORY_DB_PASSWORD','WORKSHOP_DB_PASSWORD','VISION_DB_PASSWORD','REDIS_PASSWORD','INTERNAL_TOKEN']
    target.write_text(''.join(f'{name}={secrets.token_hex(24)}\n' for name in names)+'BEDROCK_MODEL_ID=\nAWS_REGION=eu-west-1\n'+f'LOCAL_UID={getattr(os,"getuid",lambda:1000)()}\nLOCAL_GID={getattr(os,"getgid",lambda:1000)()}\n')
    target.chmod(0o600)
    print('Created .env with unique local credentials.')

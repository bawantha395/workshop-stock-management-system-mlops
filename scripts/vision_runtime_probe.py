"""Read-only probe sent to the running Vision container by check_readiness.py.

No application/secret values or raw provider errors are printed. The optional
Bedrock probe is one small text request under the actual workload IAM identity.
It is an invocation test, not product accuracy or production acceptance.
"""
import json
import sys
from pathlib import Path

import boto3
import httpx
import redis
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings


def main(probe_bedrock=False):
    settings=Settings()
    result={}
    try:
        response=httpx.get('http://127.0.0.1:8083/health/ready',timeout=5,trust_env=False)
        manifest=json.loads((Path(settings.model_dir)/'model.json').read_text())
        result['photoModel']={'status':'loaded' if response.status_code==200 else 'unavailable',
            'version':manifest.get('version'),'workshopCalibrated':manifest.get('workshopCalibrated') is True,
            'automaticPosting':False}
    except Exception as error:
        result['photoModel']={'status':'unverified','errorCode':type(error).__name__}
    try:
        response=httpx.get(settings.inventory_url+'/internal/catalogue',
            headers={'X-Internal-Token':settings.inventory_read_token or settings.internal_token},
            timeout=8,trust_env=False)
        result['inventoryConnection']={'status':'verified' if response.status_code==200 else 'failed',
                                       'httpStatus':response.status_code}
    except Exception as error:
        result['inventoryConnection']={'status':'failed','errorCode':type(error).__name__}
    try:
        cache=redis.Redis.from_url(settings.redis_url,socket_connect_timeout=3,socket_timeout=3)
        result['cache']={'status':'reachable' if cache.ping() else 'unavailable'}
        cache.close()
    except Exception as error:
        result['cache']={'status':'unavailable','errorCode':type(error).__name__}
    result['catalogueConsumer']={'configured':bool(settings.catalogue_queue_url),
                                 'note':'Configuration alone does not prove message consumption.'}
    result['bedrock']={'modelId':settings.bedrock_model_id or None,
        'region':settings.aws_region,
        'status':'not_verified' if settings.bedrock_model_id else 'not_configured'}
    if probe_bedrock and settings.bedrock_model_id:
        try:
            response=boto3.client('bedrock-runtime',region_name=settings.aws_region,
                config=Config(connect_timeout=5,read_timeout=15,retries={'total_max_attempts':1})).converse(
                modelId=settings.bedrock_model_id,
                messages=[{'role':'user','content':[{'text':'Reply with OK.'}]}],
                inferenceConfig={'maxTokens':8,'temperature':0})
            has_text=any(block.get('text','').strip()
                         for block in response.get('output',{}).get('message',{}).get('content',[]))
            result['bedrock'].update(status='invocation_verified' if has_text else 'invalid_response',
                inputTokens=response.get('usage',{}).get('inputTokens',0),
                outputTokens=response.get('usage',{}).get('outputTokens',0))
        except ClientError as error:
            details=error.response.get('Error',{})
            message=details.get('Message','').lower()
            result['bedrock'].update(status='blocked',errorCode=details.get('Code','Unknown'),
                dailyQuotaMessage=any(word in message for word in ('per day','daily')))
        except Exception as error:
            result['bedrock'].update(status='unverified',errorCode=type(error).__name__)
    return result


if __name__=='__main__':
    print(json.dumps(main('--probe-bedrock' in sys.argv)))

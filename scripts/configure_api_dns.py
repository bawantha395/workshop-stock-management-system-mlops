#!/usr/bin/env python3
"""Create the owned API DNS alias after the ALB controller reports its address."""
import argparse,json,os,subprocess
from pathlib import Path
import boto3
p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();c=json.loads(Path(a.config).read_text());c=c.get('deployment',{}).get('value',c)
account=boto3.client('sts').get_caller_identity()['Account']
if account!=c['account_id']:raise RuntimeError('AWS account mismatch')
ingress=json.loads(subprocess.check_output(['kubectl','get','ingress','api','-n',c.get('workload_namespace','stocklane'),'-o','json']))
host=ingress['status']['loadBalancer']['ingress'][0]['hostname']
lbs=boto3.client('elbv2',region_name=c['region']).get_paginator('describe_load_balancers')
lb=next(x for page in lbs.paginate() for x in page['LoadBalancers'] if x['DNSName']==host)
boto3.client('route53').change_resource_record_sets(HostedZoneId=c['route53_zone_id'],ChangeBatch={'Comment':'Stocklane reviewed API endpoint','Changes':[{'Action':'UPSERT','ResourceRecordSet':{'Name':c['api_domain'],'Type':'A','AliasTarget':{'HostedZoneId':lb['CanonicalHostedZoneId'],'DNSName':host,'EvaluateTargetHealth':True}}}]})
print('API DNS alias requested for',c['api_domain'])

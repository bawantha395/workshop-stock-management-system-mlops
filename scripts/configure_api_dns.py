#!/usr/bin/env python3
"""Publish owned API/admin aliases after their ALBs report addresses."""
import argparse,json,subprocess,time
from pathlib import Path
import boto3

def configure(c):
    if boto3.client('sts').get_caller_identity()['Account']!=c['account_id']:raise RuntimeError('AWS account mismatch')
    targets=[('api',c.get('workload_namespace','stocklane'),c['api_domain'])]
    for name,namespace in [('argocd','argocd'),('grafana','monitoring')]:
        if c.get(name+'_domain'):targets.append(('admin-'+name,namespace,c[name+'_domain']))
    for ingress_name,namespace,domain in targets:
        deadline=time.monotonic()+300
        while True:
            result=subprocess.run(['kubectl','get','ingress',ingress_name,'-n',namespace,'-o','json'],capture_output=True,text=True,check=False)
            addresses=json.loads(result.stdout).get('status',{}).get('loadBalancer',{}).get('ingress',[]) if result.returncode==0 else []
            if addresses:break
            if time.monotonic()>deadline:raise TimeoutError('No ALB address for '+ingress_name)
            time.sleep(5)
        host=addresses[0]['hostname']
        lbs=boto3.client('elbv2',region_name=c['region']).get_paginator('describe_load_balancers')
        lb=next(x for page in lbs.paginate() for x in page['LoadBalancers'] if x['DNSName']==host)
        boto3.client('route53').change_resource_record_sets(HostedZoneId=c['route53_zone_id'],ChangeBatch={'Comment':'Stocklane reviewed endpoint','Changes':[{'Action':'UPSERT','ResourceRecordSet':{'Name':domain,'Type':'A','AliasTarget':{'HostedZoneId':lb['CanonicalHostedZoneId'],'DNSName':host,'EvaluateTargetHealth':True}}}]})
        print('DNS alias requested for',domain)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();c=json.loads(Path(a.config).read_text());configure(c.get('deployment',{}).get('value',c))

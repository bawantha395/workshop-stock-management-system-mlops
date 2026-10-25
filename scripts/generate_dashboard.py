"""Generate an importable Grafana dashboard; no hard-coded cluster addresses."""
import json
from pathlib import Path
panels=[]
def panel(title,query,unit='short'):
    n=len(panels)
    panels.append({'id':n+1,'title':title,'type':'timeseries','datasource':{'type':'prometheus','uid':'prometheus'},'gridPos':{'x':(n%2)*12,'y':(n//2)*8,'w':12,'h':8},'fieldConfig':{'defaults':{'unit':unit}},'targets':[{'refId':'A','expr':query}]})
panel('Vision HTTP requests / second','sum by (route) (rate(stocklane_http_requests_total[5m]))','reqps')
panel('Vision p95 request time','histogram_quantile(0.95, sum by (le) (rate(stocklane_http_request_seconds_bucket[5m])))','s')
panel('Java API requests / second','sum by (application) (rate(http_server_requests_seconds_count{namespace="stocklane"}[5m]))','reqps')
panel('Vision server errors / second','sum(rate(stocklane_http_requests_total{status=~"5.."}[5m]))','reqps')
panel('Embedding cache hit ratio','sum(rate(stocklane_embedding_cache_total{result="hit"}[5m])) / clamp_min(sum(rate(stocklane_embedding_cache_total{result=~"hit|miss"}[5m])),0.001)','percentunit')
panel('Application pod restarts','sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="stocklane"}[15m]))')
panel('Java heap in use','sum by (application) (jvm_memory_used_bytes{namespace="stocklane",area="heap"})','bytes')
panel('API availability / scrape health','up{namespace="stocklane"}')
dashboard={'title':'Stocklane - workshop platform','uid':'stocklane-platform','schemaVersion':39,'version':1,'tags':['stocklane','mlops'],'timezone':'browser','refresh':'30s','time':{'from':'now-1h','to':'now'},'panels':panels}
root=Path(__file__).resolve().parents[1]
(root/'deploy/observability/stocklane-dashboard.json').write_text(json.dumps(dashboard,indent=2)+'\n')

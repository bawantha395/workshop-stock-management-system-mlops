#!/usr/bin/env python3
"""Optional no-Docker development stack (H2 + SQLite; Redis can be external).

Production and the recommended local Compose setup use PostgreSQL + pgvector.
"""
import os,sys,subprocess,time,urllib.request,signal,shutil,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env=os.environ.copy()
settings=ROOT/'.env.dev.local'
if settings.exists():
    for line in settings.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);env[k.strip()]=v.strip()
java=env.get('DEV_JAVA') or (str(Path(env['JAVA_HOME'])/'bin/java') if env.get('JAVA_HOME') else shutil.which('java'))
if java and (ROOT/java).exists():java=str((ROOT/java).resolve())
if java:
    java_home=Path(java).parent.parent
    env['LD_LIBRARY_PATH']=str(java_home/'lib')+os.pathsep+str(java_home/'lib/server')+(os.pathsep+env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
python=env.get('DEV_PYTHON') or sys.executable
env.update({'SPRING_PROFILES_ACTIVE':'local','ENVIRONMENT':'local','AUTH_MODE':'local','INTERNAL_TOKEN':env.get('INTERNAL_TOKEN','local-development-service-token-32-characters'),'MODEL_DIR':str(ROOT/'models/baseline'),'PYTHONPATH':str(ROOT/'services/vision')+(os.pathsep+str(ROOT/env['DEV_PYTHONPATH']) if env.get('DEV_PYTHONPATH') else ''),'INVENTORY_URL':'http://localhost:8081','WORKSHOP_URL':'http://localhost:8082','VISION_URL':'http://localhost:8083'})
temporary=tempfile.TemporaryDirectory(prefix='stocklane-smoke-') if '--smoke-only' in sys.argv else None
data=Path(temporary.name) if temporary else ROOT/'.data/dev'
data.mkdir(parents=True,exist_ok=True)
children=[]

def spawn(args,cwd=ROOT,extra=None):
    p=subprocess.Popen(args,cwd=cwd,env=dict(env,**(extra or {})))
    children.append(p);return p

def stop(*_):
    for p in reversed(children):
        if p.poll() is None:p.terminate()
    for p in children:
        try:p.wait(timeout=8)
        except subprocess.TimeoutExpired:p.kill()

def wait_ready(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        if any(p.poll() is not None for p in children):raise RuntimeError('A backend exited; check its output above')
        try:
            with opener.open(url,timeout=1) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(.4)
    raise RuntimeError('Backend did not become ready: '+url)

def main():
    if not java:raise RuntimeError('Java 21 is required for the no-Docker development option')
    port=sys.argv[sys.argv.index('--port')+1] if '--port' in sys.argv else env.get('PORT','5173')
    web=spawn(['npm','run','dev','--','--port',port],cwd=ROOT/'apps/web') if '--smoke-only' not in sys.argv else None
    for service in ['inventory','workshop']:
        jar=ROOT/'services'/service/'target'/f'{service}-0.1.0.jar'
        if not jar.exists():raise RuntimeError('Build the services first: mvn package')
        spawn([java,'-XX:MaxRAMPercentage=35','-jar',str(jar),'--spring.profiles.active=local','--spring.datasource.url=jdbc:h2:file:'+str(data/service)+';MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DEFAULT_NULL_ORDERING=HIGH;DB_CLOSE_ON_EXIT=FALSE','--app.files-root='+str(data/'invoices')])
    spawn([python,'-m','uvicorn','app.main:create_app','--factory','--host','0.0.0.0','--port','8083'],extra={'DATABASE_URL':'sqlite:///'+str(data/'vision.db'),'FILES_ROOT':str(data/'images')})
    for url in ['http://localhost:8081/actuator/health/readiness','http://localhost:8082/actuator/health/readiness','http://localhost:8083/health/ready']:wait_ready(url)
    print('All three backend services are ready.',flush=True)
    if '--smoke-only' in sys.argv:
        subprocess.run([python,str(ROOT/'scripts/smoke_local.py')],env=env,check=True);return
    if '--seed' in sys.argv or env.get('DEV_SEED')=='true':subprocess.run([python,str(ROOT/'scripts/seed_demo.py')],env=env,check=True)
    while web.poll() is None:
        if any(p.poll() is not None for p in children):raise RuntimeError('A service exited')
        time.sleep(1)

if __name__=='__main__':
    signal.signal(signal.SIGTERM,lambda *_:(stop(),sys.exit(0)))
    try:main()
    finally:
        stop()
        if temporary:temporary.cleanup()

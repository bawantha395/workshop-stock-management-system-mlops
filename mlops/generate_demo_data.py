"""Reproducible synthetic workshop data for MLOps practice, never real stock.

The visual fixtures are programmatic illustrations, not workshop photographs.
Different views/sessions are rendered independently. Their quality scores only
describe this artificial dataset and cannot demonstrate workshop recognition.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import uuid
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image,ImageDraw,ImageFont

ITEMS=[
 ('Air filter','Filters','UNIT'),('Cabin filter','Filters','UNIT'),
 ('Oil filter','Filters','UNIT'),('Fuel filter','Filters','UNIT'),
 ('Brake pad set','Brakes','UNIT'),('Brake rotor','Brakes','UNIT'),
 ('Drive belt','Belts','UNIT'),('Spark plug','Ignition','UNIT'),
 ('Wiper blade','Body','UNIT'),('Wheel bearing','Bearings','UNIT'),
 ('Coolant bottle','Fluids','UNIT'),('Grease tub','Lubricants','UNIT'),
 ('Bolt pack','Fasteners','UNIT'),('Hose clamp','Fasteners','UNIT'),
 ('Radiator hose','Cooling','UNIT'),('Battery terminal','Electrical','UNIT'),
 ('Washer fluid','Fluids','LITRE'),('Transmission fluid','Fluids','LITRE'),
 ('Differential oil','Lubricants','LITRE'),('Engine oil','Lubricants','LITRE'),
 ('Headlamp bulb','Electrical','UNIT'),('Fuse pack','Electrical','UNIT'),
 ('Trim clip pack','Fasteners','UNIT'),('Gasket','Seals','UNIT'),
]
SCENARIOS={'cold_start':9,'weekday_baseline':12,'seasonal_mixed':24}


def catalogue():
    return [{'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'stocklane:synthetic:'+str(i))),
        'sku':f'DEMO-{i+1:03d}','name':'Demo '+name,'category':category,
        'brand':'Demo Parts Co','partNumber':f'DEMO-PART-{i+1:03d}','unit':unit,
        'location':f'Demo shelf {i//6+1}'} for i,(name,category,unit) in enumerate(ITEMS)]


def history(scenario,seed=20261027,as_of=None):
    if scenario not in SCENARIOS:raise ValueError('Unknown demo scenario')
    end=as_of or datetime.now(ZoneInfo('Asia/Colombo')).date()
    rows=[]
    for i,item in enumerate(catalogue()[:SCENARIOS[scenario]]):
        rng=random.Random(seed+i*1009)
        days=14 if scenario=='cold_start' else 56 if scenario=='weekday_baseline' else (1095 if i<12 else 210 if i<18 else 365 if i<22 else 14)
        start=end-timedelta(days=days);values=[];available=[]
        profile='weekday_only' if scenario=='weekday_baseline' else ['weekday_only','growth','seasonal','intermittent'][i%4]
        for n in range(days):
            day=start+timedelta(days=n)
            weekday=[.9,.7,.65,.85,1.8,1.15,.25][day.weekday()]
            season=(1.9 if day.month==12 else 1.3 if day.month==4 else 1.0) if profile=='seasonal' else 1.0
            trend=1+n*.04 if profile=='growth' else 1.0
            base=(3+i%5)*weekday*season*trend
            noise=0 if profile in {'weekday_only','growth'} else rng.uniform(-.15,.15)*base
            value=max(0,base+noise)
            if profile=='intermittent' and rng.random()<.68:value=0
            is_available=not (scenario=='seasonal_mixed' and i in (20,21) and (n%29 in (0,1,2) or n>=days-3))
            if not is_available:value=0
            values.append(round(value) if item['unit']=='UNIT' else round(value,3))
            available.append(is_available)
        rows.append({**{k:item[k] for k in ('id','sku','name','unit')},'start':str(start),
                     'usage':values,'inStock':available,'syntheticProfile':profile})
    return {'schemaVersion':1,'timezone':'Asia/Colombo','historyConfirmed':True,
        'asOf':datetime.combine(end,datetime.min.time(),tzinfo=ZoneInfo('Asia/Colombo')).isoformat(),
        'historyUntil':str(end),'synthetic':True,'dataPurpose':'mlops_demo_only',
        'seed':seed,'scenario':scenario,'products':rows}


def illustration(index,rng):
    """Draw code-native object fixtures; do not imitate commercial packaging."""
    background=tuple(rng.randint(215,245) for _ in range(3))
    canvas=Image.new('RGB',(480,480),background)
    obj=Image.new('RGBA',(340,340),(0,0,0,0));d=ImageDraw.Draw(obj)
    colors=['#bc5646','#c7a563','#3e6fa0','#b9953e','#474e55','#9bafb8',
            '#3e4540','#d9d5c5','#586c75','#8e9ea9','#7baf92','#986c9e']
    color=colors[index]
    if index in (0,1):
        d.rounded_rectangle((35,70,305,260),radius=12,fill=color,outline='#293943',width=8)
        d.rectangle((55,90,285,240),fill='#eadfba')
        for x in range(65,280,15):d.line((x,92,x,238),fill='#8b7d62',width=4)
    elif index in (2,3):
        d.rounded_rectangle((90,45,250,280),radius=26,fill=color,outline='#283b4c',width=7)
        d.ellipse((90,35,250,95),fill='#bec9cb',outline='#283b4c',width=5)
        d.ellipse((152,52,188,80),fill='#394750')
        d.rectangle((105,130,235,225),fill='#e8ece9')
    elif index==4:
        for y in (90,210):d.rounded_rectangle((45,y,295,y+75),radius=28,fill=color,outline='#252d32',width=9)
    elif index in (5,6,9):
        d.ellipse((45,45,295,295),fill=color,outline='#263c46',width=10)
        d.ellipse((100,100,240,240),fill=(0,0,0,0),outline='#263c46',width=8)
        if index==5:
            for n in range(8):
                a=n*math.pi/4;x=170+100*math.cos(a);y=170+100*math.sin(a)
                d.ellipse((x-8,y-8,x+8,y+8),fill='#314650')
    elif index==7:
        d.rectangle((135,38,205,155),fill='#eae8dd',outline='#59676b',width=5)
        for y in range(50,140,15):d.line((130,y,210,y),fill='#a4ada9',width=5)
        d.polygon([(120,155),(220,155),(230,205),(110,205)],fill='#b6c1c4',outline='#536a74')
        d.rectangle((140,205,200,295),fill='#9dabb1',outline='#536a74',width=5)
    elif index==8:
        d.rounded_rectangle((35,135,305,195),radius=14,fill=color,outline='#293b45',width=6)
        d.line((50,205,285,205),fill='#34444c',width=10)
    elif index==10:
        d.rounded_rectangle((75,95,265,285),radius=30,fill=color,outline='#2b5c49',width=6)
        d.rectangle((130,40,210,105),fill=color,outline='#2b5c49',width=6)
        d.rectangle((125,28,215,57),fill='#476274')
        d.rectangle((95,155,245,245),fill='#eff3e6')
    else:
        d.rounded_rectangle((65,90,275,280),radius=20,fill=color,outline='#503657',width=6)
        d.ellipse((58,65,282,130),fill='#cfc9d6',outline='#503657',width=6)
    d.text((104,164),f'DEMO {index+1:03d}',fill='#142632',font=ImageFont.load_default(size=17))
    angle=rng.uniform(-8,8)
    obj=obj.rotate(angle,resample=Image.Resampling.BICUBIC)
    scale=rng.uniform(.90,1.04);obj=obj.resize((int(obj.width*scale),int(obj.height*scale)))
    x=(480-obj.width)//2+rng.randint(-12,12);y=(480-obj.height)//2+rng.randint(-12,12)
    canvas.paste(obj,(x,y),obj)
    d=ImageDraw.Draw(canvas)
    d.text((16,12),'SYNTHETIC MLOPS DEMO',fill='#4e5f69',font=ImageFont.load_default(size=16))
    for _ in range(35):
        x=rng.randrange(480);y=rng.randrange(440,480)
        d.point((x,y),fill=tuple(rng.randrange(170,240) for _ in range(3)))
    return canvas


def generate(destination,seed=20261027,as_of=None):
    root=Path(destination);root.mkdir(parents=True,exist_ok=True)
    metadata={'synthetic':True,'dataPurpose':'mlops_demo_only','seed':seed,
        'description':'Programmatically generated fixtures. No real stock, customers, vehicle fitment or workshop accuracy evidence.',
        'productionEligible':False}
    (root/'dataset-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    with (root/'catalogue.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(catalogue()[0]));writer.writeheader();writer.writerows(catalogue())
    for scenario in SCENARIOS:
        folder=root/'forecast'/scenario;folder.mkdir(parents=True,exist_ok=True)
        snapshot=history(scenario,seed,as_of)
        (folder/'history.json').write_text(json.dumps(snapshot,separators=(',',':'))+'\n')
        with (folder/'daily_usage.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['sku','date','outgoingQuantity','inStock','syntheticProfile'])
            for row in snapshot['products']:
                start=date.fromisoformat(row['start'])
                for n,(value,available) in enumerate(zip(row['usage'],row['inStock'])):
                    writer.writerow([row['sku'],str(start+timedelta(days=n)),value,available,row['syntheticProfile']])
    photos=root/'photos';photos.mkdir(exist_ok=True);rows=[];checks={}
    for split_index,split in enumerate(('train','validation','test')):
        for index in range(12):
            for view in range(6):
                rng=random.Random(seed+split_index*100003+index*1009+view*97)
                name=f'{split}/DEMO-{index+1:03d}-{view+1:02d}.jpg';p=photos/name;p.parent.mkdir(exist_ok=True)
                illustration(index,rng).save(p,quality=90)
                checks[name]=hashlib.sha256(p.read_bytes()).hexdigest()
                rows.append({'file':name,'sku':f'DEMO-{index+1:03d}',
                    'session':f'demo-{split}-{index+1:03d}-{view//3+1}','split':split})
    with (photos/'manifest.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['file','sku','session','split']);writer.writeheader();writer.writerows(rows)
    checks['manifest.csv']=hashlib.sha256((photos/'manifest.csv').read_bytes()).hexdigest()
    (photos/'dataset-checksums.json').write_text(json.dumps(checks,sort_keys=True))
    (photos/'dataset-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (root/'README.md').write_text('''# Stocklane synthetic MLOps practice data

Every record and image here is artificial. No actual workshop stock is included.
These files demonstrate data validation, training, evaluation and artifact handling.
They cannot prove production forecasting or photo-recognition accuracy.

catalogue.csv: 24 generic workshop item definitions, including filters, brakes,
belts, ignition/electrical parts, fasteners, fluids and seals.

forecast/cold_start/history.json: 9 items with 14 days; expect insufficient history.
forecast/weekday_baseline/history.json: 12 items with 56 days; expect weekday baselines.
forecast/seasonal_mixed/history.json: 24 items; includes 1,095-day histories, growth,
Friday peaks, December/April seasonality, intermittent use, stock-outs and new items.
The accompanying daily_usage.csv files are human-readable versions of the input.
Availability masks deliberately prevent zero stock being treated as zero demand.

photos/: 216 illustrated visual fixtures for 12 SKUs, 72 images per train,
validation and test split. Independent rendered sessions use different angles,
positions, sizes and backgrounds. These are not real camera photographs.
manifest.csv and dataset-checksums.json support the normal validation steps.

Use the separate Train demo ML models workflow after deploying the updated
ml-training image. It writes under demo/, labels registry packages as synthetic,
and cannot change the live model, forecast or stock ledger.

Generate another reproducible set:
python mlops/generate_demo_data.py --output artifacts/demo-data-2 --seed 20261028

Amazon Bedrock is a pretrained managed LLM. This data does not train Nova.
Production photo matching needs real reviewed part images. Production forecasting
needs genuine, consistently recorded outgoing-stock history.
''')
    return {'synthetic':True,'productionEligible':False,'seed':seed,'photoImages':len(rows),
        'photoSkus':12,'forecastScenarios':list(SCENARIOS),'catalogueItems':len(ITEMS)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='artifacts/demo-data')
    parser.add_argument('--seed',type=int,default=20261027)
    parser.add_argument('--as-of',type=date.fromisoformat)
    args=parser.parse_args();print(json.dumps(generate(args.output,args.seed,args.as_of),indent=2))

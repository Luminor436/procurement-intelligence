#!/usr/bin/env python3
"""Official ECB daily EUR/USD series, no synthetic values. Standard library only."""
import csv, io, json, pathlib, urllib.request, datetime, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=2026-01-01&format=csvdata'
try:
    req=urllib.request.Request(URL,headers={'User-Agent':'ProcurementIntelligence/1.0','Accept':'text/csv'})
    with urllib.request.urlopen(req,timeout=30) as response: raw=response.read().decode('utf-8-sig')
    reader=csv.DictReader(io.StringIO(raw)); rows={}
    for r in reader:
        d=r.get('TIME_PERIOD','').strip();v=r.get('OBS_VALUE','').strip()
        try:
            datetime.date.fromisoformat(d); x=float(v)
            if x>0:rows[d]=x
        except (ValueError,TypeError):continue
    if len(rows)<20:raise RuntimeError(f'Solo {len(rows)} osservazioni BCE')
    out=ROOT/'data'/'eurusd_ecb.csv';out.parent.mkdir(exist_ok=True)
    with out.open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['date','eurusd','source']);w.writerows((d,format(v,'.6f'),'ECB') for d,v in sorted(rows.items()))
    (ROOT/'data'/'fx_status.json').write_text(json.dumps({'status':'ok','updated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'latest_date':max(rows),'rows':len(rows),'source':URL},indent=2)+'\n')
    print(f'BCE: {len(rows)} dati; ultimo {max(rows)}')
except Exception as exc:
    print(f'ERRORE BCE: {exc}',file=sys.stderr)
    sys.exit(1)

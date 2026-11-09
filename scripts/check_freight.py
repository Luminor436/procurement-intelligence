#!/usr/bin/env python3
"""Check only user-supplied port-to-port quotes; never synthesize rates."""
import csv,datetime,json,pathlib
root=pathlib.Path(__file__).resolve().parents[1]
p=root/'data'/'freight_quotes.csv'; rows=[]
with p.open(encoding='utf-8-sig',newline='') as f:
    for r in csv.DictReader(f):
        try:
            d=datetime.date.fromisoformat(r['date']); usd=float(r['usd'])
            if usd>0 and r.get('port') in ('Tianjin','Shenzhen','Ningbo'):rows.append((d,r))
        except (KeyError,ValueError,TypeError):pass
latest=max((d for d,_ in rows),default=None)
age=(datetime.date.today()-latest).days if latest else None
status='no_quotes' if latest is None else ('stale' if age>30 else 'ok')
out={'status':status,'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'valid_quotes':len(rows),'latest_date':str(latest) if latest else None,'age_days':age,'warning':'No verified route-specific quotes supplied' if not rows else ('Most recent quote older than 30 days' if age>30 else None)}
(root/'data'/'freight_status.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out))

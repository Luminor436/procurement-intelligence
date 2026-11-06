#!/usr/bin/env python3
"""Luccables public-page collector; source data is NOT official LME Cash.
Requires requests and beautifulsoup4. No bypass of site access controls.
"""
import csv, json, os, re, sys, time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
URL='https://www.luccables.it/rame.aspx'
HEAD={'User-Agent':'ProcurementIntelligence/1.0 (public data quality monitor; contact via GitHub repository)'}
NUM=r'([\d.]+,\d{3,4})'
FX_RE=re.compile(r'DOLLARO\s*:\s*'+NUM,re.I)
LME_RE=re.compile(r'\bLME\s*:\s*'+NUM,re.I)
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}

def number(s): return float(s.replace('.','').replace(',','.'))
def extract(html,year,month):
    soup=BeautifulSoup(html,'html.parser')
    # Calendar day cells can contain nested tags; use text with whitespace separators.
    found={}
    for cell in soup.select('td'):
        txt=cell.get_text(' ',strip=True)
        fx=FX_RE.search(txt); cu=LME_RE.search(txt)
        if not (fx and cu):continue
        before=txt[:min(fx.start(),cu.start())]
        days=re.findall(r'(?<!\d)(\d{1,2})(?!\d)',before)
        if not days:continue
        day=int(days[-1]);
        try:d=date(year,month,day)
        except ValueError:continue
        f=number(fx.group(1)); e=number(cu.group(1))
        if not (0.5<f<2.5 and 1000<e<50000):continue
        found[d.isoformat()]={'date':d.isoformat(),'eurusd_bfix':f,'copper_eur_t':e,'copper_usd_t_derived':round(f*e,4),'source':'Luccables','source_url':f'{URL}?a={year}&m={month}','copper_kind':'Luccables LME-derived EUR/t; not independently verified official Cash'}
    # Some layouts render one day per div, with a day number preceding the quote.
    return list(found.values())

def fetch(year,month):
    response=requests.get(URL,params={'a':year,'m':month},headers=HEAD,timeout=30)
    response.raise_for_status()
    response.encoding=response.apparent_encoding or 'utf-8'
    result=extract(response.text,year,month)
    if not result:raise RuntimeError(f'No valid daily Luccables entries parsed for {year}-{month:02d}; site may have changed or access may be restricted')
    return result

def main():
    now=datetime.now(ZoneInfo('Europe/Rome'))
    if os.environ.get('SCHEDULED','')=='1' and (now.weekday()>4 or now.hour!=18):
        print('Outside weekday 18:xx Europe/Rome window; no update');return
    months=[]
    for offset in (0,1,2):
        y=now.year;m=now.month-offset
        while m<1:y-=1;m+=12
        months.append((y,m))
    oldfile=DATA/'luccables_daily.json'
    existing=json.loads(oldfile.read_text('utf-8')) if oldfile.exists() else []
    merged={r['date']:r for r in existing}
    failures=[]; retrieved=0
    for y,m in months:
        try:
            rows=fetch(y,m)
            for r in rows:merged[r['date']]=r
            retrieved+=len(rows)
            print(f'{y}-{m:02d}: {len(rows)} entries')
        except Exception as exc:
            failures.append(f'{y}-{m:02d}: {exc}')
    rows=sorted(merged.values(),key=lambda x:x['date'])
    today=now.date()
    recent=[r for r in rows if date.fromisoformat(r['date'])<=today]
    latest=date.fromisoformat(recent[-1]['date']) if recent else None
    # Data are generally available after the session. Friday may be latest on Monday before publication.
    age=(today-latest).days if latest else None
    status={'checked_at':now.isoformat(),'latest_date':latest.isoformat() if latest else None,'age_calendar_days':age,'retrieved_rows':retrieved,'total_rows':len(rows),'errors':failures,'source':URL,'freshness':'unknown'}
    if latest and age<=3:status['freshness']='recent'
    if latest and age>3:status['freshness']='stale'
    (DATA/'luccables_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not retrieved or not latest or age>4 or (now.weekday()<5 and age>2):
        print('ERROR: insufficient fresh source data',status,file=sys.stderr)
        sys.exit(1)
    if failures:
        print('WARNING: partial month failures: '+'; '.join(failures),file=sys.stderr)
    oldfile.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (DATA/'luccables_daily.csv').open('w',encoding='utf-8',newline='') as fh:
        fields=['date','eurusd_bfix','copper_eur_t','copper_usd_t_derived','source','source_url','copper_kind']
        writer=csv.DictWriter(fh,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print('Updated',len(rows),'rows; latest',latest)

if __name__=='__main__':main()

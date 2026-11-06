#!/usr/bin/env python3
"""Fetch and cross-check public LME Cash copper quotes. No TLS bypass.

Outputs are isolated from legacy Luccables files until the dashboard schema is confirmed.
Review source licensing/redistribution terms before enabling public deployment.
"""
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

FT_URL = 'https://www.ftmercati.com/en/quotazioni.html'
WM_URL = 'https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash'
DATA = Path('data')
MONTHS = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}


def amount(s):
    s = re.sub(r'[^0-9,.]', '', s.strip())
    if not s: raise ValueError('missing numeric price')
    if ',' in s and '.' in s:
        s = s.replace(',', '') if s.rfind('.') > s.rfind(',') else s.replace('.', '').replace(',', '.')
    elif ',' in s:
        parts = s.split(',')
        s = s.replace(',', '') if len(parts[-1]) == 3 else s.replace(',', '.')
    return float(s)


def fetch(url):
    r = requests.get(url, timeout=25, headers={'User-Agent':'ProcurementIntelligence/1.0 (market-data verification; contact repository owner)'})
    r.raise_for_status()
    return r.text


def parse_ft(html):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    m = re.search(r'Session of\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})', text, re.I)
    if not m: raise ValueError('FT session date not found')
    month = MONTHS.get(m.group(1).lower())
    if not month: raise ValueError('FT unknown month')
    day = date(int(m.group(3)), month, int(m.group(2))).isoformat()
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td','th'])]
        if len(cells) >= 3 and cells[0].strip().lower() == 'copper':
            price = amount(cells[1])
            validate_price(price)
            return {'date':day,'cash_usd_t':price,'cash_eur_t_lme_fx':amount(cells[2]),'source':'FT Mercati','url':FT_URL}
    raise ValueError('FT copper row not found')


def parse_wm(html):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    for tr in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td','th'])]
        if len(cells) < 4: continue
        m = re.fullmatch(r'(\d{1,2})\.\s*([A-Za-z]+)\s+(20\d{2})', cells[0])
        if not m: continue
        month = MONTHS.get(m.group(2).lower())
        if not month: continue
        d = date(int(m.group(3)), month, int(m.group(1))).isoformat()
        p = amount(cells[1]); validate_price(p)
        out.append({'date':d,'cash_usd_t':p,'three_month_usd_t':amount(cells[2]),'lme_stocks_t':amount(cells[3]),'source':'Westmetall','url':WM_URL})
    if not out: raise ValueError('Westmetall historical rows not found')
    return sorted({x['date']:x for x in out}.values(), key=lambda x:x['date'])


def validate_price(v):
    if not 1000 <= v <= 100000: raise ValueError(f'implausible copper price {v}')


def main():
    DATA.mkdir(exist_ok=True)
    now = datetime.now(ZoneInfo('Europe/Rome'))
    status = {'checked_at':now.isoformat(),'ft':None,'westmetall':None,'result':'error','errors':[], 'warning':'Sources may have usage or redistribution restrictions; confirm before public publication.'}
    ft = None; wm = []
    try:
        ft = parse_ft(fetch(FT_URL)); status['ft'] = ft
    except Exception as e: status['errors'].append('FT: '+str(e))
    try:
        wm = parse_wm(fetch(WM_URL)); status['westmetall'] = wm[-1]
    except Exception as e: status['errors'].append('Westmetall: '+str(e))
    if not ft and not wm:
        status['result']='error'
    elif ft and wm:
        match = next((r for r in wm if r['date']==ft['date']), None)
        if match:
            diff = abs(match['cash_usd_t']-ft['cash_usd_t'])
            status['comparison']={'date':ft['date'],'difference_usd_t':round(diff,2),'difference_pct':round(diff/ft['cash_usd_t']*100,3)}
            status['result']='verified' if diff <= max(10,ft['cash_usd_t']*.002) else 'discrepancy'
        else: status['result']='unverified_date_mismatch'
    else: status['result']='single_source_only'
    latest = max([date.fromisoformat(x['date']) for x in ([ft] if ft else []) + (wm[-1:] if wm else [])]) if (ft or wm) else None
    if latest:
        status['latest_market_date'] = latest.isoformat()
        status['calendar_age_days'] = (now.date()-latest).days
        if status['calendar_age_days'] > 4: status['result']='stale'
    # Always write status; never replace validated legacy dataset on error.
    (DATA/'copper_sources_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if wm:
        # Keep isolated historical export, not dashboard's legacy files.
        with (DATA/'copper_westmetall_history.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['date','cash_usd_t','three_month_usd_t','lme_stocks_t','source','url']);w.writeheader();w.writerows(wm)
    if status['result'] not in ('verified','single_source_only'):
        print('SOURCE CHECK:',status['result'],status['errors'],file=sys.stderr)
        return 1
    print('SOURCE CHECK:',status['result'],status.get('latest_market_date'))
    return 0

if __name__ == '__main__': sys.exit(main())

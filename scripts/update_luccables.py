#!/usr/bin/env python3
"""Luccables public-page collector; not an official LME Cash feed.

Dependencies: requests, beautifulsoup4. HTTPS certificate checks stay enabled.
No bypass of access restrictions. Data is published only when validated.
"""
import csv
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(parents=True, exist_ok=True)
URL = 'https://luccables.it/rame.aspx'
HEADERS = {'User-Agent': 'ProcurementIntelligence/1.0 (public data quality monitor)'}
START_YEAR, START_MONTH = 2026, 1
NUM = r'([0-9][0-9.,]*)'
FX_RE = re.compile(r'\bDOLLARO\s*:\s*' + NUM, re.I)
LME_RE = re.compile(r'\bLME\s*:\s*' + NUM, re.I)
FIELDS = ['date', 'eurusd_bfix', 'copper_eur_t', 'copper_usd_t_derived',
          'source', 'source_url', 'copper_kind']


def parse_number(raw):
    s = raw.strip().replace(' ', '')
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    elif s.count('.') > 1:
        s = s.replace('.', '')
    return float(s)


def extract(html, year, month, source_url):
    soup = BeautifulSoup(html, 'html.parser')
    found = {}
    for cell in soup.select('td'):
        text = cell.get_text(' ', strip=True)
        fx_match = FX_RE.search(text)
        cu_match = LME_RE.search(text)
        if not (fx_match and cu_match):
            continue
        prefix = text[:min(fx_match.start(), cu_match.start())]
        day_matches = re.findall(r'(?<!\d)(\d{1,2})(?!\d)', prefix)
        if not day_matches:
            continue
        day = int(day_matches[-1])
        try:
            quoted_date = date(year, month, day)
            fx = parse_number(fx_match.group(1))
            copper_eur = parse_number(cu_match.group(1))
        except (ValueError, OverflowError):
            continue
        if not (0.5 < fx < 2.5 and 1000 < copper_eur < 50000):
            continue
        key = quoted_date.isoformat()
        found[key] = {
            'date': key,
            'eurusd_bfix': fx,
            'copper_eur_t': copper_eur,
            'copper_usd_t_derived': round(fx * copper_eur, 4),
            'source': 'Luccables',
            'source_url': source_url,
            'copper_kind': 'Luccables EUR/t; derived USD/t; NOT independently verified LME Cash',
        }
    return list(found.values())


def fetch(year, month, session):
    params = {'a': year, 'm': month}
    # Do not automatically follow redirects: diagnose TLS/hostname changes explicitly.
    response = session.get(URL, params=params, headers=HEADERS,
                           timeout=30, allow_redirects=False)
    if response.is_redirect:
        destination = urljoin(response.url, response.headers.get('Location', ''))
        parsed = urlparse(destination)
        raise RuntimeError(
            f'HTTP {response.status_code} redirect to {destination}; '
            f'check the target HTTPS certificate and domain. '
            f'No redirect was followed.'
        )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or 'utf-8'
    result = extract(response.text, year, month, response.url)
    if not result:
        raise RuntimeError(
            f'No valid daily records for {year}-{month:02d}; '
            'HTML layout or published data may have changed.'
        )
    return result


def month_sequence(now, full_history):
    if full_history:
        y, m = START_YEAR, START_MONTH
        while (y, m) <= (now.year, now.month):
            yield y, m
            m += 1
            if m == 13:
                y, m = y + 1, 1
    else:
        for offset in range(3):
            y, m = now.year, now.month - offset
            while m < 1:
                y, m = y - 1, m + 12
            yield y, m


def read_existing(path):
    if not path.exists():
        return []
    loaded = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(loaded, list):
        raise ValueError('Existing Luccables JSON is not an array')
    return loaded


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    now = datetime.now(ZoneInfo('Europe/Rome'))
    if os.getenv('SCHEDULED') == '1' and (now.weekday() > 4 or now.hour != 18):
        print('Outside weekday 18:xx Europe/Rome window; no update')
        return 0

    daily_path = DATA / 'luccables_daily.json'
    csv_path = DATA / 'luccables_daily.csv'
    status_path = DATA / 'luccables_status.json'
    errors = []
    retrieved = 0
    latest = None
    rows = []
    full_history = os.getenv('FULL_HISTORY') == '1' or not daily_path.exists()
    try:
        existing = read_existing(daily_path)
        merged = {r['date']: r for r in existing if isinstance(r, dict) and 'date' in r}
        with requests.Session() as session:
            for y, m in month_sequence(now, full_history):
                try:
                    batch = fetch(y, m, session)
                    for row in batch:
                        merged[row['date']] = row
                    retrieved += len(batch)
                    print(f'{y}-{m:02d}: {len(batch)} records')
                except requests.exceptions.SSLError as exc:
                    errors.append(f'{y}-{m:02d}: HTTPS certificate validation failed: {exc}')
                except requests.exceptions.RequestException as exc:
                    errors.append(f'{y}-{m:02d}: HTTP/network error: {exc}')
                except Exception as exc:
                    errors.append(f'{y}-{m:02d}: {exc}')
        rows = sorted(merged.values(), key=lambda r: r['date'])
        dated = [date.fromisoformat(r['date']) for r in rows
                 if date.fromisoformat(r['date']) <= now.date()]
        latest = max(dated) if dated else None
    except Exception as exc:
        errors.append(f'Collector initialization error: {exc}')

    age = (now.date() - latest).days if latest else None
    status = {
        'checked_at': now.isoformat(),
        'latest_date': latest.isoformat() if latest else None,
        'age_calendar_days': age,
        'retrieved_rows': retrieved,
        'total_rows': len(rows),
        'errors': errors,
        'source': URL,
        'freshness': 'unknown' if age is None else ('recent' if age <= 3 else 'stale'),
        'full_history_attempted': full_history,
        'source_verified_this_run': retrieved > 0,
    }
    write_json(status_path, status)

    # Do not overwrite valid history with an empty or unverified retrieval.
    if retrieved == 0 or latest is None or age > 4 or (now.weekday() < 5 and age > 2):
        print('ERROR: source unavailable or not fresh enough', json.dumps(status, ensure_ascii=False), file=sys.stderr)
        return 1

    if errors:
        print('WARNING: partial month failures: ' + '; '.join(errors), file=sys.stderr)
    write_json(daily_path, rows)
    with csv_path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f'Updated {len(rows)} rows; latest {latest}; retrieved this run {retrieved}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

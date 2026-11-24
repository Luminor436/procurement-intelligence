
#!/usr/bin/env python3
"""Controlla la freschezza dei noli senza inventare quotazioni."""
import csv
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTS = ("Tianjin", "Shenzhen", "Ningbo")
TODAY = dt.datetime.now(dt.timezone.utc).date()
quotes = {port: [] for port in PORTS}

sources = [
    ("freight_quotes.csv", "date", "port", "usd"),
    ("public_freight_rates.csv", "valid_from", "origin", "usd_per_container"),
]

for filename, date_col, port_col, price_col in sources:
    path = ROOT / "data" / filename
    if not path.exists():
        print(f"File non presente: {filename}")
        continue

    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                port = row[port_col].strip()
                date = dt.date.fromisoformat(row[date_col].strip())
                price = float(row[price_col])

                if port not in PORTS or price <= 0 or date > TODAY:
                    continue

                if filename == "public_freight_rates.csv":
                    if "genova" not in row.get("destination", "").lower():
                        continue
                    if row.get("container_type", "").upper() not in ("40HQ", "40HC", "40H"):
                        continue

                category = row.get("category", "").upper()
                carrier = row.get("carrier", "")
                source = row.get("source_url", row.get("source", ""))

                quotes[port].append({
                    "date": date.isoformat(),
                    "usd": price,
                    "carrier": carrier,
                    "category": category or "UNCLASSIFIED",
                    "source": source,
                    "file": filename,
                })
            except (KeyError, ValueError, TypeError, AttributeError):
                continue

result = {}
for port in PORTS:
    items = sorted(quotes[port], key=lambda x: x["date"])
    latest = items[-1] if items else None
    age = (TODAY - dt.date.fromisoformat(latest["date"])).days if latest else None

    if latest is None:
        status = "no_quotes"
    elif age > 30:
        status = "stale"
    else:
        status = "ok"

    result[port] = {
        "status": status,
        "count": len(items),
        "latest_date": latest["date"] if latest else None,
        "age_days": age,
        "latest_quote": latest,
    }

overall = (
    "no_quotes" if all(x["status"] == "no_quotes" for x in result.values())
    else "stale" if any(x["status"] != "ok" for x in result.values())
    else "ok"
)

output = {
    "status": overall,
    "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "ports": result,
    "warning": "Controllare le quotazioni mancanti o obsolete" if overall != "ok" else None,
}

destination = ROOT / "data" / "freight_status.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(output, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8"
)

print(json.dumps(output, indent=2, ensure_ascii=False))

"""Fetch The Numbers weekend domestic box-office charts (public pages; robots.txt allows generic agents),
one request every 3 s, 2024-01-05..2026-10-16 Fridays. Box Office Mojo was NOT used: its robots.txt
disallows all generic agents and its terms prohibit automated access.
Writes per-film-weekend rows to r2-cache/r7boxoffice_weekends.parquet."""
import html
import re
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
RAW = CACHE / "r7boxoffice_html"
RAW.mkdir(exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (academic research script; 1 req / 3 s)"}
ROW = re.compile(r"<tr>\s*<td class=\"data\">(\d+)</td>\s*<td class=\"data\">([^<]*)</td>\s*<td><b><a href=\"([^\"]+)\">([^<]+)</a></b></td>\s*"
                 r"<td class=\"data\">\$([\d,]+)</td>.*?<td class=\"data\">([\d,]*)</td>\s*<td class=\"data\">[^<]*</td>\s*"
                 r"<td class=\"data\">\$([\d,]+)</td>\s*<td class=\"data\">(\d+)</td>", re.S)

d, rows = date(2024, 1, 5), []
c = httpx.Client(headers=H, follow_redirects=True, timeout=30)
while d <= date(2026, 10, 16):
    f = RAW / f"{d}.html"
    if not f.exists():
        r = c.get(f"https://www.the-numbers.com/box-office-chart/weekend/{d:%Y/%m/%d}")
        if r.status_code != 200:
            print(d, r.status_code, flush=True)
            if r.status_code in (403, 429):
                raise SystemExit("blocked; stopping (do not circumvent)")
            d += timedelta(7)
            continue
        f.write_text(r.text)
        time.sleep(3)
    for m in ROW.finditer(f.read_text()):
        rows.append({"weekend": d, "rank": int(m[1]), "prev": m[2].strip(), "slug": m[3], "title": html.unescape(m[4]),
                     "gross": int(m[5].replace(",", "")), "theaters": int(m[6].replace(",", "") or 0),
                     "total": int(m[7].replace(",", "")), "days": int(m[8])})
    d += timedelta(7)
df = pd.DataFrame(rows)
df.to_parquet(CACHE / "r7boxoffice_weekends.parquet")
print(df.groupby("weekend").gross.sum().describe(), len(df))

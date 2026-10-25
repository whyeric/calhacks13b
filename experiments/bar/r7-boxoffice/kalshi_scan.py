"""Scan all Kalshi events (settled/open/closed) for box-office contracts; cache matches in r2-cache."""
import json
import time

import httpx

B = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache/r7boxoffice_events.json"
KEYS = ["box office", "opening weekend", "domestic gross", "gross", "opening weekend"]
c = httpx.Client(timeout=60)
hits, n, t0 = [], 0, time.time()
for st in ["settled", "open", "closed"]:
    cur = None
    while True:
        p = {"limit": 200, "status": st}
        if cur:
            p["cursor"] = cur
        r = c.get(f"{B}/events", params=p)
        if r.status_code == 429:
            time.sleep(2)
            continue
        j = r.json()
        ev = j.get("events", [])
        n += len(ev)
        for e in ev:
            t = (e.get("title", "") + " " + (e.get("sub_title") or "") + " " + e["event_ticker"]).lower()
            if any(k in t for k in KEYS):
                hits.append(e)
        cur = j.get("cursor")
        if not cur or not ev or time.time() - t0 > 1500:
            break
    print(st, n, len(hits), round(time.time() - t0), flush=True)
for e in hits:
    print(e["event_ticker"], "|", e["series_ticker"], "|", e["title"], "|", e.get("sub_title"))
json.dump(hits, open(OUT, "w"))

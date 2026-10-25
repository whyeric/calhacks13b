"""Basis check: does NOAA GHCN TMAX at the four CLI stations reproduce settled Kalshi results?

For every settled KXHIGH* market (threshold T and 2-degree bracket B), recompute the outcome from
GHCN TMAX and count agreement. Run from backend/: .venv/bin/python ../experiments/bar/r4-ercot/basis.py
"""

from __future__ import annotations

import re
from datetime import date

import httpx
import pandas as pd

from ercot import CACHE

SERIES = {"KXHIGHAUS": "USW00013904", "KXHIGHTHOU": "USW00012918",
          "KXHIGHTDAL": "USW00003927", "KXHIGHTSATX": "USW00012921"}
MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
API = "https://api.elections.kalshi.com/trade-api/v2/markets"


def markets(series: str) -> list[dict]:
    p = CACHE / f"r4ercot_kalshi_{series}.json"
    if p.exists():
        return pd.read_json(p).to_dict("records")
    out, cur = [], None
    with httpx.Client(timeout=30) as c:
        for _ in range(20):
            params = {"series_ticker": series, "status": "settled", "limit": 1000} | ({"cursor": cur} if cur else {})
            d = c.get(API, params=params).json()
            out += [{k: m.get(k) for k in ["ticker", "title", "result", "floor_strike", "cap_strike", "strike_type"]}
                    for m in d.get("markets", [])]
            cur = d.get("cursor")
            if not cur:
                break
    pd.DataFrame(out).to_json(p)
    return out


def main() -> None:
    g = pd.read_csv(CACHE / "r4ercot_ghcn.csv")
    g = g.dropna().set_index(["STATION", "DATE"])["TMAX"].to_dict()
    for s, sid in SERIES.items():
        ms = markets(s)
        rows = []
        for m in ms:
            mm = re.match(r".*-(\d\d)([A-Z]{3})(\d\d)-", m["ticker"])
            if not mm or m["result"] not in ("yes", "no"):
                continue
            day = date(2000 + int(mm[1]), MON[mm[2]], int(mm[3])).isoformat()
            if (sid, day) not in g:
                continue
            x, st = g[(sid, day)], m.get("strike_type")
            if st == "greater":
                pred = x > m["floor_strike"]
            elif st == "less":
                pred = x < m["cap_strike"]
            elif st == "between":
                pred = m["floor_strike"] <= x <= m["cap_strike"]
            else:
                continue
            rows.append({"day": day, "ok": pred == (m["result"] == "yes")})
        r = pd.DataFrame(rows)
        if r.empty:
            print(f"{s}: no comparable settled markets")
            continue
        byday = r.groupby("day")["ok"].all()
        print(f"{s} ({sid}): {len(r)} markets on {len(byday)} days {byday.index.min()}..{byday.index.max()}; "
              f"market agreement {r.ok.mean():.4f}; days fully consistent {byday.mean():.4f} "
              f"(mismatch days {int((~byday).sum())})")


if __name__ == "__main__":
    main()

# Dewey series: C3 restaurant choice and sanity numbers

Built by `python -m app.data.dewey build` (from `backend/`) on the raw export in repo-root `data/`
(gitignored). Outputs `backend/fixtures/restaurant_daily.parquet` and
`backend/fixtures/msg_visits_daily.parquet`: daily aggregates, no names, addresses or
coordinates. Both files are gitignored and rebuilt locally with `make seed-data` (D2: Dewey
data may be published only as summaries/insights). This note carries summary numbers only. Folder resolution and day alignment are documented in `dewey.py`.

## Candidates (C3)

Filters: ZIP in 10001/10119/10121, NAICS 722511/722513/722410, weeks from 2024-01-01; 395 stores,
358 eligible (coverage >= 98% of days and >= 200 visits/week). `rise` = mean visits on MSG spike
days / mean visits on non-spike days of the same weekday. Ids are truncated sha256 of `ID_STORE`.

| rank | place_id | weekly visits | median daily | rise | coverage |
|---:|---|---:|---:|---:|---:|
| 1 | p_512bcbdfde5f | 818 | 81 | 1.870 | 1.0 |
| 2 | p_789e21ebfad2 | 2951 | 373 | 1.338 | 1.0 |
| 3 | p_68aa690d99f7 | 2101 | 271 | 1.313 | 1.0 |
| 4 | p_db64f3b3f63d | 986 | 109 | 1.275 | 1.0 |
| 5 | p_632a192f7e08 | 14186 | 1364 | 1.250 | 1.0 |
| 6 | p_eb186f3725b0 | 890 | 114 | 1.244 | 1.0 |
| 7 | p_52e55069c0a9 | 1390 | 152 | 1.241 | 1.0 |
| 8 | p_c584faed3954 | 4125 | 350 | 1.222 | 1.0 |
| 9 | p_8917dd1c1e2c | 419 | 47 | 1.221 | 1.0 |
| 10 | p_7d743e95623b | 880 | 89 | 1.209 | 1.0 |
| **17** | **p_afa556030e60** (chosen) | 1706 | 216 | 1.153 | 1.0 |

**Chosen: `p_afa556030e60`**, shown publicly as "Bar across from MSG". It is the highest-rise
store with NAICS 722410 (drinking place), which matches the demo story; it has ~1,700
visits/week, full 2024-01-01..2026-09-27 history, and a clear same-weekday rise of +15% on MSG
spike nights (+27% raw). The ranks above it are restaurants (722511/722513); #1 is a small
limited-service spot whose 1.87 rise rests on ~80 visits/day. The best-ranked bar
(`p_1fe3c7eccfae`, ZIP 10121, ~13k visits/week) sits inside the MSG/Penn complex, not across
from it. The hash is pinned as `CHOSEN_PLACE_ID` in `dewey.py`; `DEWEY_PLACE_ID` in `.env`
(raw id, never committed) overrides it.

## Sanity numbers

- Window: 2024-01-01 .. 2026-09-27, 1001 days, no missing days, no malformed weeks.
- Chosen bar: median 216 visits/day; mean 298 on spike days vs 235 otherwise.
- MSG: median 33,906 visits/day. The MSG POI includes Penn Station foot traffic, so event
  signal is diluted.
- Spike rule (`SPIKE_WINDOW_DAYS=28`, `SPIKE_MAD_K=2.0`, past-only, unscaled MAD): 138 spike
  days (2024: 44, 2025: 61, 2026 to Sep: 33), about 50/year, below the 100-180/year target.
  K=1.0 gives ~105/year. Downstream `msg_event = home_game OR spike`, so home games are
  covered regardless.
- Alignment (G5): on 15 known 2024 Knicks/Rangers playoff home dates, visits relative to the
  same weekday's prior-4-week median average 1.11 at offset 0, 0.93 at -1 and 1.03 at +1, so
  index 0 = DATE_RANGE_START holds.

## Open

- C6 (Dewey/Yale license quote + link) not yet recorded. Until the user decides D2, the daily
  series are local only.
- C4 `AVG_CHECK_USD` = 35 is a placeholder without a menu link yet.

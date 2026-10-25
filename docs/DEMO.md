# Demo data: sample week vs. real desk runs

## Two modes (`DEMO_SAMPLE_WEEK`, default `1`)

| | `DEMO_SAMPLE_WEEK=1` (default) | `DEMO_SAMPLE_WEEK=0` |
|---|---|---|
| Empty db on API start / `make seed` | Businesses + the example hedges from `backend/fixtures/examples/week_seed.json` and their log entries | Businesses + ledger history only; no example hedges |
| `GET /health` | `sample_week: true`, `sample_businesses: ["restaurant", "taxi"]` until a real run replaces them | `sample_week: false`, `sample_businesses: []`; startup also deletes any sample hedges left in the db |
| `POST /businesses/{id}/desk/run` | Deletes that business/week's sample hedges, then runs the real pipeline (logged: `desk run … replaced sample week hedges …`). A failed run puts them back. | Runs the real pipeline |

The sample hedges are example data: they don't match `/analyze` (for example, a Knicks hedge for the
bar, whose `home_win` isn't hedgeable). The frontend labels them "sample week" from
`/health.sample_week` / `sample_businesses` (I6). After a real run, `/decisions` hides the sample
entries about replaced hedges. They are still stored, because the log is append-only.
Owner-approved or settled sample hedges are never deleted, since they have ledger entries.

## The pinned demo week (`DEMO_AS_OF`)

The committed cache was warmed Sat 2026-10-24 ~23:10 UTC, and its markets close over the next few
days. `make demo` sets `DEMO_AS_OF=2026-10-24T19:00:00Z`: the API clock starts at that instant and
moves forward with real time from there, so the desk week is **Mon 2026-10-26**, approval expiry and
offline market matching follow the cached week, and the demo doesn't depend on today's date. Set
`DEMO_AS_OF` in `.env` (or `DEMO_AS_OF= make demo` to unset) when you re-warm for another week.
`make api` / `make dev` use the real clock unless `.env` sets it.

The desk only matches markets about a day **inside** the desk week (Mon–Sun). A Saturday run for the
week of Oct 26 no longer picks Sunday Oct 25's `KXRAIN-26OCT25-NYC`.

## Backtest

`make seed` (and API startup, when the row is missing) stores the walk-forward backtest for every
business that has data (`python -m scripts.run_backtest --if-missing`, offline from the feature
fixtures and `fixtures/kalshi_history/`). `GET /businesses/{id}/backtest` therefore answers on a
fresh db. On a fresh clone only taxi has one; the restaurant gets one once its Dewey series exist.
After changing thresholds, `python -m scripts.run_backtest` (from `backend/`) recomputes and stores.

## Real pipeline today (offline, committed Kalshi cache, `DEMO_AS_OF` week)

- **taxi**: one `declined` hedge on `exp_rain`, reasons `no_market` + `unstable`. The cache has no
  NYC rain market for a day in the week of Oct 26, and the recent-window refit of rain
  (+$228 [−$1,885, +$2,342] vs +$2,080 [+$386, +$3,775] on train) crosses zero. No payoff table.
- **restaurant** (needs the Dewey series): the `playoff_home` season hedge, three legs on the
  Knicks futures (group total $3,059.50): "Knicks don't win the title" (`KXNBA-27-NYK`, 84 NO,
  $78.51) is **proposed** within the $250 budget; "Knicks miss the playoffs" (1,251 of 2,462
  filled, $260.94) and "Knicks don't win the East" ($2,720.05) are **pending_approval**
  (`over_budget`). Approving the title leg books it. Rain and game results are dropped as not
  significant. Without the Dewey files the restaurant run fails contained (`analysis_unavailable`)
  and its sample week stays.

## Taxi numbers with and without the Dewey files

The MSG-event control (`msg_event`) uses Dewey visit spikes for the **restaurant only**. The taxi
table is `home_game` alone either way, so taxi numbers are the same on a fresh clone and with
`msg_visits_daily.parquet` built: rain +$2,080/day (it used to read +$2,245 with the file).

`tests/api/test_sample_week.py` checks that every non-sample proposed/pending hedge is for a
hedgeable exposure from `/analyze`.

## Getting a fresh real decision for the demo

The payoff table needs a two-sided book with depth on the rain `no` side, so warm the cache close
to demo time, when books are live:

1. Online, from the repo root: `make warm` (runs `python -m app.markets.warm` in `backend/`). It
   prints each candidate with `yes_ask`/`no_ask` and `depth5c`. Go ahead only if the taxi `rain`
   line shows a `no_ask` and nonzero `no` depth. Otherwise re-run later.
2. Replay offline: `DEMO_OFFLINE=1 make api`, then click **Run desk** for taxi (or
   `curl -XPOST localhost:8000/businesses/taxi/desk/run -H 'content-type: application/json' -d '{}'`).
   The run replaces the sample week. `GET /businesses/taxi/hedges` should show a `proposed` or
   `pending_approval` hedge, and the server log should have no `CacheMiss`.
3. Commit `backend/fixtures/kalshi_cache/` (public market data, committed per ACCEPTANCE-demo
   decision 5) before the demo freeze.
4. To present only real data, start with `DEMO_SAMPLE_WEEK=0 make demo` (or `make clean` first for
   a fresh db). With the default `1`, the sample week shows, labeled, until the first desk run.

## Try it: upload the sample

The report (`POST /research`) and the hedge quote (`POST /research/quote`) are computed live on the
uploaded file; nothing is stored. Full details are in
[UPLOAD_AND_RESEARCH.md](UPLOAD_AND_RESEARCH.md).

1. Have `hudson_bike_co_daily_revenue.csv` ready. It's in `frontend/public/samples/`, and the
   presenter's copy is in `~/Downloads/`.
2. On `make demo`, click **Upload your revenue** and choose the file. The app shows the file's real
   row count and dates (1,004 days, 2024-01-01 to 2026-09-30).
3. Click **Upload and research**. The backend runs the protocol live (`POST /research`); a
   "Running analysis…" bar shows for about 2.5 seconds, then the report appears.
   - Rain is FOUND: −18.2% (−$1,923.43/day) on 2024, −20.4% on 2025–26, placebo p 0.29.
   - Cold <40 °F is FOUND (−26.5% / −26.4%), and warm >80 °F is FOUND as an upside
     (+10.9% / +15.5%).
   - Hot >90 °F, Knicks home games and Knicks wins are not distinguishable from zero.
4. Click **Send to the desk** on rain. The live quote scans Kalshi and Polymarket for the next 8
   days on the committed caches: 1,923 YES on `KXRAIN-26OCT25-NYC` for $20.57, every check passing,
   with the Polymarket market it also scanned listed on the card. It's a quote (not saved).

## Roles, co-sign and close

`make demo` and `make dev` set `OWNER_TOKEN=demo-owner` and `CONTROLLER_TOKEN=demo-controller` (and
bake the same values into the frontend build as `NEXT_PUBLIC_*`). Without the right token the API
answers `403 owner_only` / `403 controller_only`, so the desk, or anyone calling the API without a
role's token, can't approve, co-sign or close. Override them (`make demo OWNER_TOKEN=…`) outside a
demo. The header's **Acting as** switch picks which token the browser sends. The flow to show:

1. Owner tries to approve the taxi's $942.80 hedge: `409 needs_controller` (materiality $200.00).
2. Controller co-signs (or refuses); then the owner approves (or can only reject).
3. Books tab, as Controller: close through 2026-10-23. The planted $0.89 short deposit returns
   `409 unreconciled` until it's acknowledged and carried as an exception.

## Re-warming Polymarket

`make warm` also refreshes `backend/fixtures/polymarket_cache/` for the desk week and the next 8
days as of `DEMO_AS_OF`; `python -m app.markets.warm --polymarket-only` leaves the Kalshi cache
alone. Game markets are looked up one slug per scheduled New York home game (the ESPN schedule
fixtures), so the cache stays small. Commit it with the Kalshi cache before the demo freeze.

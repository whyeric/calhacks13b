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

## Try it with your own revenue

Uploads and research run on `make demo` with no network. Without `ANTHROPIC_API_KEY`, research
uses the deterministic fallback plan (`agent: "fallback"`). The full guide is
[UPLOAD_AND_RESEARCH.md](UPLOAD_AND_RESEARCH.md).

1. **Upload.** Click **Upload your revenue**, enter a name and a type, and choose a `date,revenue`
   CSV (≥ 540 days inside the cached weather/schedule window). For the demo, use the drawer's
   synthetic `sample_revenue_nyc_bike_shop.csv` with type `shop`. On 201 the app switches to the new
   business, with an **Uploaded** badge in the switcher.
2. **Research.** Click **Research my risks**. The UI POSTs `/businesses/{id}/research`, polls
   `/runs/{run_id}` (`kind: "research"`) and then shows the report: the summary, then one row per
   hypothesis with the mechanism, train vs holdout effect and CI, the placebo, the verdict badge,
   reasons in plain language and the Kalshi series.
3. **Send to the desk.** On the FOUND, hedgeable rain row, click **Send to the desk** (POST
   `.../research/{hypothesis_id}/promote`). The exposure appears in `/analyze` with
   `source: "research"`. Click **Run desk** and the desk prices a `KXRAIN` hedge for it, or declines
   it with reasons, under the same six rules.
4. **Clean up.** Use the switcher's delete action (`DELETE /businesses/{id}`, 204). Built-ins
   return 403 `not_uploaded`.

What the bike-shop sample gives on the committed cache (*fill in after integration*):

- research verdicts: *n_tested / n_found, and rain's train → holdout effect and CI*;
- the desk outcome for the promoted rain exposure in the week of Oct 26: *proposed / pending /
  declined, plus reasons*. The week of Oct 26 has no NYC rain market for a day inside the desk week
  (see the taxi result above), so a `no_market` decline is possible unless the cache is re-warmed.
  Check this before rehearsing.

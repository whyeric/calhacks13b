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

## Real pipeline today (offline, committed Kalshi cache)

- **taxi**: one `declined` hedge on `exp_rain`, reason `illiquid` (the cached book filled 0 of
  1307 contracts). There's no proposal, so there's no payoff table.
- **restaurant**: no hedges. The bar has no hedgeable exposure (see `experiments/bar/SUMMARY.md` on branch `experiments/bar`).

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

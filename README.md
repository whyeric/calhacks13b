# Hedge Desk

Hedge Desk measures how much a small business's daily revenue moves with weather and game days,
looks for a Kalshi contract that settles on that event, and sizes a hedge so it never covers more
than the measured exposure. Every hedge has to pass six decline rules before the desk proposes it
to the owner, and only the owner can approve. Approved hedges are booked to a Beancount ledger and
reconciled against Kalshi and the bank at settlement. **It never places real orders.**

The demo has two businesses around Madison Square Garden. One is a taxi fleet (real NYC trip
records). The other is a bar across from MSG (real foot traffic, estimated dollars).

The app also runs the **research protocol live on an uploaded revenue file**. Upload any daily
`date,revenue` CSV (the drawer offers a fictional bike shop's: synthetic revenue on real NOAA
Central Park weather), and `POST /research` tests six pre-registered risks with train/holdout
replication, Benjamini–Hochberg and a placebo, in about a second. Nothing is stored.

## Quickstart

You need Python 3.12, Node 18.18+ and `make`.

```bash
make install     # backend venv (backend/.venv) + frontend npm ci
make seed        # SQLite schema, both businesses, sample week, demo books, backtest; fixtures only, no network
make demo        # offline (DEMO_OFFLINE=1, clock pinned by DEMO_AS_OF): API on :8000, frontend on :3000
```

Open <http://localhost:3000> once `make demo` prints `Hedge Desk ready`. The demo runs with **no
network and no API key**: Kalshi reads come from the committed cache in
`backend/fixtures/kalshi_cache/`. Without `ANTHROPIC_API_KEY`, the desk uses its deterministic
fallback agent (`agent: fallback`).

Optional steps:

```bash
cp .env.example .env   # set ANTHROPIC_API_KEY / ANTHROPIC_MODEL to use Claude
make seed-data         # rebuild the daily series from raw data/ (needs the Dewey export + network)
make warm              # online, once: refresh the Kalshi cache, then replay offline and diff
make dev               # hot-reload API + Next dev server, live Kalshi if online
make test              # backend pytest + frontend typecheck
make e2e               # C8 end-to-end suite: sockets blocked, no key (tests/e2e/)
make clean             # drop the SQLite db, generated ledgers and the frontend build (never fixtures)
```

`make demo DEMO_WEB=0` serves only the API. `DEMO_SAMPLE_WEEK=0 make demo` starts without the
labeled sample week. See [docs/DEMO.md](docs/DEMO.md).

## Try it: upload the sample

*The report is computed live by `POST /research` on whatever file you pick; nothing is stored.
The hedge card behind **Send to the desk** is still a scripted example, and is labeled so.*

1. `make demo`, then open <http://localhost:3000>.
2. Click **Upload your revenue** and choose `hudson_bike_co_daily_revenue.csv` (in
   `frontend/public/samples/`, and linked from the drawer). The app reads the file's real row count
   and date range: 1,004 days, 2024-01-01 to 2026-09-30.
3. Click **Upload and research**. The backend runs the protocol (a "Running analysis…" bar shows
   for a couple of seconds), then the report appears with each risk's pre-registered mechanism.
   On the sample, rain, cold and warm days are FOUND; hot days and Knicks games aren't. Any other
   NYC-area file from 2024-01-01 to 2026-09-30 with at least 540 days works the same way.
4. On the rain row, click **Send to the desk** to see the (scripted, labeled) hedge card.

See [docs/UPLOAD_AND_RESEARCH.md](docs/UPLOAD_AND_RESEARCH.md) for the protocol, the API, what's
still scripted and the full results.

**Restaurant data on a fresh clone.** The bar's daily series (`restaurant_daily.parquet`,
`msg_visits_daily.parquet`) come from Dewey and are gitignored under its license. On a fresh clone,
the bar's analysis therefore returns `analysis_unavailable`, and the rest of the app still works.
To get the bar's full analysis, put the raw export under `data/` and run `make seed-data`.

## What's real and what's simulated

| | Status |
|---|---|
| Taxi fares (NYC TLC, zone 186 Penn Station/Madison Sq West), weather, Knicks/Rangers games, Kalshi markets and prices | **Real** |
| Bar foot traffic (Dewey / Advan, aggregates only) | **Real** |
| Bar dollars (visits × an assumed $35 average check) | **Estimated**, labeled in the UI |
| The "sample week" of hedges shown before the first desk run | **Example data**, labeled "sample week" |
| Hedge settlements and the bank statement (with one planted short deposit) | **Simulated**, from real settled Kalshi results |
| Hudson Bike Co. sample revenue | **Synthetic** (fictional shop, planted effects) on **real** NOAA Central Park weather |
| The upload → research report | **Live**: `POST /research` runs the protocol on the uploaded file (nothing stored) |
| The hedge card behind "Send to the desk" | **Scripted** example, labeled on the card |
| Trades | **None**: nothing is ever sent to Kalshi |

In the pitch and the UI, the bar is only ever called "a bar across from MSG".

## Docs

- [docs/SPEC.md](docs/SPEC.md): the spec, the source of truth for behavior
- [docs/CONTRACTS.md](docs/CONTRACTS.md): cross-chunk contract decisions
- [docs/PLAN.md](docs/PLAN.md): chunks, gates and conventions
- [docs/DEMO.md](docs/DEMO.md): sample week vs real desk runs, and re-warming the cache
- [docs/ACCEPTANCE-demo.md](docs/ACCEPTANCE-demo.md): the C8 demo acceptance tests
- [docs/UPLOAD_AND_RESEARCH.md](docs/UPLOAD_AND_RESEARCH.md): the live upload + research protocol, its API and results
- [docs/RESEARCH.md](docs/RESEARCH.md): what we tested, what replicated, and what didn't
- [docs/PITCH.md](docs/PITCH.md): the 2-minute demo script, track pitches and the Devpost draft
- [AGENTS.md](AGENTS.md): guidance for coding agents

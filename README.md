# Hedge Desk

Hedge Desk measures how much a small business's daily revenue moves with weather and game days,
looks for a Kalshi contract that settles on that event, and sizes a hedge so it never covers more
than the measured exposure. Every hedge has to pass six decline rules before the desk proposes it
to the owner, and only the owner can approve. Approved hedges are booked to a Beancount ledger and
reconciled against Kalshi and the bank at settlement. **It never places real orders.**

The demo has two businesses around Madison Square Garden. One is a taxi fleet (real NYC trip
records). The other is a bar across from MSG (real foot traffic, estimated dollars).

You can also **upload your own daily revenue** and click **Research my risks**. Claude
pre-registers which events should matter and why, and a fixed harness tests each one with
train/holdout replication, Benjamini–Hochberg correction and a placebo against the NOAA settlement
station. Claude does the analyst's work but never produces a number. Risks that come back FOUND can
be sent to the desk to be priced.

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

## Try it with your own revenue

1. `make demo`, then open <http://localhost:3000>.
2. Click **Upload your revenue**. Give a name (1–60 characters) and a type (bar, restaurant, shop,
   transport or other), and choose a CSV with `date,revenue` columns. You need at least 540 days
   inside the cached NYC weather/schedule window. No data handy? Download a sample from the drawer
   (`sample_revenue_nyc_bike_shop.csv` or `sample_revenue_msg_sports_bar.csv`; both are
   **synthetic**).
3. The app switches to your business. **Run desk**, the backtest, the ledger and chat all work on
   it.
4. Click **Research my risks**. When the report lands, read each hypothesis's verdict and reasons.
   On a FOUND row with a Kalshi series, click **Send to the desk**, then **Run desk**.

The same thing from the shell:

```bash
curl -F name="Hudson Bikes" -F kind=shop -F file=@sample_revenue_nyc_bike_shop.csv \
     localhost:8000/businesses/upload                                  # -> {"id": "up_...", ...}
curl -XPOST localhost:8000/businesses/$ID/research -H 'content-type: application/json' -d '{}'
curl localhost:8000/runs/$RUN_ID                                       # poll until done
curl localhost:8000/businesses/$ID/research                            # the ResearchReport
curl -XPOST localhost:8000/businesses/$ID/research/$HYP_ID/promote     # send a FOUND risk to the desk
```

Your revenue is stored in the local SQLite database only and is never sent to Kalshi. The data is
NYC only (NOAA Central Park, Knicks/Rangers). Research runs offline with the deterministic fallback
when there's no `ANTHROPIC_API_KEY`. See [docs/UPLOAD_AND_RESEARCH.md](docs/UPLOAD_AND_RESEARCH.md)
for the CSV format, the errors, the protocol, the verdicts and the limitations.

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
| Uploaded revenue | **Yours**: stored locally, analysed as-is (`data_label: "uploaded"`) |
| The two sample revenue CSVs | **Synthetic**, seeded with planted effects, labeled |
| Trades | **None**: nothing is ever sent to Kalshi |

In the pitch and the UI, the bar is only ever called "a bar across from MSG".

## Docs

- [docs/SPEC.md](docs/SPEC.md): the spec, the source of truth for behavior
- [docs/CONTRACTS.md](docs/CONTRACTS.md): cross-chunk contract decisions
- [docs/PLAN.md](docs/PLAN.md): chunks, gates and conventions
- [docs/DEMO.md](docs/DEMO.md): sample week vs real desk runs, and re-warming the cache
- [docs/ACCEPTANCE-demo.md](docs/ACCEPTANCE-demo.md): the C8 demo acceptance tests
- [docs/UPLOAD_AND_RESEARCH.md](docs/UPLOAD_AND_RESEARCH.md): uploading your revenue, the research loop, the API and the limits
- [docs/RESEARCH.md](docs/RESEARCH.md): what we tested, what replicated, and what didn't
- [docs/PITCH.md](docs/PITCH.md): the 2-minute demo script, track pitches and the Devpost draft
- [AGENTS.md](AGENTS.md): guidance for coding agents

# C8 · Demo ops & integration

> Cross-chunk conflicts are resolved in [CONTRACTS.md](CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | Repo-root ops: `make dev/demo/seed`, `.env.example`, `.gitignore`, `DEMO_OFFLINE=1` end to end, cache warming, fallbacks, the 2-minute demo, Devpost real-vs-estimated text, track pitches, checkpoint gates and cut list, notebooks |
| **Files** | `Makefile`, `.env.example`, `.gitignore`, `notebooks/01_taxi.ipynb`, `notebooks/02_restaurant.ipynb`, `notebooks/03_exposure.ipynb`, `fixtures/kalshi_cache/`, `fixtures/schedule_{team}.csv`, `fixtures/bank_statement.csv`, `tests/e2e/` |
| **Spec sections** | §1 (I1–I6), §2, §14, §15, §16, §17, §12 (stack, `.gitignore`, env) |
| **Owner role** | Frontend and story (with integration help from every role) |
| **Depends on** | C1 Data, C2 Stats, C3 Markets, C4 Agent/policy/log, C5 Books, C6 API/models/db, C7 Frontend. C8 owns Demo ops/Makefile/offline and integration |
| **Gate** | 9 PM backend e2e + Devpost draft; 2 AM cache warmed + video recorded on `DEMO_OFFLINE=1`; 7 AM bug fixes only |

## Interfaces

### Make targets

| Target | Does |
|---|---|
| `make install` | `uv`/`pip` install backend deps, `npm ci` in `frontend/` (not in spec; see gaps) |
| `make seed` | Builds from committed fixtures only (no network): creates SQLite schema, loads `fixtures/businesses/*.json`, writes `ledgers/*.beancount` headers, loads `bank_statement.csv`. Idempotent; safe to rerun |
| `make seed-data` | Optional, needs raw `data/` + network: rebuilds `fixtures/*.parquet` from TLC/Dewey/Open-Meteo/ESPN |
| `make dev` | uvicorn `--reload` on :8000 and `next dev` on :3000; live Kalshi if online; `ANTHROPIC_API_KEY` used if set |
| `make demo` | `DEMO_OFFLINE=1`, production-mode frontend build, uvicorn without reload, runs `seed` first, prints URL when `/healthz` is OK |
| `make warm` | Online once: hits every Kalshi endpoint the desk uses for both businesses and the backtest, writes `fixtures/kalshi_cache/`, then replays offline and diffs |
| `make test` | pytest (all chunks) + frontend typecheck/lint |
| `make e2e` | Runs the C8-A tests with sockets blocked |
| `make clean` | Removes SQLite file and `ledgers/*.beancount` (not fixtures) |

### Env vars (`.env.example`, every key present, no real values)

| Var | Default in example | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Empty means fallback agent mode |
| `ANTHROPIC_MODEL` | pinned model ID | Pinned, never "latest" |
| `KALSHI_BASE_URL` | `https://external-api.kalshi.com/trade-api/v2` | |
| `DEMO_OFFLINE` | `0` | `1` = cache only, no outbound HTTP at all |
| `DATABASE_URL` | `sqlite:///./hedge_desk.db` | |
| `WEEKLY_BUDGET_DEFAULT` | `250` | |
| `AVG_CHECK_USD` | `35` | Labeled "assumed" if C4 unresolved |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend only |

### Offline cache layout

| Path | Contents | Committed? |
|---|---|---|
| `fixtures/kalshi_cache/{sha1(method+path+sorted_query)}.json` | Raw response + `{url, fetched_at}` | Yes (public market data) |
| `fixtures/kalshi_cache/index.json` | Key to human-readable request map, used by `make warm` diff | Yes |
| `fixtures/schedule_{knicks,rangers}.csv` | Home games and results for the demo week | Yes |
| `fixtures/{taxi,restaurant,msg_visits}_daily.parquet` | Aggregated daily series only | Yes |
| `fixtures/weather_daily.parquet` | Open-Meteo daily and hourly, cached at import | Yes |
| `data/`, raw TLC and Dewey exports, `.env`, `*.db` | | No (gitignored) |

Cache miss under `DEMO_OFFLINE=1` must raise `OfflineCacheMiss` (loud, logged), never a silent network call.

## Automated acceptance tests

Network blocking: `tests/e2e/conftest.py` patches `socket.socket.connect` to raise for non-loopback addresses; `ANTHROPIC_API_KEY` unset.

| ID | Test name | Future test file path | Setup/fixture | Assertion |
|---|---|---|---|---|
| C8-A1 | fresh_clone_boots_offline | `tests/e2e/test_boot.py` | `git clone` (or `git worktree`) of HEAD into tmp dir, sockets blocked, key unset, `.env` absent, then `make seed && make demo` | Exit 0; `/healthz` 200; `GET /businesses` returns both businesses; zero blocked-socket attempts recorded |
| C8-A2 | env_example_complete | `tests/e2e/test_env.py` | Parse `.env.example` and `config.py` settings | Every var in spec §12 plus `NEXT_PUBLIC_API_URL` present; no value matches `sk-ant-`; app boots with only `.env.example` copied |
| C8-A3 | cold_start_time | `tests/e2e/test_boot.py` | As A1, timed | `make demo` to first `/healthz` 200 under N s (default N=20); `POST /analyze` for either business under 5 s |
| C8-A4 | e2e_taxi | `tests/e2e/test_smoke_taxi.py` | `DEMO_OFFLINE=1`, `business_id=taxi`, fallback agent | `analyze` returns exposures; `desk/run` finishes; each hedge has market, `size_hedge` (N ≤ ceil(h·\|β\|/$1)), decision with `checks`, log entries (I5); approved hedge writes ledger entries; `reconcile` runs |
| C8-A5 | e2e_restaurant | `tests/e2e/test_smoke_restaurant.py` | Same, `business_id=restaurant` | Same chain; every response carries `estimated: true`; rain `hedge_side` is `yes` and taxi's is `no` (opposite direction) |
| C8-A6 | demo_week_outcome_mix | `tests/e2e/test_demo_week.py` | Warmed cache, default budget and thresholds, run both businesses | At least one hedge `declined` with non-empty `reasons`, at least one `pending_approval`, at least one `approved`-eligible within budget; each declined hedge appears in `GET /hedges` (I3) |
| C8-A7 | pending_not_self_approved | `tests/e2e/test_demo_week.py` | Pending hedge from A6 | No ledger entry for it; `approve` with `actor != owner` returns 403; owner approve books it (I4) |
| C8-A8 | reconcile_one_mismatch | `tests/e2e/test_reconcile.py` | Settle simulated from cached `result`s, `fixtures/bank_statement.csv` with planted error | `POST /reconcile` returns exactly 1 mismatch, with an explanation naming the amount (e.g. fee short); all other lines match; the mismatch is in the decision log |
| C8-A9 | declined_flips_with_threshold | `tests/e2e/test_demo_week.py` | Declined hedge from A6; PATCH setting for its failing rule | Re-evaluating flips the status; both evaluations logged |
| C8-A10 | offline_never_touches_network | `tests/e2e/test_offline.py` | `DEMO_OFFLINE=1`, spy on `httpx` transport and DNS | Zero outbound requests across the full A4 and A5 flows; deleting one cache file yields `OfflineCacheMiss`, not a live call |
| C8-A11 | fallback_agent_marked | `tests/e2e/test_fallback.py` | No API key, then a mocked erroring Claude | All entries `agent: fallback`; summary numbers all appear in `checks` (I2); desk still completes |
| C8-A12 | no_raw_data_tracked | `tests/e2e/test_repo_hygiene.py` | `git ls-files` | No path under `data/`; no `*.parquet` outside `fixtures/`; no fixture parquet over 5 MB; no file with columns `visits_by_day`, `PLACEKEY`, `tpep_pickup_datetime`; no fixture contains per-trip or per-weekly-visit rows (C6 license check) |
| C8-A13 | secrets_not_tracked | `tests/e2e/test_repo_hygiene.py` | `git ls-files`, `git grep` | `.env` and `*.db` untracked and matched by `.gitignore`; `git grep -E "sk-ant-\|ANTHROPIC_API_KEY=.+"` finds nothing outside docs; `.gitignore` itself tracked |
| C8-A14 | public_naming | `tests/e2e/test_repo_hygiene.py` | `git grep -i` for the real venue's name (list in a local, untracked `.naming-denylist`) | Zero hits in tracked files, API responses, and UI strings; fixtures use "Bar across from MSG" |
| C8-A15 | labels_present_in_api | `tests/e2e/test_labels.py` | Responses from `/businesses`, `/analyze`, `/ledger` | Restaurant has `estimated: true`; ledger and reconcile payloads carry `simulated: true` (I6) |
| C8-A16 | notebooks_run_offline | `tests/e2e/test_notebooks.py` | `nbconvert --execute` on the 3 notebooks, sockets blocked | All execute on committed fixtures with no error; 03 shows planted-vs-recovered with CI containing 500 |
| C8-A17 | make_targets_exist | `tests/e2e/test_make.py` | `make -n <target>` | `dev`, `demo`, `seed`, `warm`, `test` all resolve without error |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C8-H1 | Beat 1 (0:00–0:15) bad week | Stopwatch dry run on `make demo` | Worst week before/after on screen by 0:05; line spoken in plain words; under 15 s |
| C8-H2 | Beat 2 (0:15–0:45) find the risk | Timed; click Run desk | Exposures render with CI bars within 5 s; at least one "measured, not hedged" with reason visible; under 30 s |
| C8-H3 | Beat 3 (0:45–1:15) protect it | Timed | Real market, sized, payoff chart both outcomes with premium, "Unhedged swing / hedged swing / cost" line readable from 2 m away |
| C8-H4 | Beat 4 (1:15–1:40) the moment | Timed; rehearse threshold drag | Decline with numbers read aloud OR planted deposit caught; a judge-style threshold move flips a decision in under 10 s |
| C8-H5 | Beat 5 (1:40–2:00) proof | Timed; business switch | Model check shows $500 recovered, backtest headline, switch to restaurant shows opposite rain direction; total run under 2:00, three consecutive times |
| C8-H6 | Language | Listen to first minute | No "hedge ratio" or "basis risk"; uses "insurance for a single Saturday" |
| C8-H7 | Wi-Fi-off rehearsal | Turn Wi-Fi off, reboot machine, `make demo`, run beats 1–5 | Identical result to online run; no spinner longer than 3 s; no error toast |
| C8-H8 | Cold cache, hot demo day | After 2 AM warm, delete nothing, open in a fresh browser profile | No cache miss in server log for the full run |
| C8-H9 | Devpost real-vs-estimated text | Read against spec §14 and each data source | States: taxi fares, weather, games, Kalshi prices real; restaurant visits real, dollars estimated (visits × average check); settlements and bank statement simulated from real results; no real trades. No claim stronger than the data |
| C8-H10 | Public naming | Read Devpost, video, slides, UI | "A bar across from MSG" everywhere; no venue name; no raw-data screenshots; Dewey attributed, aggregates only |
| C8-H11 | Demo video | Watch end to end | Recorded on `DEMO_OFFLINE=1`; under 2 min or the Devpost limit; audio clear; shows decline moment and model check |
| C8-H12 | Hyphenate claim | Map each claim to a screen | Limits/approvals (pending card), decision log, books (ledger tab), sources that disagree (rule 4 numbers), planted errors (model check, reconcile) all visible in demo |
| C8-H13 | Microsoft claim | Map each claim | Customer shown (fleet, bar), usefulness = backtest strip, never over-hedges = N ≤ cap visible, production path stated in one sentence |
| C8-H14 | Anthropic claim | Map each claim | Named community stated; chat answers "why?" with numbers from `checks`; "Claude never produces a number" demonstrated by a rejected log entry or tool-sourced chat |
| C8-H15 | Track count | Check Devpost form | Sponsor tracks selected within the form's limit |
| C8-H16 | Three pitch rehearsals at 7 AM | Different presenters/listeners | Each within 2:00; no code changes after except bug fixes |

## Gate checklist

Test IDs are generic per chunk: C1-A* data, C2-A* stats, C3-A* markets, C4-A* agent, C5-A* books, C6-A* API, C7-A* frontend.

| Gate | Must be green | Cut-list trigger |
|---|---|---|
| 3:30 PM | Spec C1–C6 checks answered and recorded; interfaces §5, §7, §8 locked; example JSON per object in `fixtures/` (C6-A* schema tests pass against them); frontend renders from fixtures (C7-A*); `.gitignore`, `.env.example`, `Makefile` skeleton committed; C8-A12, A13, A17 pass | Any C-check unanswered: apply its spec default and note it in Devpost |
| 6:00 PM | C1-A* (both feature tables), C2-A* exposure fit + model check; notebooks 01–03 run (C8-A16) | Dewey or restaurant series not built: restaurant goes to cut-list position 5 early |
| 9:00 PM | C3-A*, C4-A*, C5-A* booking, C6-A* API on live Kalshi; C8-A1, A4 (taxi), A5 if restaurant alive; dashboard on real API (C7-A*); Devpost draft submitted | If any slips, cut in order: (1) settings drawer, (2) approval timing, (3) real-priced backtest, (4) reconciliation, (5) restaurant. Never cut: decline moment, payoff table with premium, model check, decision log, ledger booking |
| Midnight | Real-priced backtest (C2-A*), reconcile mismatch (C5-A*, C8-A8), chat "why?" (C4-A*), decline verified on live data (C8-A6); all of C8-A1…A17 | Backtest not real-priced: frequency pricing, labeled; reconcile unreliable: drop to ledger only |
| 2:00 AM | `make warm` run online, then C8-A10 green; C8-H7, H8 done; video recorded on `DEMO_OFFLINE=1` (H11); `main` tagged `demo-freeze` | Any cache miss: re-warm once; if still missing, remove that business from demo path |
| 7:00 AM | Three rehearsals (H16); full `make test` + `make e2e` green on a fresh clone; Devpost text reviewed (H9, H10) | Bug fixes only; feature requests rejected |
| 8:30 AM | Devpost submitted with video, repo link, tracks (H15); `git status` clean; fresh-clone A1 re-run | Submit what is green; do not merge anything unverified |

## Definition of done

- Fresh clone, no network, no API key: `make seed && make demo` serves the full 2-minute demo (C8-A1, A3, A10).
- Both businesses complete the exposures → market → size → decide → book → reconcile chain (A4, A5), with one declined, one pending, and exactly one reconciliation mismatch (A6, A8).
- Every invariant I1–I6 is observable in the demo or asserted in tests.
- No raw Dewey/TLC rows, `.env`, keys, or venue name in git (A12–A14).
- All H1–H16 signed off by a named person; three timed rehearsals under 2:00.
- Devpost real-vs-estimated statement matches the shipped data; video recorded; submitted by 9:00 AM with a fresh-clone check.

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| 1 | Spec defines no `make install`, `warm`, `test`, `e2e` targets or the cache key scheme | Add them as listed above; cache key = sha1 of method + path + sorted query |
| 2 | "Fresh clone boots" conflicts with `data/` and raw exports being gitignored | `make seed` uses committed aggregate fixtures only; `seed-data` is the only target that needs raw data |
| 3 | Startup-time budget N not specified | N = 20 s to healthy, 5 s per analyze |
| 4 | Whether committing aggregated Dewey-derived daily series is license-safe (C6 unresolved) | Commit only the single-venue daily series and MSG daily visits (aggregates, no weekly rows); if the license check fails, ship synthetic-noised restaurant fixture and label it |
| 5 | Kalshi cache committed vs. gitignored (spec silent) | Commit; it is public market data and is required for a fresh-clone demo. Re-warm at 2 AM and commit before freeze |
| 6 | Which hedge is declined and which is pending in the demo week is data-dependent and not guaranteed | If natural data yields none, set demo-week budget and thresholds in `fixtures/businesses/*.json` (not code) to produce both; document in the runbook, and keep the settings drawer thresholds editable for the live flip (this raises the cost of cutting the drawer) |
| 7 | Planted reconciliation mismatch location and amount unspecified | Bank deposit short by the Kalshi fee on one settled hedge; defined in `fixtures/bank_statement.csv`, never randomized |
| 8 | No-API-key mode: spec says fallback only on slow/error | Treat empty `ANTHROPIC_API_KEY` as fallback mode with `agent: fallback` labels; demo can run either way |
| 9 | Public naming enforcement has no mechanism | Local untracked `.naming-denylist` used by C8-A14 |
| 10 | Time conflict: 9 PM gate says "live Kalshi" but Kalshi markets for the demo week may close before judging | Warm cache with the demo-week series; pin the demo "as of" date in `config.py` so offline replay is consistent |
| 11 | Devpost sponsor track limit unknown (spec §17) | Check form at 3:30 PM; default order: Hyphenate, Anthropic, Microsoft |
| 12 | Owner for notebooks and demo video unspecified beyond roles | Notebooks: Data (executed by C8-A16); video: Frontend and story |

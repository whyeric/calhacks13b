# C6 · API, models & contracts

> Cross-chunk conflicts are resolved in [CONTRACTS.md](../../docs/CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | FastAPI app, pydantic/sqlmodel models, SQLite storage, config/env, business fixtures, and one example JSON per shared object. The contract hub: other chunks import `models.py`; the frontend codes against the routes and examples. |
| **Files** | `backend/app/main.py`, `config.py`, `models.py`, `db.py`, `fixtures/businesses/*.json`, `fixtures/examples/*.json`, `backend/tests/contract/` |
| **Spec sections** | §1 (I2–I5), §5 (Exposure), §8 (Decision), §10 (BacktestResult), §12 (stack, env, API, Decimal rule), §15, §16 (3:30 PM gate) |
| **Owner role** | Integration lead (proposed: the "Agent and books" person; they consume most models and own the run loop). Backup: Stats and markets. Contract changes need a PR reviewed by the consuming chunk's owner. |
| **Depends on** | C1 Data (business feature-table metadata only), C2 Stats (Exposure, BacktestResult, model check), C3 Markets (Hedge, Decision, Check), C4 Agent/policy/log (LogEntry, run loop, chat), C5 Books (LedgerEntry, Reconciliation). Depended on by all of C1–C5, C7 Frontend, C8 Demo ops. |
| **Gate** | **3:30 PM**: models and example JSON merged, all routes return fixture-backed responses, contract tests green in CI. Real wiring by 9:00 PM. |

## Interfaces

All bodies are JSON. Money, price, and probability fields are `Decimal` serialized as strings (`"1240.00"`, `"0.62"`). Counts, ids, and booleans are native. `ci90` is `["880.00","1600.00"]`. Timestamps are ISO-8601 UTC. Error shape for every non-2xx: `{"error": {"code": "<snake_case>", "message": "<human>", "detail": {...}|null}}`.

| Method | Route | Request | Success | Errors |
|---|---|---|---|---|
| GET | `/businesses` | none | 200 `Business[]` (id, name, kind, data_label `real`/`estimated`, weekly_budget, budget_remaining) | none |
| POST | `/businesses/{id}/analyze` | `{}` or `{strike?: number}` | 200 `{exposures: Exposure[], dropped: Exposure[], model_check: ModelCheck, r2_holdout: str}` | 404 `business_not_found` |
| POST | `/businesses/{id}/desk/run` | `{week_of?: date}` | **202** `{run_id, status:"queued"}`, work runs in a background task | 404; 409 `run_in_progress` |
| GET | `/runs/{run_id}` (gap G2) | none | 200 `{run_id, status: queued/running/done/failed, agent: claude/fallback, started_at, finished_at, error?}` | 404 `run_not_found` |
| GET | `/businesses/{id}/hedges?week_of=` | query | 200 `Hedge[]`, **all statuses incl. declined**, each with embedded `Decision` | 404; 422 `bad_week_of` |
| POST | `/hedges/{id}/approve` | `{actor:"owner", note?}` | 200 `Hedge` (status `approved`, `ledger_entry_ids` set) | 403 `owner_only` (actor missing or not `owner`); 404; 409 `invalid_state` (not `pending_approval`) |
| POST | `/hedges/{id}/reject` | `{actor:"owner", reason?}` | 200 `Hedge` (status `rejected`) | same as approve |
| GET | `/businesses/{id}/backtest` | none | 200 `BacktestResult` | 404; 409 `backtest_not_ready` |
| GET | `/businesses/{id}/ledger` | none | 200 `{entries: LedgerEntry[], reconciliation_status: none/clean/mismatch}` | 404 |
| POST | `/businesses/{id}/reconcile` | `{}` | 200 `Reconciliation` (matches + flagged mismatches) | 404; 409 `nothing_to_reconcile` |
| POST | `/businesses/{id}/chat` | `{message: str}` (1–2000 chars) | 200 `{reply: str, tool_calls: [{name, input, output}]}` | 404; 422; never 5xx on Claude failure (fallback reply) |
| GET | `/businesses/{id}/decisions?limit=&before=` | query | 200 `LogEntry[]`, newest first | 404 |
| GET | `/health` (added) | none | 200 `{status, offline, anthropic: configured/fallback}` | none |

Hedge status enum: `proposed`, `pending_approval`, `approved`, `rejected`, `declined`, `expired_unapproved`, `settled`.

### Example JSON to check in (`fixtures/examples/`)

| File | Model | Owner chunk | Notes |
|---|---|---|---|
| `exposure.json` | Exposure | C2 | Copy of §5 snippet, money as strings; plus `exposure_dropped.json` with non-empty `reasons` |
| `hedge_proposed.json`, `hedge_declined.json`, `hedge_pending.json` | Hedge (with payoff table, fill, fee, premium) | C3 | Declined one uses §8 snippet; pending one has a within-budget alternative |
| `decision.json` | Decision / Check[] | C3 | Includes `partial` and `resized` check variants |
| `log_entry.json` (3 variants: proposal, approval, fallback) | LogEntry | C4 | Has `agent: claude` and `agent: fallback`, `actor`, `numbers`, `summary` |
| `backtest_result.json` | BacktestResult | C2 | All §10 metrics, `per_exposure{}` with one `ineffective` |
| `ledger_entry.json` | LedgerEntry | C5 | Metadata: hedge_id, ticker, decision_id, approved_by |
| `reconciliation.json` | Reconciliation | C5 | Contains the planted short-deposit mismatch with explanation |
| `model_check.json` | ModelCheck | C2 | planted 500, recovered, ci90, coverage_pct over 50 seeds |
| `business_taxi.json`, `business_restaurant.json` (also `fixtures/businesses/`) | Business | C6 | Zone id, avg check (labeled assumed), budget, estimated flag |

### Config / env (`config.py`, loaded from `.env`)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Unset means fallback mode, no crash |
| `ANTHROPIC_MODEL` | none, required when key set | Pinned ID, never hard-coded |
| `KALSHI_BASE_URL` | `https://external-api.kalshi.com/trade-api/v2` | |
| `DEMO_OFFLINE` | `0` | `1` blocks all outbound HTTP; cache only |
| `DATABASE_URL` | `sqlite:///./hedge_desk.db` | |
| `WEEKLY_BUDGET_DEFAULT` | `250` | Decimal |
| `AVG_CHECK_USD` | `35` | Labeled assumed |
| `CORS_ORIGINS` (added) | `http://localhost:3000,http://127.0.0.1:3000` | |
| Thresholds (in `config.py`, not env) | size 150, support 10, overpay 0.15, expense ratio 0.35, fill 0.5/1.0, slippage 0.05, rule-4 R² 0.5, cap 12 tool calls | Single source for rules, UI drawer, tests |

## Automated acceptance tests

Test dir `backend/tests/`; framework pytest + FastAPI `TestClient`; schema check via pydantic `model_validate` plus OpenAPI response models.

| ID | Test name | Future test file | Setup / fixture | Assertion |
|---|---|---|---|---|
| C6-A1 | every route returns schema-valid JSON | `tests/api/test_routes_schema.py` | App with seeded fixture DB, both businesses, `DEMO_OFFLINE=1` | Each route in table returns expected status; body validates against its declared response model; OpenAPI lists all routes |
| C6-A2 | example JSONs validate against models | `tests/contract/test_examples.py` | Glob `fixtures/examples/*.json` | Each file parses with its named model, `extra="forbid"`; round trip `model_dump_json` equals file semantically. Fails the build if a chunk renames a field |
| C6-A3 | no model is missing an example | `tests/contract/test_example_coverage.py` | Registry of shared models | Every model in `models.CONTRACT_MODELS` has at least one example file |
| C6-A4 | money fields are strings | `tests/contract/test_decimal_strings.py` | All example files and live route responses | Walk JSON; every field declared `Decimal` is a `str` matching `^-?\d+(\.\d+)?$`; no float appears in money/price/probability keys |
| C6-A5 | Decimal never passes through float | `tests/contract/test_decimal_precision.py` | Hedge with price `0.62`, fee `0.01` | Serialized `"0.62"` exact; sum of premium parts equals total with no float drift |
| C6-A6 | desk/run returns 202 and finishes in background | `tests/api/test_desk_run.py` | Fallback agent (no key), cached Kalshi fixtures | 202 within 1 s with `run_id`; poll `/runs/{id}` until `done`; hedges now present; second concurrent call returns 409 |
| C6-A7 | desk/run failure is contained | `tests/api/test_desk_run.py` | Monkeypatch agent to raise | Run status `failed` with error; API stays up; log entry written |
| C6-A8 | approve requires actor=owner | `tests/api/test_approval_auth.py` | One `pending_approval` hedge | No body, `actor:"desk"`, `actor:"agent"` all give 403 `owner_only`; hedge unchanged; with `owner` returns 200 and status `approved` (I4) |
| C6-A9 | reject requires actor=owner | `tests/api/test_approval_auth.py` | same | Same matrix; status `rejected` |
| C6-A10 | desk can never self-approve | `tests/api/test_approval_auth.py` | Run desk with over-budget hedge | After run, status is `pending_approval`, never `approved`; no ledger entries exist |
| C6-A11 | approve only valid from pending | `tests/api/test_approval_state.py` | Hedges in declined/approved/rejected | 409 `invalid_state`; no duplicate ledger entries on double approve |
| C6-A12 | approve books to ledger and logs | `tests/api/test_approval_books.py` | Pending hedge, temp ledgers dir | Premium and fee entries in the `.beancount` file; `GET /ledger` shows them; decisions list has an `approved` entry with `actor=owner` (I5) |
| C6-A13 | hedges endpoint includes declined | `tests/api/test_hedges.py` | Fixture week with 1 proposed, 1 declined, 1 pending | All three returned; declined has non-empty `decision.reasons` and `checks` (I3) |
| C6-A14 | week_of filter and format | `tests/api/test_hedges.py` | Two weeks of hedges | Monday date filters correctly; a Wednesday is normalized to its Monday or 422 per G3; omitted gives current week |
| C6-A15 | decisions newest first | `tests/api/test_decisions.py` | 5 log entries with shuffled insert order | `created_at` strictly descending; `limit` and `before` paginate without gaps |
| C6-A16 | decision log is append-only | `tests/api/test_decisions.py` | Any state change | No route updates or deletes a log row; row count is monotone (I5) |
| C6-A17 | works offline with no network | `tests/api/test_offline.py` | `DEMO_OFFLINE=1`, socket-blocking fixture (pytest-socket) | Every route returns success from caches/fixtures; zero outbound connection attempts |
| C6-A18 | missing Anthropic key falls back | `tests/api/test_no_key.py` | Env without `ANTHROPIC_API_KEY` | App boots; `/health` says `fallback`; desk/run completes; entries tagged `agent: fallback`; chat returns templated 200 |
| C6-A19 | Anthropic error falls back | `tests/api/test_no_key.py` | Mock SDK raising 500 and timeout | Same as A18; never a 5xx to client |
| C6-A20 | CORS for Next.js dev origin | `tests/api/test_cors.py` | `Origin: http://localhost:3000` | Preflight OPTIONS on POST routes returns allow-origin for that origin; a foreign origin is not allowed |
| C6-A21 | error shape is uniform | `tests/api/test_errors.py` | Unknown business, bad body, bad state | 404/409/422/403 all match `{error:{code,message,detail}}`, including FastAPI validation errors |
| C6-A22 | config defaults and overrides | `tests/test_config.py` | Empty env, then overridden env | Defaults match table; `WEEKLY_BUDGET_DEFAULT` parses to `Decimal`; thresholds exposed in one object |
| C6-A23 | db create and seed idempotent | `tests/test_db.py` | Temp SQLite | `make seed` twice leaves identical row counts; Decimal columns round-trip exactly |
| C6-A24 | business fixtures valid | `tests/contract/test_businesses.py` | `fixtures/businesses/*.json` | Both validate; restaurant has `estimated: true` and assumed-check label; taxi has `estimated: false` |
| C6-A25 | analyze returns model check | `tests/api/test_analyze.py` | Stub exposure module returning the example | Response has `model_check` and `r2_holdout` string; dropped exposures carry reasons |
| C6-A26 | chat returns tool calls | `tests/api/test_chat.py` | Fallback agent | `reply` non-empty; `tool_calls` is a list of `{name,input,output}`; every number in reply appears in tool outputs (I2) |
| C6-A27 | reconcile surfaces planted mismatch | `tests/api/test_reconcile.py` | Seeded ledger, `bank_statement.csv` | Response flags exactly 1 mismatch with explanation; `GET /ledger` status becomes `mismatch` |
| C6-A28 | backtest route serves cached result | `tests/api/test_backtest.py` | `backtest_result.json` seeded | 200, validates, `reduction_pct` and `priced_real_pct` strings; 409 when absent |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C6-H1 | API surface complete | Open `http://localhost:8000/docs` | All 10 spec routes plus `/runs/{id}` and `/health`; each has typed request and response models, not `object` |
| C6-H2 | Money is strings | In Swagger, Try it on `/hedges` and `/backtest` | Every dollar, price, probability is quoted, e.g. `"0.62"`; no bare decimals |
| C6-H3 | Declined hedge readable | Call `/hedges` on the fixture week | Declined hedge shows each failed check with `metric` numbers and a `summary` |
| C6-H4 | Owner gate | curl approve with no body, with `actor:"desk"`, with `actor:"owner"` | 403, 403, 200; error message tells the caller why |
| C6-H5 | Frontend can start now | Frontend dev points `lib/api.ts` at fixture mode | Page renders every region from examples without any backend edits |
| C6-H6 | Agent dev can start now | Agent dev imports `models.py` and builds a Hedge from the example | No missing field or circular import; tools return models directly |
| C6-H7 | Offline demo | Unplug Wi-Fi, `DEMO_OFFLINE=1 make demo`, click Run desk and approve | Full flow works, no stack traces in console, Header shows offline/estimated labels |
| C6-H8 | No key behavior | Unset `ANTHROPIC_API_KEY`, run desk | Hedges appear tagged fallback; log shows `agent: fallback`; UI does not error |
| C6-H9 | Log after a full flow | Run, approve, reject, reconcile, then GET `/decisions` | One entry per event (I5), newest first, actor visible on approvals |
| C6-H10 | Threshold flip | Change a threshold in `config.py`, restart, re-run | A decision flips with the changed metric visible in the check |
| C6-H11 | Example files are the truth | Diff each example against the spec snippets (§5, §8, §10) | Field names identical; any deviation is documented in a PR |
| C6-H12 | Secrets hygiene | `git grep -i "sk-ant"`; read `.gitignore` | No keys; `.env`, `*.db`, raw data ignored; `.env.example` present |

## Fixtures & sample data needed

| Item | Path | Owner | Needed by |
|---|---|---|---|
| Example JSON per object (list above) | `fixtures/examples/*.json` | Each model's owning chunk, merged via C6 | 3:30 PM |
| Business definitions (taxi, restaurant) | `fixtures/businesses/{taxi,restaurant}.json` | C6 with C1 filling zone id and avg check | 3:30 PM (placeholders), 6:00 PM (real) |
| Seed script to load fixtures into SQLite | `make seed` -> `db.py` | C6 | 3:30 PM |
| Seeded week of hedges (1 proposed, 1 pending, 1 declined, 1 partial) | `fixtures/examples/week_seed.json` | C3 + C6 | 3:30 PM |
| Seeded decision log (about 8 entries, mixed actors and agents) | `fixtures/examples/decisions_seed.json` | C4 | 3:30 PM |
| Cached Kalshi responses for the test suite | `fixtures/kalshi_cache/` | C3 | 9:00 PM |
| `bank_statement.csv` with planted short deposit | `fixtures/bank_statement.csv` | C5 | Midnight |
| `.env.example` | repo root | C6 | 3:30 PM |
| Contract-test CI job (pytest on push) | `.github/workflows/ci.yml` or `make test` | C8 + C6 | 3:30 PM |

## Definition of done

- All routes in the table implemented with response models; `/docs` is accurate.
- Every shared model has an example file, and contract tests C6-A2 to A5 run in CI and pass.
- Fixture mode: with no other chunk implemented, all routes return example data and the frontend renders.
- C6-A1 to A28 pass with no network and no Anthropic key.
- Owner-only approval and append-only log verified (A8 to A11, A16).
- Config and env documented in `.env.example`; no hard-coded model ID, URL, or threshold outside `config.py`.
- The models file is frozen at 3:30 PM; later changes require updating the example file and test in the same PR.
- Each of C1–C5 and C7 has confirmed (H5, H6) that they can code against it.

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| G1 | "Only `actor: owner` can approve" but there is no auth. How is it asserted? | Request body `actor` must equal `"owner"`; the desk/agent code path never sends it and the agent has no tool that calls approve. Optional header `X-Owner-Token` from env `OWNER_TOKEN` (default off). Demo-grade, documented as such. |
| G2 | desk/run returns `run_id` but no route to poll it | Add `GET /runs/{run_id}`; frontend polls `/hedges` plus this every 1 s. Runs held in a SQLite `run` table. |
| G3 | `week_of` format undefined | ISO date of the Monday (matches §10 Monday-start weeks); non-Monday dates snap to that week's Monday; omitted = current week; invalid = 422. |
| G4 | Auth/identity of the "desk" actor in log entries | `actor` enum: `desk`, `owner`, `system`; `agent` enum: `claude`, `fallback`. |
| G5 | Decimal precision not specified | Money 2 dp as strings; prices and probabilities up to 4 dp; counts are ints. Parsed from Kalshi with `Decimal`, never float; `ci90` and `se` are also strings. |
| G6 | `effect_usd`, `se` shown as floats in §5 example | Treat the §5 snippet as illustrative; the contract stores them as Decimal strings. Example file corrected. |
| G7 | Object shapes for Hedge, LogEntry, LedgerEntry, Reconciliation, ModelCheck, Business are not specified | C6 drafts them from §7, §9, §10, §11 text by 2:00 PM; owning chunk reviews before the gate. |
| G8 | Within-budget alternative on over-budget hedges: where in the model? | `Hedge.alternative: Hedge-lite or null` with reduced contracts and premium. |
| G9 | Settings drawer (thresholds, budget) has no route | Cut-list item 1 already; if kept, add `PUT /businesses/{id}/settings` (budget, thresholds). Default: not built, thresholds from `config.py`. |
| G10 | Nudge/expire (`expired_unapproved`) has no trigger | Evaluate lazily on `GET /hedges` (no scheduler); cut-list item 2. |
| G11 | Does `analyze` persist? | It writes nothing except an `analysis` cache row; `desk/run` calls the same function. Cached per (business, strike). |
| G12 | Chat "read-only log access" and persistence of chat history | Stateless per request in v1; each reply and its tool calls are written to the log as `chat` entries. |
| G13 | Concurrency on SQLite with background tasks | One `run` at a time per business (409 otherwise), WAL mode on, short transactions. |
| G14 | Error shape not in spec | Uniform `{error:{code,message,detail}}`; FastAPI's default 422 body is overridden to match. |
| G15 | Ledger of approved hedge when Beancount write fails | Approve is atomic: DB status and ledger write in one step; on failure return 500 `ledger_write_failed` and leave the hedge `pending_approval`. |

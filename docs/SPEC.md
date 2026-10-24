# Hedge Desk: Spec

Cal Hacks 13.0 · submission due **Sunday 9:00 AM**, judging 10:30 AM to 12:30 PM, live demo required.

Hedge Desk is the treasury seat a small business can't afford. It reads a business's daily revenue, finds the events that revenue quietly depends on (weather, games), measures each one in dollars, and proposes prediction-market hedges on Kalshi sized to cancel them out. Approved hedges are booked to a ledger and reconciled at settlement. It never places real orders.

---

## 1. Principles

These are the four lines we say to judges. Every design decision below should trace to one of them.

1. **Measured, not guessed.** Every number comes from real data and math. Claude finds markets and explains its reasoning, but it never produces a figure.
2. **Built for steady income.** It buys only enough protection to offset a real, measured risk, never more, so it does well when the week is steady, not when you trade.
3. **Your call, every time.** It does the homework and proposes; the owner decides, because the owner knows things no dataset does.
4. **Every decision has a receipt.** Each proposal, decline, approval, and booking is logged with both its numbers (from tools) and its reasoning (from Claude), so anyone can ask "why?" later and get a real answer.

**Invariants the code enforces:**

| # | Rule | Enforced in |
|---|---|---|
| I1 | Contracts bought ≤ measured exposure ÷ $1. Hedge ratio `h` is at most 1.0 | `markets/sizing.py` |
| I2 | Every dollar figure, price, or probability on screen comes from a tool result. Claude's text is never the source of a number | `agent/log.py` validates (regex on currency and percent tokens) |
| I3 | A hedge is proposed only if it passes every decline rule. Declined hedges are shown with reasons, never hidden | `markets/rules.py`, UI |
| I4 | The desk never approves its own hedge. Over-budget hedges wait in `pending_approval` | `agent/policy.py` |
| I5 | Every proposal, decline, approval, rejection, booking, and reconciliation is appended to the decision log | `agent/log.py` |
| I6 | Anything estimated or simulated carries a visible label in the UI | Data layer flags, `Header` |

---

## 2. Demo businesses

Both businesses sit around **Madison Square Garden (MSG)**, so they share one set of events: NYC weather and Knicks and Rangers home games.

| | Taxi fleet (public data) | Bar or restaurant near MSG (private data) |
|---|---|---|
| Story | A taxi fleet that works the MSG/Penn Station zone | A real bar or restaurant across from MSG |
| Revenue source | NYC TLC yellow-taxi trip records: `fare_amount` summed by day for pickups in the zone | Dewey / Advan Weekly Patterns+: `visits_by_day` × average check |
| Real or estimated | **Real dollars** | **Real visits, estimated dollars** (labeled) |
| Expected exposures | Rain (likely positive: riders leave the subway), temperature, event nights | Rain (likely negative), temperature, event nights, home win vs. loss |
| Cross-check | MTA subway ridership at the Penn Station complex (riders switch to cabs in rain) | MSG's own daily visits in Advan (ticker `NBA-A`) confirm event nights |

**Public naming:** use "a bar across from MSG" in the pitch and Devpost rather than the real business's name. We're showing estimates of a real business's traffic, and the license is academic.

**Expect some exposures to be small.** Whether the Knicks win may barely move taxi revenue. That's fine: it appears under "measured, not hedged" with its reason, which is principle 1 in action. Weather is likely the main real exposure.

---

## 3. Confirm before building (by 3:30 PM)

| # | Check | How | Owner | Default if it fails |
|---|---|---|---|---|
| C1 | Which NYC Kalshi markets are open this week | `GET /series?category=Climate and Weather`, `GET /markets?series_ticker=…&status=open` for NYC high temp (`KXHIGHNY` expected), NYC rain, Knicks and Rangers games | Markets | Temperature plus game markets only; rain becomes "measured, not hedged: no market" |
| C2 | Taxi zone ID for MSG/Penn Station | `taxi_zone_lookup.csv` from the TLC page (expected zone: "Penn Station/Madison Sq West") | Data | Neighboring Midtown zone |
| C3 | Dewey export: a busy bar or restaurant near MSG with daily visits from 2024 | See section 4.2 | Data | PassBy "Daily Store Visits" on Dewey |
| C4 | Average check for that place | Its menu: price of a typical order | Data | $35, labeled "assumed" |
| C5 | Date window every source covers | Dewey ends 2026-09-21; check the latest TLC month; check Kalshi settled-market history for the chosen series | Data + Markets | Train Oct 2024 to Sep 2025; holdout Oct 2025 to the last common month |
| C6 | Dewey license allows charts in a public demo | Yale's Dewey terms | Anyone | Show aggregates only; never commit raw rows |

---

## 4. Data layer

Everything downstream reads one **feature table** per business: one row per calendar day.

### 4.1 Taxi revenue (`data/taxi.py`)

- Source: TLC monthly Parquet files (yellow taxi), one per month in the window.
- Read with DuckDB directly from Parquet; filter `PULocationID == <zone>`; group by local date of `tpep_pickup_datetime`; `revenue = sum(fare_amount)`, `trips = count(*)`.
- Drop rows with `fare_amount <= 0` or a trip distance of 0.
- Cache the daily series to `fixtures/taxi_daily.parquet`. Raw monthly files stay out of git.

### 4.2 Restaurant revenue (`data/dewey.py`)

- Export from Dewey **with filters**, never the full 1.11 TB table:
  - `POSTAL_CODE` in (10001, 10119, plus MSG's own ZIP if different)
  - `NAICS_CODE` in (722511, 722513, 722410) or ticker `NBA-A`
  - week start ≥ 2024-01-01
- Explode each weekly row into 7 daily rows: `date = week_start + i`, `visits = visits_by_day[i]`.
- Pick the place: rank by total visits, keep the busy ones, and choose the one that clearly rises on MSG event nights.
- `revenue_est = visits × AVG_CHECK` (C4), with `estimated: true`.
- Save `fixtures/restaurant_daily.parquet` (aggregated daily series only) and `fixtures/msg_visits_daily.parquet`.

### 4.3 Events (shared)

| Data | Source | Notes |
|---|---|---|
| Daily weather at MSG | Open-Meteo archive API, no key. MSG ≈ 40.7505, −73.9934. `daily=precipitation_sum,temperature_2m_max`, Fahrenheit, inches, `America/New_York` | Also pull `hourly=precipitation` for the open-hours rain flag (basis rule) |
| Settlement weather | The station named in the matched market's `rules_primary` (Central Park expected for NYC) | NOAA GHCN-Daily for that station if time allows; otherwise Open-Meteo at the station's coordinates |
| Home games and results | ESPN scoreboard: `basketball/nba` (Knicks), `hockey/nhl` (Rangers), one call per date, cached | Fallback: a hand-entered CSV for the demo week |
| MSG event nights | Advan visits to MSG (spikes) | Captures concerts and other events, not just games |
| Holidays | Fixed list in `config.py` | Control only |

### 4.4 Feature table (`data/features.py`)

| Column | Type | Source |
|---|---|---|
| `date` | date | |
| `revenue` | float | taxi or restaurant series |
| `dow`, `doy` | int | derived |
| `is_holiday` | bool | config |
| `msg_event` | bool | MSG visits spike or game day (known in advance, so a **control**, not hedgeable) |
| `home_game` | bool | ESPN (control) |
| `home_win` | bool | ESPN, only on game days (**hedgeable**) |
| `rain` | bool | precipitation ≥ threshold from the matched contract's rules (default 0.01 in) |
| `rain_open_hours` | bool | hourly precipitation during business hours ≥ 0.05 in (for the basis rule) |
| `tmax` | float °F | weather |
| `estimated` | bool | true for the restaurant |

Split by date: the first year is `train`, the rest is `holdout`.

---

## 5. Exposure model (`stats/exposure.py`)

One OLS regression per business on `train`, with HC3 robust standard errors:

```
revenue_t = α + Σ δ_d·DOW_d + Σ_k [a_k sin(2πk·doy/365.25) + b_k cos(2πk·doy/365.25)]   (k = 1, 2)
          + γ·holiday + β_e·msg_event + β_w·home_win + β_r·rain + β_T·hot + ε
```

- `hot = tmax ≥ strike`, where the strike comes from the matched temperature contract. Refit per strike; it takes milliseconds.
- `msg_event` and `home_game` are controls: they're known in advance, so nothing to hedge. `home_win`, `rain`, and `hot` are the hedgeable exposures.
- Levels, not logs: hedges need dollars.

**Hedgeable only if all three hold** (otherwise shown as "measured, not hedged" with the reason):

| Rule | Threshold |
|---|---|
| Size | \|effect\| ≥ $150/day |
| Significance | 90% CI excludes zero |
| Support | ≥ 10 event days in `train` |

**Exposure object:**

```json
{
  "id": "exp_rain", "business_id": "taxi", "event": "rain",
  "effect_usd": 1240.0, "ci90": [880.0, 1600.0], "se": 219.0, "p_value": 0.001,
  "n_events_train": 112, "direction": "positive", "hedge_side": "no",
  "settlement_var": "rain", "hedgeable": true, "reasons": []
}
```

`hedge_side` is the contract side that pays when revenue is low. A positive rain exposure (taxis earn more when it rains) means buying **NO** on rain; a negative one (the bar) means buying **YES**. Nothing else decides direction.

### 5.1 Model check: planted effect on real data

The answer key for "how do you know the numbers are right?":

1. Copy the real `train` series.
2. Add a known `+$500` on a random 15% of days, flagged `planted`.
3. Refit with `planted` as an extra regressor.
4. Report planted vs. recovered with the 90% CI. Pass = the CI contains 500.
5. Repeat with 50 random seeds; report the share of runs whose CI contains the truth (target ≈ 90%).

Shown in the UI as **Model check**. Also report `r2_holdout` as the out-of-sample number.

---

## 6. Market layer (`markets/kalshi.py`, `markets/match.py`)

Public Kalshi v2 endpoints, no API key. Base URL `https://external-api.kalshi.com/trade-api/v2`. One `httpx.AsyncClient`, 10 s timeout, 3 retries. Every response is cached to `fixtures/kalshi_cache/` so `DEMO_OFFLINE=1` can replay it.

| Method | Endpoint | Used for |
|---|---|---|
| `list_series(category)` | `GET /series?category=…` | Find NYC weather and NBA/NHL game series; read `fee_type`, `fee_multiplier`, settlement sources |
| `list_markets(series, window)` | `GET /markets?series_ticker=&status=open&min_close_ts=&max_close_ts=` | This week's candidates |
| `get_market(ticker)` | `GET /markets/{ticker}` | `rules_primary`, `floor_strike`, asks |
| `get_orderbook(ticker)` | `GET /markets/{ticker}/orderbook` | Price and depth for sizing |
| `list_settled(series, window)` | `GET /markets?series_ticker=&status=settled&…` | Past contracts and results for the backtest |
| `candles(ticker)` | `GET /series/{s}/markets/{t}/candlesticks?period_interval=1440`, or the `/historical/…` equivalent past the archive cutoff | Past prices for the backtest |

- Prices arrive as fixed-point dollar strings. Parse with `Decimal`, never float.
- The order book returns **bids only**. Best YES ask = 1 − best NO bid; best NO ask = 1 − best YES bid.

**Matching:** a deterministic filter builds candidates (series by `settlement_var`, NYC or team, closes within 8 days, `status=open`). Claude then picks one ticker **from that list** with a one-sentence reason via the `match_market` tool; anything off-list is rejected. An empty list becomes the `no_market` decline, not an error.

---

## 7. Sizing (`markets/sizing.py`)

```
N* = ceil(h · |β| / $1),   0 < h ≤ 1
```

- Walk the order book from the best ask until `N*` is filled or the next level is more than 5¢ above the best ask; report anything unfilled.
- Kalshi taker fee per order: `0.07 × C × P × (1 − P)`, rounded up to the cent. Read `fee_type` and `fee_multiplier` from the series; flag `fee_unverified` if they differ from the standard.
- `premium = cost + fee`
- `expected_cost = fee + (avg_price − fair) × N`, where `fair` = the event's historical frequency on `train` (`p̂` for YES, `1 − p̂` for NO).
- **Payoff table, always both outcomes, always including the premium:**

| Outcome | Revenue vs. base | Contract payout | Premium | Net vs. base |
|---|---|---|---|---|
| Event | β | N or 0 | −premium | ≈ flat |
| No event | 0 | 0 or N | −premium | ≈ flat |

The headline under every hedge: **"Unhedged swing $X · hedged swing $Y · cost $Z."**

---

## 8. Decline rules (`markets/rules.py`)

Every check runs and is logged, even after one fails. The budget check runs last because it pauses rather than declines.

| # | Code | Test | Threshold | Result |
|---|---|---|---|---|
| 1 | `no_market` | Candidate list empty | | declined |
| 2 | `illiquid` | Fillable within 5¢ ÷ `N*` | < 0.5 declined; 0.5 to 1.0 partial | declined / partial |
| 3 | `overpriced` | `avg_price − fair` | > 0.15 | declined |
| 4 | `basis_too_loose` | R² between the business's exposure flag and the contract's settlement flag on `train` | < 0.5 declined; otherwise `h = min(1, \|β_S\| / \|β\|)` | declined / resized |
| 5 | `too_expensive` | `expected_cost ÷ \|β\|` | > 0.35 | declined |
| 6 | `over_budget` | premium > remaining weekly budget | | `pending_approval` |

**Rule 4 is "sources that disagree."** The bar loses money when it rains during open hours near MSG (`rain_open_hours`). The contract pays on any measurable rain at the settlement station over the calendar day (`rain`). Morning drizzle pays the contract but never touches the bar. The desk measures how often the two agree and says so in numbers: "Last year this contract paid on 68 days; the bar lost money on 41 of them."

Thresholds live in `config.py` and in the UI's settings drawer, so a judge can move one and watch a decision flip.

**Decision object** (embedded in the hedge, written to the log):

```json
{
  "status": "declined",
  "checks": [
    {"code": "overpriced", "passed": false, "metric": {"avg_price": 0.62, "fair": 0.27, "overpay": 0.35}},
    {"code": "too_expensive", "passed": false, "metric": {"expected_cost": 328.2, "swing": 900, "ratio": 0.36}}
  ],
  "reasons": ["overpriced", "too_expensive"],
  "summary": "Declined: the rain contract costs 62¢ against a 27% historical rain rate, and the hedge would cost 36% of the swing it removes."
}
```

`summary` is the only field Claude writes, and every number in it must appear in `checks` (I2).

---

## 9. Books and reconciliation (`books/ledger.py`, `books/reconcile.py`)

This is what makes the desk a member of the finance team rather than an outside advisor.

**Ledger:** Beancount, one plain-text file per business (`ledgers/{business}.beancount`).

| Event | Entry |
|---|---|
| Owner approves | Debit `Expenses:Hedging:Premiums` and `Expenses:Hedging:Fees`; credit `Assets:Kalshi:Cash` |
| Contract settles in our favor | Debit `Assets:Kalshi:Cash`; credit `Income:Hedging:Payouts` |
| Contract expires worthless | No cash entry; log `expired` |
| Withdrawal to bank | Debit `Assets:Bank:Checking`; credit `Assets:Kalshi:Cash` |

Each entry carries metadata: `hedge_id`, `ticker`, `decision_id`, `approved_by`.

**Reconciliation:** after settlement, compare three sources: the desk's expected payout (from the market's `result`), the Kalshi cash ledger, and a bank-statement CSV. Settlements and the statement are **simulated** from real market results (we don't trade), with **one planted mismatch** (for example, a deposit short by the fee). The reconciler flags it, explains the difference, and asks the owner. That's a second answer key: planted error, caught.

---

## 10. Backtest (`stats/backtest.py`)

Walk forward through `holdout` one Monday-start week at a time, with exposures frozen from `train`, and re-estimate monthly (this shows time passing: an exposure that keeps missing gets dropped).

```
for week in holdout weeks:
    unhedged = sum(revenue)
    for each hedgeable exposure, each day it could occur:
        q = price for that date's contract          # real Kalshi candles if available, else p̂_trailing + 0.02
        N = ceil(h × |β|)
        if rules 3–5 decline at q: continue           # rules 2 and 6 skipped (no historical depth; budget is policy)
        pnl += (N if settlement fired in our favor else 0) − premium
    hedged = unhedged + pnl
```

**Headline:** "Over the holdout, weekly income swings fell X% for $Y in premiums."

| Metric | Meaning |
|---|---|
| `std_unhedged`, `std_hedged`, `reduction_pct` | The headline |
| `worst_week_unhedged`, `worst_week_hedged` | The bad week, before and after (the demo opener) |
| `total_premium`, `n_hedges`, `n_declined` | Cost and activity |
| `priced_real_pct` | Share of contracts priced from real Kalshi history |
| `per_exposure{}` | Each exposure alone; under 10% reduction → `ineffective` |

---

## 11. Agent and policy (`agent/`)

Standard Claude tool-use loop, capped at 12 tool calls per turn. Two entry points:

- `run_weekly_desk(business_id)`: `get_exposures` → per exposure `search_markets` → `match_market` → `size_hedge` → `evaluate_hedge` → `log_decision` → `summarize_week`.
- `chat(business_id, message)`: same tools plus read-only log access; answers "why?" from `checks[].metric`.

| Tool | Returns | Backed by |
|---|---|---|
| `get_exposures` | Exposures, dropped ones with reasons, model check | `stats/exposure.py` |
| `search_markets` | Candidate markets with asks and rules | `markets/match.py` |
| `match_market` | The chosen market, or an error if off-list | validation only |
| `size_hedge` | Hedge with fill, fee, premium, payoff | `markets/sizing.py` |
| `evaluate_hedge` | Decision with all checks | `markets/rules.py` |
| `check_budget` | Budget, spent, remaining, pending | `agent/policy.py` |
| `log_decision` | Log entry ID (rejects numbers not in `checks`) | `agent/log.py` |
| `book_hedge` | Ledger entry IDs | `books/ledger.py` |
| `reconcile` | Matches, mismatches, explanations | `books/reconcile.py` |
| `run_backtest` | BacktestResult | `stats/backtest.py` |

**System prompt rules:**
1. You are the risk desk for one small business. Find, size, and evaluate hedges, and explain them to an owner who isn't a trader.
2. Every number you state must come from a tool result in this conversation. If you don't have it, call the tool. Never estimate.
3. Never recommend more contracts than `size_hedge` returns. If asked to buy more, explain that it would be speculation.
4. When a hedge is declined, say which checks failed and the numbers behind them. A decline is a good outcome when the price is wrong.
5. Premiums are a cost. Never describe a hedge as making money; its value is a smaller swing, and you say what it costs.
6. For `pending_approval`, state the premium, the budget, and what the owner gets, then stop. Don't argue for approval.
7. Say what's real and what's estimated when asked.
8. One or two sentences per answer unless asked for detail.

**Policy:** weekly budget per business (default $250). Over-budget hedges keep full size and show an "approve" button plus a within-budget alternative. Only `actor: owner` can approve or reject. If a hedge is still pending 3 hours before the market closes, the desk sends one nudge, then lets it expire and logs `expired_unapproved`.

**Fallback:** if Claude is slow or erroring, `run_weekly_desk` uses deterministic matching (the most liquid candidate) and a templated summary, and the log marks those entries `agent: fallback`.

---

## 12. Stack and repo

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn |
| Data and stats | DuckDB, pandas, numpy, statsmodels |
| HTTP | httpx (async) |
| Agent | `anthropic` SDK, tool use; pin the model ID in `.env` |
| Books | Beancount (plain text) |
| Storage | SQLite via sqlmodel |
| Frontend | Next.js, Tailwind, Recharts, SWR |

```
hedge-desk/
  Makefile                 make dev / make demo / make seed
  backend/app/
    main.py config.py models.py db.py
    data/      taxi.py dewey.py weather.py sports.py features.py
    stats/     exposure.py modelcheck.py backtest.py
    markets/   kalshi.py match.py sizing.py rules.py
    books/     ledger.py reconcile.py
    agent/     tools.py desk.py prompts.py policy.py log.py
  notebooks/   01_taxi.ipynb  02_restaurant.ipynb  03_exposure.ipynb
  fixtures/    taxi_daily.parquet  restaurant_daily.parquet  msg_visits_daily.parquet
               businesses/*.json  kalshi_cache/  bank_statement.csv
  ledgers/     *.beancount
  frontend/    app/page.tsx  components/  lib/api.ts
```

`.gitignore`: raw TLC Parquet, raw Dewey exports, `.env`.

**Environment:** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `KALSHI_BASE_URL`, `DEMO_OFFLINE`, `DATABASE_URL`, `WEEKLY_BUDGET_DEFAULT=250`, `AVG_CHECK_USD`.

### API

| Method | Route | Returns |
|---|---|---|
| GET | `/businesses` | Both businesses |
| POST | `/businesses/{id}/analyze` | Exposures, dropped, model check, `r2_holdout` |
| POST | `/businesses/{id}/desk/run` | `202 {run_id}` (background task) |
| GET | `/businesses/{id}/hedges?week_of=` | Hedges, including declined |
| POST | `/hedges/{id}/approve`, `/reject` | Hedge (owner only; books on approve) |
| GET | `/businesses/{id}/backtest` | BacktestResult |
| GET | `/businesses/{id}/ledger` | Entries plus reconciliation status |
| POST | `/businesses/{id}/reconcile` | Matches and flagged mismatches |
| POST | `/businesses/{id}/chat` | `{reply, tool_calls[]}` |
| GET | `/businesses/{id}/decisions` | Log, newest first |

Decimals serialize as strings; the frontend formats and never calculates.

---

## 13. Frontend

One page:

| Region | Shows |
|---|---|
| Header | Business switcher (fleet / restaurant), "real" or "estimated" label, budget remaining, **Run desk** |
| Left | Exposures with effect and 90% CI bars; collapsed "measured, not hedged" list with reasons; **Model check** toggle |
| Center | Hedge cards (declined ones included): market, side, contracts, premium, payoff chart (unhedged vs. hedged bars in both outcomes), decision chip, Claude's summary, "Open on Kalshi" |
| Right | Decision log, newest first, expandable to checks |
| Bottom | Backtest: weekly income unhedged vs. hedged, plus the metrics strip; ledger and reconciliation tab |
| Drawers | Chat ("why?"); settings (thresholds and budget) |

---

## 14. Demo (2 minutes)

1. **0:00–0:15, the bad week.** "This is a real taxi zone outside Madison Square Garden. Here's its worst week last season, and the same week with Hedge Desk." (`worst_week` before and after.)
2. **0:15–0:45, find the risk.** Run the desk. Exposures appear in dollars with confidence bars; one or two land in "measured, not hedged" with reasons.
3. **0:45–1:15, protect it.** This week's real Kalshi market, sized; the payoff chart shows flat income in both outcomes, and the cost.
4. **1:15–1:40, the moment.** A hedge is declined and the desk defends it with numbers; or reconciliation catches the planted short deposit. A judge can move a threshold and watch a decision flip.
5. **1:40–2:00, proof.** Model check (planted $500 recovered) and the backtest headline. Switch to the restaurant: same desk, different business, opposite rain direction.

**Language:** say "insurance for a single Saturday," not "hedge ratio" or "basis risk," in the first minute.

**Real vs. estimated (for the Devpost):** taxi fares, weather, games, and Kalshi prices are real; restaurant visits are real and its dollars are estimated (visits × average check); settlements and the bank statement are simulated from real market results; no real trades are placed.

---

## 15. Fallbacks

| Failure | Fallback |
|---|---|
| Kalshi unreachable | `DEMO_OFFLINE=1` serves cached markets and books |
| ESPN unreachable | `fixtures/schedule_{team}.csv` for the demo week |
| Open-Meteo unreachable | Weather is cached at import; never fetched live during the demo |
| Claude slow or erroring | Deterministic matching and templated summaries, marked `agent: fallback` |
| No live market for an exposure | `no_market` decline; it still shows as measured |
| Venue Wi-Fi | At 2 AM, run the desk online once to warm the cache, then judge with `DEMO_OFFLINE=1` |

---

## 16. Team and checkpoints

| Role | Owns |
|---|---|
| Data | TLC pipeline, Dewey export and daily expansion, weather, sports, feature table |
| Stats and markets | Exposure model, model check, Kalshi client, sizing, decline rules, backtest |
| Agent and books | Tool loop, prompts, policy, decision log, ledger, reconciliation |
| Frontend and story | Dashboard, pitch, Devpost, demo video |

| Time | Gate |
|---|---|
| **3:30 PM** | C1–C6 answered; interfaces in sections 5, 7, and 8 locked; example JSON for each object checked in so frontend and agent can start against fixtures |
| **6:00 PM** | Both daily revenue series and feature tables built; exposure fit and model check working in a notebook |
| **9:00 PM** | Backend end to end (exposures → market → size → decide → book) on live Kalshi data; dashboard on the real API; **Devpost draft submitted** |
| **Midnight** | Real-priced backtest; reconciliation with the planted mismatch; chat answers "why?"; decline moment verified on live data |
| **2:00 AM** | Cache warmed; demo video recorded on `DEMO_OFFLINE=1`; sleep |
| **7:00 AM** | Three pitch rehearsals; bug fixes only |
| **8:30 AM** | Final submission |

**Cut list, in order, if 9 PM slips:**
1. Settings drawer (thresholds stay in config)
2. Approval timing (nudge and expire)
3. Real-priced backtest tier (frequency pricing only, labeled)
4. Reconciliation (keep ledger booking)
5. Restaurant business (the taxi fleet alone carries the demo)

**Never cut:** the decline moment, the payoff table with premium, the model check, the decision log, ledger booking.

---

## 17. Tracks

| Track | What to emphasize |
|---|---|
| **Hyphenate** (primary) | Seat line: "The treasury analyst who finds and hedges a business's event risk, and the bookkeeper who records and reconciles it." Limits, approvals, the decision log, the books, sources that disagree (rule 4), planted errors with an answer key (model check and reconciliation) |
| **Microsoft: Built for the Real World** | Customer (the fleet, the bar), measurable usefulness (backtest), path to production (owners connect their point-of-sale or bank), responsible design (never over-hedges) |
| **Anthropic: Claude for Public Benefit** | Named community: small-business owners whose income rides on weather and game days. Claude chooses and explains but never produces a number; every figure is checked against tool results |
| General | Overall; Most Technically Complex |

Check the Devpost form for a limit on sponsor tracks per project.

---

## 18. Sources

- [NYC TLC trip record data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)
- [MTA Subway Hourly Ridership 2020–2024](https://data.ny.gov/Transportation/MTA-Subway-Hourly-Ridership-2020-2024/wujg-7c2s) and [beginning 2025](https://catalog.data.gov/dataset/mta-subway-hourly-ridership-beginning-2025)
- Dewey: Advan Weekly Patterns Plus (product page and documentation, viewed Oct 24, 2026)
- [Kalshi API quick start: market data](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [Kalshi daily temperature markets by city (third-party list)](https://apify.com/bigdavidson/kalshi-weather-markets)
- [Fortune on Blanket (Aug 7, 2026)](https://fortune.com/2026/08/07/exclusive-kalshi-blanket-small-business-hedge-hypergamblification/)
- Hyphenate track brief (CalHacks_Hyphenate_Track.pdf)
- Kalshi fee formula and historical endpoints: as cited in the team's earlier technical spec (confirm on first call)


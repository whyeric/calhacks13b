# C3 · Markets

> Cross-chunk conflicts are resolved in [CONTRACTS.md](../../../docs/CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | Kalshi public-API client + disk cache, candidate matching, hedge sizing (book walk, fee, premium, payoff), six decline rules. Also owns confirm-check **C1** (open NYC Kalshi markets this week). Never places orders. |
| **Files** | `backend/app/markets/kalshi.py`, `match.py`, `sizing.py`, `rules.py`; cache dir `fixtures/kalshi_cache/` |
| **Spec sections** | §3 C1, §6 Market layer, §7 Sizing, §8 Decline rules; invariants **I1** (contracts ≤ exposure ÷ $1, h ≤ 1) and **I3** (propose only if every rule passes; declines shown with reasons) |
| **Owner role** | Stats and markets |
| **Depends on** | **C2 Stats** (Exposure objects, `p̂` train frequency, basis R² and `β_S`). **C6 API/models/db** (shared pydantic models for Hedge/Decision/Candidate; Decimal-as-string serialization). **C1 Data** (none directly). **C8** supplies `DEMO_OFFLINE` and cache warm-up in the Makefile. |
| **Consumed by** | **C4 Agent** (`search_markets`, `match_market`, `size_hedge`, `evaluate_hedge` tools; budget input), **C5 Books** (Hedge fills/fee/premium), **C7 Frontend** (Hedge/Decision JSON), **C2 backtest** (`list_settled`, `candles`, `taker_fee`, rules 3–5 reused) |
| **Gate** | **3:30 PM**: C1 answered (list of open NYC tickers checked into `fixtures/kalshi_cache/` + noted below) and the Interfaces section frozen with example JSON checked in. **9 PM**: exposure → market → size → decide works on live Kalshi data. **Midnight**: decline moment verified on live data. **2 AM**: cache warm; `DEMO_OFFLINE=1` replay passes. |

## Interfaces

All money, prices, probabilities are `decimal.Decimal` in Python and **strings** in JSON. No `float` anywhere in this package. `Level = {price: Decimal, count: int}`. Sides are lowercase `"yes"` / `"no"`.

### kalshi.py
| Signature | Behavior |
|---|---|
| `KalshiClient(base_url=env KALSHI_BASE_URL, offline=env DEMO_OFFLINE=="1", cache_dir="fixtures/kalshi_cache", transport=None)` | One shared `httpx.AsyncClient`, 10 s timeout, 3 retries (timeouts, 429, 5xx; not other 4xx), exponential backoff. `transport` is injectable for tests. |
| `async list_series(category: str) -> list[dict]` | `GET /series?category=`. Each dict keeps `ticker`, `title`, `fee_type`, `fee_multiplier`, settlement sources. |
| `async list_markets(series_ticker, status="open", min_close_ts=None, max_close_ts=None) -> list[dict]` | Follows `cursor` pagination until exhausted. |
| `async get_market(ticker) -> dict` | Includes `rules_primary`, `floor_strike`, `close_time`, `result` when settled. |
| `async get_orderbook(ticker) -> Orderbook` | `Orderbook{ticker, yes_bids: list[Level], no_bids: list[Level], fetched_at}`; bids only, sorted best (highest) first. |
| `async list_settled(series_ticker, min_close_ts, max_close_ts) -> list[dict]` | `status=settled`. |
| `async candles(series_ticker, ticker, start_ts, end_ts, period_interval=1440) -> list[dict]` | Falls back to the `/historical/...` path past the archive cutoff. |
| `parse_price(s: str) -> Decimal` | Fixed-point dollar string to Decimal; raises on float input. |
| `best_ask(book, side) -> Decimal \| None` | `side="yes"`: `1 − max(no_bids.price)`; `side="no"`: `1 − max(yes_bids.price)`. `None` if opposite bid list empty. |
| `ask_levels(book, side) -> list[Level]` | Ascending ask ladder derived by inverting the opposite bids (`ask = 1 − bid`, same count). |
| `class CacheMiss(Exception)` | Raised in offline mode when a request has no cache file. Never falls through to the network. |

Cache: key = `sha1(method + path + sorted query)`; file `fixtures/kalshi_cache/<key>.json` holding `{request, response, fetched_at}` plus a human-readable `index.json` mapping key to path+query. Online mode writes every successful response; offline mode only reads.

### match.py
| Signature | Behavior |
|---|---|
| `async build_candidates(client, exposure: Exposure, now: datetime, window_days=8) -> list[Candidate]` | Deterministic filter: series chosen by `exposure.settlement_var` (rain / hot-temp / home_win) and NYC or team; `status=open`; closes within `window_days`; one `get_orderbook` per survivor to fill asks. Sorted by `yes_ask` fill depth desc, then ticker (stable). Empty list is a valid return. |
| `validate_pick(candidates, ticker, reason) -> Candidate` | Returns the candidate if `ticker` is in the list; else raises `OffListError(ticker, allowed=[...])`. Used by `match_market`. |
| `deterministic_pick(candidates) -> Candidate \| None` | Fallback: most liquid (largest depth within 5¢ of best ask on the hedge side). |

**Candidate shape**
```json
{
  "ticker": "KXHIGHNY-26OCT28-T65", "series_ticker": "KXHIGHNY",
  "title": "Highest temperature in NYC on Oct 28?", "close_time": "2026-10-29T04:59:00Z",
  "status": "open", "rules_primary": "...Central Park...", "floor_strike": "65",
  "settlement_var": "hot", "fee_type": "quadratic", "fee_multiplier": "1",
  "yes_ask": "0.42", "no_ask": "0.62", "yes_bid": "0.38", "no_bid": "0.58",
  "depth_within_5c": {"yes": 70, "no": 220}
}
```

### sizing.py
| Signature | Behavior |
|---|---|
| `target_contracts(effect_usd: Decimal, h: Decimal) -> int` | `N* = min(ceil(h·|β|), floor(|β|))`; computed in exact Decimal/Fraction (no float); raises if `h<=0` or `h>1`. |
| `walk_book(levels: list[Level], n_target: int, max_slip=Decimal("0.05")) -> Fill` | `Fill{fills: [Level], n_filled, n_unfilled, avg_price, cost, best_ask, stopped_reason: "filled"\|"slippage"\|"book_exhausted"}`. Takes levels from best ask; includes a level only if `price − best_ask <= 0.05` (exactly 5¢ allowed, >5¢ stops). |
| `taker_fee(contracts: int, price: Decimal, multiplier=Decimal("1")) -> Decimal` | `ceil_to_cent(0.07·multiplier·C·P·(1−P))` using `ROUND_CEILING` at 2 dp. Exact-cent results are not bumped. |
| `order_fee(fills: list[Level]) -> Decimal` | `ceil_to_cent(Σ per-level unrounded fee)` (round once, on the order). |
| `size_hedge(exposure, candidate, book, h, fair, series_fee) -> Hedge` | Picks `side = exposure.hedge_side`, walks that side's ask ladder, computes fee, premium (`cost + fee`), `expected_cost = fee + (avg_price − fair)·n_filled`, `fee_unverified` if `fee_type != "quadratic"` or `fee_multiplier != 1`, payoff table, headline. Does **not** decide pass/fail. |
| `payoff_table(exposure, side, n, premium) -> list[PayoffRow]` | Two rows (event / no event), both always include `−premium`. |

### rules.py
| Signature | Behavior |
|---|---|
| `Thresholds` (dataclass, defaults from `config.py`) | `fill_decline=0.5`, `max_slip=0.05`, `overpay_max=0.15`, `basis_r2_min=0.5`, `cost_ratio_max=0.35`, `weekly_budget` (budget remains policy input). |
| `BasisStat{r2: Decimal, beta_s: Decimal}` | Supplied by C2 (R² of exposure flag vs. settlement flag on `train`; revenue effect of the settlement flag). |
| `resolve_h(basis: BasisStat \| None, effect_usd, th) -> Decimal \| None` | `min(1, |β_S|/|β|)`; `None` if `r2 < basis_r2_min`. |
| `evaluate(exposure, candidates, hedge: Hedge \| None, basis, remaining_budget, th) -> Decision` | Runs **all six checks in table order 1→6, always**, returns a Decision. |

**Decision object** (exactly spec §8; `summary` is filled later by C4, `null`/templated until then)
```json
{
  "status": "declined",
  "checks": [
    {"code": "no_market",       "passed": true,  "metric": {"n_candidates": 3}},
    {"code": "illiquid",        "passed": true,  "metric": {"n_target": 100, "n_filled": 70, "fill_ratio": "0.70", "partial": true}},
    {"code": "overpriced",      "passed": false, "metric": {"avg_price": "0.62", "fair": "0.27", "overpay": "0.35"}},
    {"code": "basis_too_loose", "passed": true,  "metric": {"r2": "0.81", "beta_s": "900", "beta": "900", "h": "1"}},
    {"code": "too_expensive",   "passed": false, "metric": {"expected_cost": "328.20", "swing": "900", "ratio": "0.36"}},
    {"code": "over_budget",     "passed": true,  "metric": {"premium": "41.20", "remaining": "250.00"}}
  ],
  "reasons": ["overpriced", "too_expensive"],
  "summary": "Declined: ..."
}
```
`status` ∈ `proposed | declined | pending_approval`. `partial` fills and `resized` h are flags inside `metric`, and mirrored on the Hedge. Precedence: any of checks 1–5 failed → `declined`; else check 6 failed → `pending_approval`; else `proposed`. `reasons` lists failed codes in table order.

**Hedge object** (C3 produces everything except `id`, `week_of`, and `decision.summary`)
```json
{
  "id": "hdg_...", "business_id": "taxi", "exposure_id": "exp_rain", "week_of": "2026-10-26",
  "ticker": "KXRAINNYC-26OCT28", "side": "no", "match_reason": "one sentence from Claude",
  "h": "1", "n_target": 1240, "n_filled": 1240, "n_unfilled": 0, "partial": false,
  "fills": [{"price": "0.62", "count": 800}, {"price": "0.64", "count": 440}],
  "avg_price": "0.6271", "cost": "777.60", "fee": "13.40", "premium": "791.00",
  "fair": "0.73", "expected_cost": "13.40", "fee_unverified": false,
  "payoff": [
    {"outcome": "event",    "revenue_vs_base": "1240.00", "contract_payout": "0.00",    "premium": "-791.00", "net_vs_base": "449.00"},
    {"outcome": "no_event", "revenue_vs_base": "0.00",    "contract_payout": "1240.00", "premium": "-791.00", "net_vs_base": "449.00"}
  ],
  "headline": {"unhedged_swing": "1240.00", "hedged_swing": "0.00", "cost": "791.00"},
  "decision": { "...Decision object above..." },
  "agent": "claude | fallback"
}
```
(Numbers illustrative only.) Declined hedges are still emitted with the sizing that was attempted; if no candidate, `ticker`/fills/payoff are `null` and only `decision` is populated.

## Automated acceptance tests

Test dir: `backend/tests/markets/`. Hand-built fixtures under `fixtures/markets_test/` (books as JSON) unless noted. `pytest` + `pytest-asyncio`; network blocked by default via a transport that raises.

| ID | Test name | Future test file | Setup / fixture | Assertion |
|---|---|---|---|---|
| C3-A1 | fee_rounds_up | `test_sizing_fee.py` | none | `taker_fee(100, 0.40)`=1.68 (exact, not bumped). `taker_fee(10, 0.62)`: 0.07·10·0.62·0.38=0.16492 → **0.17**. `taker_fee(1, 0.50)`: 0.0175 → **0.02**. `taker_fee(3, 0.10)`: 0.0189 → **0.02**. Return type is `Decimal`, 2 dp. |
| C3-A2 | fee_multiplier_and_flag | `test_sizing_fee.py` | series `fee_multiplier="2"`; separate series `fee_type="flat"` | Multiplier 2 doubles the pre-round fee; either non-standard series sets `fee_unverified=true` on the Hedge; standard series gives `false`. |
| C3-A3 | prices_are_decimal | `test_kalshi_parse.py` | recorded market + book JSON | `parse_price("0.4200")==Decimal("0.42")`; no `float` instance in Orderbook, Candidate, Hedge (recursive type walk); `parse_price(0.42)` raises. |
| C3-A4 | ask_derived_from_opposite_bid | `test_kalshi_book.py` | book `yes_bids=[0.38×50,0.35×20]`, `no_bids=[0.58×40,0.55×30,0.50×100]` | `best_ask(book,"yes")==0.42`; `best_ask(book,"no")==0.62`; `ask_levels(book,"yes")==[0.42×40,0.45×30,0.50×100]`; empty `no_bids` → `best_ask(book,"yes") is None`. |
| C3-A5 | hedge_side_to_ask | `test_sizing_side.py` | Exposure `hedge_side="no"` (taxi rain) and `"yes"` (bar rain), same book as A4 | "no" exposure walks the NO ladder (first fill price 0.62); "yes" exposure walks YES ladder (first fill 0.42); Hedge `side` matches `exposure.hedge_side`; nothing else influences direction (flip `direction` text only → no change). |
| C3-A6 | book_walk_three_levels | `test_sizing_walk.py` | YES ladder 0.42×40, 0.45×30, 0.50×100; `N*=100` | Fills 40@0.42 + 30@0.45; 0.50 excluded (0.08 > 0.05). `n_filled=70`, `n_unfilled=30`, `cost=30.30`, `avg_price≈0.432857`, `stopped_reason="slippage"`, fill_ratio 0.70. `fee=1.21` (Σ0.68208+0.51975=1.20183 → ceil). `premium=31.51`. |
| C3-A7 | book_walk_slippage_boundary | `test_sizing_walk.py` | ladder 0.42×40, 0.47×30, 0.48×30; `N*=100` | 0.47 (exactly +5¢) is **included**; 0.48 (+6¢) is **excluded**; `n_filled=70`. |
| C3-A8 | book_walk_full_and_exhausted | `test_sizing_walk.py` | `N*=30` on A6 ladder; `N*=500` on 2-level book of 40 total | First: stops at 30 filled at 0.42, `stopped_reason="filled"`. Second: `n_filled=40`, `stopped_reason="book_exhausted"`, no exception. |
| C3-A9 | n_star_ceil | `test_sizing_n.py` | none | `target_contracts(1240, 1)=1240`; `(900, 0.5)=450`; `(825, 0.5)`: 412.5 → **413**; `(900, 0.3333)`: 299.97 → **300**. |
| C3-A10 | contracts_never_exceed_exposure | `test_sizing_n.py` | property test: 500 random `(β∈[150,5000] with cents, h∈(0,1])` | `N* <= floor(|β|)` always (I1); e.g. `β=1240.50,h=1` → 1240 not 1241. `h=0`, `h=1.01`, `h<0` raise. `n_filled <= n_target` always. No-float exactness: `h=Decimal(620)/Decimal(900)`, `β=900` → `N*=620` (not 621). |
| C3-A11 | expected_cost_and_premium | `test_sizing_cost.py` | A6 fill, `fair=0.27` | `premium=cost+fee=31.51`; `expected_cost=1.21+(0.432857−0.27)·70=12.61`. NO side: `fair=1−p̂` (p̂=0.27 → 0.73). |
| C3-A12 | payoff_includes_premium_both_outcomes | `test_sizing_payoff.py` | taxi (β=+1240, buy NO, N=1240, premium P) and bar (β=−900, buy YES, N=900, premium P) | Exactly 2 rows; every row has `premium=−P`. Taxi: event net=1240−P, no-event net=1240−P. Bar: event net=−900+900−P=−P, no-event net=−P. `|net_event − net_no_event| <= |β|−N` (<$1). Headline: `unhedged_swing=|β|`, `hedged_swing=|net diff|`, `cost=premium`. |
| C3-A13 | rule1_no_market | `test_rules.py` | candidates `[]` | Decision `declined`, `reasons==["no_market"]`; Hedge has `ticker=null`; no exception; checks 2–5 logged as `passed:null, skipped:"no_market"`; check 6 logged. |
| C3-A14 | rule2_illiquid_threshold | `test_rules.py` | `N*=100`; books giving filled 49, 50, 100 | 49 → ratio 0.49 `illiquid` fail (declined). 50 → 0.50 pass, `partial=true`, status stays `proposed`. 100 → pass, `partial=false`. |
| C3-A15 | rule3_overpriced_threshold | `test_rules.py` | `avg_price=0.42`; `fair=0.27` / `0.269` / `0.30` | overpay 0.15 → **pass** (test is strictly `>`). 0.151 → fail. 0.12 → pass. Metric keys `avg_price, fair, overpay` as strings. |
| C3-A16 | rule4_basis_threshold_and_resize | `test_rules.py` | `r2=0.50/0.499`; `β=900`, `β_S=620` and `β_S=1000` | r2 0.499 → `basis_too_loose` fail; 0.50 → pass. `β_S=620` → `h=0.6889`, N* re-sized to 620, flagged `resized`. `β_S=1000` → `h=1` (capped, never >1). |
| C3-A17 | rule5_too_expensive_threshold | `test_rules.py` | `|β|=900`; expected_cost 315.00 / 315.01 / 328.20 | ratio 0.35 → pass; 0.35001 → fail; 328.20/900=0.3647 → fail with `ratio` shown to 2 dp = "0.36" matching spec example. |
| C3-A18 | rule6_over_budget_pending | `test_rules.py` | remaining 250.00; premium 250.00 / 250.01 | 250.00 → pass, `proposed`. 250.01 → `pending_approval` (not declined), hedge keeps full size. |
| C3-A19 | all_checks_logged_after_failure | `test_rules.py` | hedge failing rules 3 and 5 (spec example) | `len(checks)==6`, in order 1–6, each with `passed` and `metric`; `reasons==["overpriced","too_expensive"]`; status `declined`. Same when rule 1 fails first. |
| C3-A20 | status_precedence | `test_rules.py` | fails: {5 and 6}; {6 only}; {none} | {5,6} → `declined` (not pending), both listed in `checks`; {6} → `pending_approval`; {} → `proposed`. |
| C3-A21 | threshold_flip | `test_rules.py` | A17 case at `cost_ratio_max` 0.35 then 0.40 | Same inputs: `declined` → `proposed`. Thresholds read from `Thresholds`, not module constants. |
| C3-A22 | off_list_ticker_rejected | `test_match.py` | candidates `[T1,T2]` | `validate_pick(...,"T1")` ok; `"T3"` and `""` and `"t1"` raise `OffListError` listing allowed; empty candidate list + any ticker raises. |
| C3-A23 | candidate_filter | `test_match.py` | cache with: wrong city, closed market, closes day 9, closes day 7, NO-side-only series | Only open, NYC/team, ≤8-day markets returned; boundary: closes at exactly `now+8d` included, `+8d+1s` excluded. |
| C3-A24 | empty_candidates_not_error | `test_match.py` | cache with no NYC rain series (C1 default case) | `build_candidates` returns `[]`; downstream `evaluate` yields `no_market` Decision, never raises. |
| C3-A25 | cache_write_online | `test_kalshi_cache.py` | `httpx.MockTransport` serving fixtures | After `list_markets`+`get_orderbook`, one file per request exists in cache dir; `index.json` lists them; cursor pagination followed. |
| C3-A26 | retry_policy | `test_kalshi_retry.py` | MockTransport: 500,500,200 then 404, then timeout×4 | Third attempt succeeds (3 tries); 404 not retried; 4 timeouts raise a typed `KalshiError`. |
| C3-A27 | offline_replay_zero_network | `test_kalshi_offline.py` | Cache populated by A25 replay (or committed demo cache); `DEMO_OFFLINE=1`; transport that fails the test on any call | `list_series`, `list_markets`, `get_market`, `get_orderbook` return identical data as online; request counter on transport == 0; uncached request raises `CacheMiss` (not network). |
| C3-A28 | end_to_end_offline_pipeline | `test_pipeline_offline.py` | committed demo cache + sample Exposure JSON for taxi rain and bar rain | candidates → pick → size → evaluate completes offline; both Hedge JSONs validate against C6 pydantic model; Decimal fields serialize as strings. |
| C3-A29 | order_book_shape_tolerant | `test_kalshi_book.py` | recorded real response (`fixtures/kalshi_cache/`) | Parser handles the shape Kalshi actually returns (see open question G1); unknown extra keys ignored; counts int, prices Decimal. |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C3-H1 | C1 market inventory | Run `list_series("Climate and Weather")` + `list_markets(...)`; open each ticker on kalshi.com | Written list of open NYC high-temp / rain / Knicks / Rangers tickers with close times, and a go/no-go per exposure (rain, hot, home_win). Matches the C1 default if rain is missing. |
| C3-H2 | Parsed ask vs. live site | Pick 3 live markets; compare our `yes_ask`/`no_ask` and top-of-book depth with the Kalshi web ticket | Within one tick of the site (site may move seconds later); YES and NO asks sum to ≥ $1.00 (never < $1.00). |
| C3-H3 | Fee vs. Kalshi's own number | Enter our N and price in Kalshi's fee schedule/calculator (or a small paper ticket preview) | Our fee equals theirs to the cent; if not, G3 is raised before 9 PM. |
| C3-H4 | Payoff table | Read one taxi and one bar hedge card's table | Both outcomes shown, premium in both rows, net-vs-base within a dollar of flat between rows; headline "Unhedged swing / hedged swing / cost" agrees with the table. |
| C3-H5 | Contracts ≤ exposure | Compare `n_filled` to exposure `effect_usd` on 3 hedges | `n_filled ≤ |β|` every time; with `h<1` visibly smaller. |
| C3-H6 | Decline summary readability | Give the `summary` of a declined hedge to a non-trader teammate | They can say why it was declined and roughly the numbers, with no jargon ("basis", "slippage"); every number is also in `checks`. |
| C3-H7 | Threshold flip | Change `overpay_max` / `cost_ratio_max` in config (or settings drawer) and rerun | A borderline decision flips declined ↔ proposed and the log shows which check changed. |
| C3-H8 | Off-list rejection | In chat/agent, ask Claude to use a ticker not in the list | Tool returns an off-list error; no hedge is created for it. |
| C3-H9 | Offline demo | Turn Wi-Fi off, `DEMO_OFFLINE=1`, run the desk for both businesses | Completes with the same hedges as the warm online run; no hangs, no timeouts, no stack traces. |
| C3-H10 | Partial and pending visuals | Force a thin book and a tiny budget | Partial fill shows "filled X of Y"; over-budget shows "pending approval", never "declined" or auto-approved. |
| C3-H11 | Basis story | Look at a rain hedge for the bar | Metric reads like "contract paid on 68 days, bar lost money on 41", r2 shown; sizing reduced when R² passes but `β_S < β`. |

## Fixtures & sample data needed

| Path | Content | Who |
|---|---|---|
| `fixtures/kalshi_cache/` | Warm cache: series list (Climate and Weather, NBA, NHL), open markets for the demo week, one orderbook per candidate, a few settled markets + candles | C3 (warm online once, commit); C8 re-warms at 2 AM |
| `fixtures/markets_test/book_basic.json` | A4 book (YES/NO bids as above) | C3 |
| `fixtures/markets_test/book_3level.json`, `book_boundary.json`, `book_thin.json`, `book_empty.json` | Ladders for A6–A8, A14 | C3 |
| `fixtures/markets_test/candidates_*.json` | Candidate lists (empty, 2 items, mixed-city) | C3 |
| `fixtures/markets_test/series_fee_{standard,x2,flat}.json` | Fee variants | C3 |
| `fixtures/businesses/exposure_taxi_rain.json`, `exposure_bar_rain.json`, `exposure_taxi_hot.json`, `exposure_taxi_homewin.json` | Sample Exposure objects (spec §5 format) incl. `hedge_side` | C2 (C3 consumes) |
| `fixtures/markets_test/basis_*.json` | `{r2, beta_s}` pairs for A16 | C2/C3 |
| `fixtures/samples/hedge_*.json`, `decision_*.json` | One proposed, declined (spec example), pending_approval, no_market, partial; frozen at 3:30 PM for C4/C5/C7 | C3 |

## Definition of done

- C3-A1…A29 pass in CI with network blocked; `grep` finds no `float(` or float literals in money paths of `markets/`.
- C1 inventory written (H1) and the demo-week cache committed.
- Sample Hedge/Decision JSON checked in and validated by C6 pydantic models; C4, C5, C7 have built against them.
- Live run on real Kalshi data (taxi rain or hot, bar rain) produces a sized hedge, and at least one real decline with readable reasons (the demo moment).
- H2–H5 and H9 signed off by a second person; H3 mismatch (if any) resolved.
- `DEMO_OFFLINE=1` full pipeline run twice yields byte-identical Hedge JSON.
- Thresholds only in `config.py`; no duplicated constants in `rules.py`.

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| G1 | Exact order-book JSON shape (spec says "bids only", not field names; Kalshi has changed shapes, e.g. fixed-point dollar string fields). | Parser accepts both `{"orderbook":{"yes":[[price,count]],"no":[...]}}` and the dollar-string variant; confirm on first live call (C1) and pin the shape with A29. |
| G2 | `ceil(h·|β|/$1)` can exceed `|β|` when β is fractional, violating I1. | `N* = min(ceil(h·|β|), floor(|β|))`; I1 wins. |
| G3 | Fee on multi-level fills: per level rounded, or once on the order? Spec says "per order". | Sum unrounded per-level fees, round up once (A6). Confirm against Kalshi calculator (H3); `fee_multiplier` scales the 0.07. |
| G4 | Where do `R²` and `β_S` (rule 4) come from, and what is `β_S`? | C2 supplies `BasisStat` from `train`: `r2` = squared correlation of the two binary flags; `β_S` = OLS effect of the settlement flag on revenue. Rule 4 is `passed:true, skipped:"no_basis_needed"` for `home_win` (flag equals settlement). |
| G5 | Rule 4 changes `h`, which changes fill (rule 2), overpay (3), cost ratio (5). Order of evaluation unspecified. | Resolve `h` from `BasisStat` first, size once with the final `h`, then run checks 1–6 and log them in table order. |
| G6 | Rule 5 `swing` and `expected_cost` use `N*` or filled N? | Use `n_filled` for `expected_cost`, `|β|` (not scaled by h) for the denominator, as in spec example (328.20/900). |
| G7 | Checks that can't be computed when no market (rules 2–5). | Log as `passed:null, skipped:"no_market"`; check 6 logged as passed (premium 0). |
| G8 | Status for `partial` and `resized`; `proposed` is not named in spec. | `status="proposed"` plus boolean flags; `reasons` stays empty. |
| G9 | Temperature has many strike brackets per day (and "between" markets); spec refits per strike but matching runs after exposure. | Candidates for `hot` = threshold ("greater than") markets only; C2 refits exposure at the candidate's `floor_strike` on demand; pick order by liquidity then strike nearest to the exposure's default strike. |
| G10 | Which side's `fair` when `hedge_side` is "no". | `fair = 1 − p̂` per spec; `p̂` computed by C2 for the *settlement* flag, not the business flag. |
| G11 | Offline cache miss behavior. | Raise `CacheMiss`; agent shows an error naming the ticker (no silent `no_market`); `make seed` warms every ticker the desk can touch. |
| G12 | "Cost $Z" in the headline: premium or expected cost? | Premium (cash out). `expected_cost` is a separate field used only for rule 5. |
| G13 | Cache staleness: orderbooks drift. | Online mode always refetches books/markets and overwrites cache; series list cached per day. Offline serves latest file. `fetched_at` shown in UI with "cached" label (I6). |
| G14 | Whether `window_days=8` is counted from `now` or week start. | From `now` (UTC), per spec "closes within 8 days"; test boundary in A23. |
| G15 | Kalshi rate limits / auth for public endpoints. | Cap concurrency at 4 requests; retry on 429 honoring `Retry-After`; if unauthenticated reads are rejected, fall back to cache and flag in C1. |

## C1 inventory (live public API, no key, 2026-10-24 23:10 UTC)

Cache: `fixtures/kalshi_cache/` (re-warm: `cd backend && python -m scripts.warm_kalshi_cache`). Both `external-api.kalshi.com` and `api.elections.kalshi.com` answer unauthenticated reads. Asks are derived from the book (`1 − best opposite bid`).

| Exposure | Series | Open tickers in 8-day window | Close (UTC) | YES ask | NO ask | Go? |
|---|---|---|---|---|---|---|
| rain | `KXRAIN` (multi-city; NYC = `-NYC` suffix). `KXRAINNYC`/`KXRAINDNYC` have nothing open | `KXRAIN-26OCT24-NYC`, `KXRAIN-26OCT25-NYC` | Oct 25 05:00, Oct 26 05:00 | 0.01, 0.01 | none (no YES bids) | **GO** (YES side only today) |
| hot | `KXHIGHNY`, `strike_type="greater"` only | `KXHIGHNY-26OCT24-T66`, `KXHIGHNY-26OCT25-T71` | Oct 25 05:00, Oct 26 05:00 | 0.01, 0.01 | none (no YES bids) | **GO** (YES side only today) |
| home_win | `KXNBAGAME` (NYK home), `KXNHLGAME` (NYR home) | `KXNBAGAME-26OCT25ORLNYK-NYK`, `KXNHLGAME-26OCT26LANYR-NYR`, `KXNBAGAME-26OCT27DETNYK-NYK` | Oct 27 23:00, Oct 28 23:00, Oct 30 00:00 | 0.76, 0.57, 0.69 | 0.26, 0.47, 0.36 | **GO** |

Findings that affect other chunks:
- Daily weather markets list only ~1 day ahead (created ~09:30 UTC for the next day), so the 8-day window holds today + tomorrow only.
- `KXHIGHNY` resolves YES iff Central Park (CLINYC) max temp is **strictly greater than** `floor_strike` (T71 = "72° or above"). Spec §5 says `hot = tmax ≥ strike`: C2 should use `tmax > floor_strike`.
- `KXRAIN-…-NYC` resolves YES iff CLINYC precipitation is strictly > 0 in, per The Weather Company.
- NBA/NHL series have `fee_type: "quadratic_with_maker_fees"` (weather: `"quadratic"`), both with multiplier 1. #43's `fee_unverified = fee_type != "quadratic"` would flag every game hedge.
- Game tickers read `<date><AWAY><HOME>-<YES team>`; `close_time` is ~2 days after tip-off (`occurrence_datetime`).
- Book shape (G1): `{"orderbook_fp": {"yes_dollars": [[price, size]], "no_dollars": [...]}}`, ascending, sizes fractional (`"1334302.28"`, floored to whole contracts), empty side = `[]`.
- `status=open` queries return markets with `status: "active"`; `status=settled` returns `"finalized"`.
- Candles for markets settled before `GET /historical/cutoff` (2026-08-25) 404 on the live path and come from `/historical/markets/{t}/candlesticks`.

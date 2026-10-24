# C2 · Stats

> Cross-chunk conflicts are resolved in [CONTRACTS.md](../../../docs/CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | OLS exposure model with HC3 errors, hedgeability gate, `hedge_side`, per-contract settlement coefficient `β_S` (for rule 4), planted-effect model check, `r2_holdout`, walk-forward backtest. Pure functions over DataFrames; no network, no LLM, no DB. |
| **Files** | `backend/app/stats/exposure.py`, `modelcheck.py`, `backtest.py` (+ `__init__.py`) |
| **Spec sections** | §5, §5.1, §10; invariants I1 (h ≤ 1, N from \|β\|), I2 (numbers originate here), I6 (`estimated` propagates); §4.4 (input), §7/§8 (backtest reuses), §16 gates |
| **Owner role** | Stats and markets |
| **Depends on** | **C1 Data**: feature table (§4.4), train/holdout split. **C3 Markets**: `sizing.py` (N, fee, premium), `rules.py` (rules 3-5 as pure functions), `kalshi.list_settled` / `candles`. **C6**: `config.py` thresholds. Consumed by **C4** (`get_exposures`, `run_backtest` tools), **C6** (`/analyze`, `/backtest`), **C7** (charts). Not used: C5 Books, C8. |
| **Gate** | **3:30 PM**: Exposure, ModelCheck, BacktestResult JSON examples checked into `fixtures/examples/`. **6:00 PM**: exposure fit + model check working on both real feature tables (notebook `03_exposure.ipynb`). **9:00 PM**: backtest with frequency pricing, labeled. **Midnight**: real-priced backtest (`priced_real_pct > 0`). |

## Interfaces

### Consumes
| Input | Shape |
|---|---|
| Feature table (C1) | pandas DataFrame, one row/day, columns exactly per §4.4: `date, revenue(float), dow, doy, is_holiday, msg_event, home_game, home_win, rain, rain_open_hours, tmax, estimated` + `split` in {`train`,`holdout`} |
| Contract spec | `{settlement_var: "rain"\|"hot"\|"home_win", strike: float\|None, side_fire_flag: Series[bool]}`; `strike` required for `hot` |
| Settled contracts + candles (C3) | per date: `{date, ticker, result: "yes"\|"no", close_price: Decimal, volume: int}` |
| Sizing/rules (C3) | callables: `size(beta, h, price) -> {N:int, fee:Decimal, premium:Decimal}`; `rule_overpriced`, `rule_basis` (needs `h`), `rule_too_expensive` returning `{passed, metric}`; thresholds from `config.py` |

### Produces
**`fit_exposures(df, strikes: dict[str,float]) -> ExposureResult`**
```
ExposureResult = {
  "exposures": [Exposure], "dropped": [Exposure],      # dropped = hedgeable:false, reasons non-empty
  "r2_holdout": float, "r2_train": float, "n_train": int, "n_holdout": int,
  "estimated": bool, "cov_type": "HC3", "model_check": ModelCheck }
Exposure = {  # §5, unchanged
  "id": "exp_<event>", "business_id": str, "event": "rain"|"hot"|"home_win",
  "effect_usd": float (signed, 2dp), "ci90": [float, float], "se": float, "p_value": float,
  "n_events_train": int, "direction": "positive"|"negative",
  "hedge_side": "yes"|"no", "settlement_var": "rain"|"hot"|"home_win",
  "hedgeable": bool, "reasons": [ "below_size" | "not_significant" | "thin_support" ],
  "strike": float|null,                  # hot only
  "beta_settlement": float|null }        # β_S per contract, see Gaps G1
```
`hedge_side = "no"` iff `effect_usd > 0`, else `"yes"`. Controls (`msg_event`, `home_game`, `holiday`) never appear as exposures.

**`beta_settlement(df, settle_flag: Series[bool]) -> {beta_S: float, se: float, r2_flags: float}`** (feeds rule 4; `r2_flags` = R² between exposure flag and settle flag on `train`).

**`run_model_check(df, event="rain", n_seeds=50, effect=500, frac=0.15) -> ModelCheck`**
```
ModelCheck = { "planted_usd": 500, "frac": 0.15, "n_seeds": 50,
  "example": {"seed": int, "recovered": float, "ci90": [float,float], "contains_truth": bool},
  "coverage": float, "mean_recovered": float, "target": 0.90 }
```

**`run_backtest(df, contracts, exposures, cfg) -> BacktestResult`** (money as Decimal strings in JSON, per §12)
```
BacktestResult = {
  "std_unhedged": "…", "std_hedged": "…", "reduction_pct": float,
  "worst_week_unhedged": {"week_start": date, "income": "…"},
  "worst_week_hedged":   {"week_start": date, "income": "…"},
  "total_premium": "…", "n_hedges": int, "n_declined": int, "priced_real_pct": float,
  "per_exposure": { "<id>": {"reduction_pct": float, "total_premium": "…", "ineffective": bool} },
  "weekly": [ {"week_start": date, "unhedged": "…", "hedged": "…", "premium": "…"} ],
  "pricing_tier": "real"|"mixed"|"frequency", "estimated": bool }
```

## Automated acceptance tests

Test dir: `backend/tests/stats/`. All use `numpy.random.default_rng(seed)`; no network.

| ID | Test name | Future test file | Setup / fixture | Assertion |
|---|---|---|---|---|
| C2-A1 | recovers known rain beta | `test_exposure.py` | `synth_taxi`: 365 train days, true rain β=+1200, noise σ=400, DOW effects | `effect_usd` within 1.645·se·1.5 of 1200; `ci90` contains 1200 |
| C2-A2 | recovers negative beta | `test_exposure.py` | same, β_rain=-800 | `effect_usd<0`, `direction=="negative"`, `hedge_side=="yes"` |
| C2-A3 | hedge_side direction table | `test_exposure.py` | parametrize sign of β over rain/hot/home_win | positive -> `no`; negative -> `yes`, for every event; nothing else changes it |
| C2-A4 | HC3 used | `test_exposure.py` | heteroskedastic synth (σ ∝ DOW) | `se` equals statsmodels `cov_type="HC3"` value to 1e-9 and differs from nonrobust; result `cov_type=="HC3"` |
| C2-A5 | size gate boundary | `test_exposure.py` | β = 149.99 / 150.00 / 150.01 with tiny noise | hedgeable False (`below_size`) / True / True; boundary is `>=` |
| C2-A6 | significance gate | `test_exposure.py` | β=300, σ huge so 90% CI spans 0 | `hedgeable False`, `reasons==["not_significant"]` |
| C2-A7 | support gate boundary | `test_exposure.py` | rain on exactly 9 vs 10 train days, large β | 9 -> `thin_support`; 10 -> passes; `n_events_train` correct |
| C2-A8 | multiple reasons listed | `test_exposure.py` | small, noisy, 5 events | all three reasons present, order stable |
| C2-A9 | zero effect | `test_exposure.py` | no rain effect | not hedgeable; no exception; `hedge_side` still set from sign |
| C2-A10 | controls never exposures | `test_exposure.py` | strong `msg_event` effect | `msg_event`/`home_game` absent from `exposures` and `dropped` |
| C2-A11 | hot refit per strike | `test_exposure.py` | tmax synth, true step at 85F | strike 85 recovers β; strike 60 yields different `n_events_train`; `strike` echoed |
| C2-A12 | collinear/degenerate input | `test_exposure.py` | event flag all False, or constant revenue | no crash; exposure dropped with `thin_support`; no NaN in output JSON |
| C2-A13 | train-only fit | `test_exposure.py` | holdout rows with wildly different revenue | coefficients identical with/without holdout rows present |
| C2-A14 | r2_holdout out of sample | `test_exposure.py` | synth with known R² | `r2_holdout` computed from train-fit predictions on holdout; equals manual calc to 1e-9; may be negative without error |
| C2-A15 | beta_S recovery | `test_exposure.py` | settle flag = rain flag with 30% disagreement noise, true β_S known | `beta_S` recovers within CI; `\|β_S\|<\|β\|`; `r2_flags` matches Pearson² of flags |
| C2-A16 | identical flags | `test_exposure.py` | settle flag == exposure flag | `beta_S == effect_usd` (1e-9), so `h==1.0` downstream (I1) |
| C2-A17 | estimated propagation (I6) | `test_exposure.py` | `estimated=True` frame | `ExposureResult.estimated` and `BacktestResult.estimated` True; False for taxi |
| C2-A18 | JSON schema | `test_exposure.py` | any fit | output validates against `fixtures/examples/exposure.schema.json`; floats finite; keys exactly as §5 plus `strike`, `beta_settlement` |
| C2-A19 | planted $500 coverage | `test_modelcheck.py` | `synth_taxi` (or real train series), 50 seeds, 15% planted | coverage in [0.80, 0.97]; `mean_recovered` in [450, 550] |
| C2-A20 | planted check determinism | `test_modelcheck.py` | same seed twice | identical `example`; different seeds differ; global RNG untouched |
| C2-A21 | planted flag in model | `test_modelcheck.py` | inspect fitted design | `planted` is an extra regressor alongside all original ones; original `train` frame not mutated |
| C2-A22 | model check negative control | `test_modelcheck.py` | `effect=0` | CI contains 0 in ~90% (same band); planted column never auto-labeled hedgeable |
| C2-A23 | backtest week structure | `test_backtest.py` | 20 holdout weeks synth, no hedging possible | weeks Monday-start; partial edge weeks dropped; `unhedged` equals sum of revenue; empty hedge set -> `reduction_pct==0`, `total_premium=="0"` |
| C2-A24 | no look-ahead | `test_backtest.py` | perturb holdout week k revenue/outcomes | exposures/prices used in weeks < k unchanged; monthly refit uses only data before the refit date |
| C2-A25 | perfect hedge reduces swing | `test_backtest.py` | synth rain β=1000, contract = rain flag, price = p̂, fee=0 | `reduction_pct` > 90%; `std_hedged < std_unhedged` |
| C2-A26 | basis loose hedge | `test_backtest.py` | settle flag 50% wrong | `reduction_pct` strictly less than A25 and `h<1` applied |
| C2-A27 | h cap (I1) | `test_backtest.py` | β_S > β | every hedge has `N <= ceil(abs(beta))` and `h<=1`; asserted per hedge, not just total |
| C2-A28 | declines counted | `test_backtest.py` | price injected at 0.80 vs p̂=0.27 (stress markup) | rule 3 declines each day; `n_declined>0`, `n_hedges==0`; premium 0 |
| C2-A29 | rules 2 and 6 skipped | `test_backtest.py` | thin volume candle; budget=$0 | still hedges; no `illiquid` / `over_budget` declines |
| C2-A30 | pnl accounting | `test_backtest.py` | one hand-computed week (2 event days) | payout minus premium (incl. fee, rounded up to cent) matches hand value exactly in Decimal |
| C2-A31 | Decimal boundary | `test_backtest.py` | candles as strings | prices parsed via `Decimal`; no float used in premium/payout path (assert type); money fields serialize as strings, `reduction_pct` as float |
| C2-A32 | priced_real_pct | `test_backtest.py` | 3 of 4 hedge-days have candles | `priced_real_pct==0.75`; `pricing_tier=="mixed"`; all-missing -> `"frequency"`, 0.0 |
| C2-A33 | per_exposure ineffective | `test_backtest.py` | one useless exposure (9% reduction) and one at 10% | 9% -> `ineffective True`; 10.0% -> False (boundary `<10`) |
| C2-A34 | worst week | `test_backtest.py` | planted bad week, hedged improves it | `worst_week_unhedged.week_start` is the lowest-income week; hedged value is the same week's hedged income; `hedged >= unhedged` for that week in A25 |
| C2-A35 | fallback price tier | `test_backtest.py` | no candles | price = `p̂_trailing + markup` (config), tier "frequency"; result carries `pricing_tier` so UI labels it (I6) |
| C2-A36 | overpriced fires in stress | `test_backtest.py` | frequency tier with markup 0.20 | rule 3 declines (overpay>0.15) while markup 0.02 never does; documents Gap G2 |
| C2-A37 | determinism / speed | `test_backtest.py` | 52-week holdout | two runs identical; refit+backtest < 5 s; exposure fit < 0.5 s (per-strike refit "milliseconds") |
| C2-A38 | no IO | `test_purity.py` | import-time check | `stats/` imports no `httpx`, `anthropic`, `sqlmodel`; no file writes |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C2-H1 | Effect signs on real data | `03_exposure.ipynb` coefficient table, both businesses | Taxi: rain > 0. Bar: rain < 0. Taxi hot/cold plausible. Opposite rain sign between businesses (demo step 5). Any surprise has a story |
| C2-H2 | Effect magnitudes in dollars | Same table beside mean daily revenue | Rain effect is a sane fraction (roughly 3-25%) of daily revenue; CI width not absurd |
| C2-H3 | Residuals | Residual vs fitted, vs date, by DOW; ACF plot | No obvious trend/seasonal leftovers; no giant outliers unexplained (storm, holiday, outage); note autocorrelation if present |
| C2-H4 | HC3 vs naive SE | Print both | HC3 SE >= naive on heteroskedastic days; conclusions same or documented |
| C2-H5 | "Measured, not hedged" list | Look at `dropped` with reasons | `home_win` plausibly small/insignificant; reasons readable by a non-trader |
| C2-H6 | Model check chart | Histogram of recovered over 50 seeds with 500 line; coverage printed | Mass centered at 500; coverage near 0.9 (in [0.8, 0.97]); explainable in one sentence for judges |
| C2-H7 | Holdout R2 | Read `r2_holdout` vs `r2_train` | Holdout reasonably close to train; if negative, say so and fix before demo |
| C2-H8 | Worst week story | Table of 5 worst unhedged weeks with weather/games | The chosen worst week is a real rainy/event-light week; hedged value visibly better; story fits the 0:00-0:15 opener |
| C2-H9 | Backtest headline | Plot weekly unhedged vs hedged + metrics | Reduction_pct credible (not >95% unless the contract is near-perfect); premium plausible vs `$250` budget |
| C2-H10 | Pricing realism | Compare `priced_real_pct`, tier label, stress sweep (markup 0.02/0.10/0.20) | Tier label correct; sweep shows declines appear as markup rises; no result presented as real when frequency-priced |
| C2-H11 | Rule 4 numbers | For rain contract: days contract paid vs days business lost money, `β_S`, `h` | Reads like "paid 68 days; bar lost money on 41"; `h` in (0,1] and matches hand calc |
| C2-H12 | Cross-check with proxy | Taxi rain effect vs MTA/Penn subway direction (optional) | Directions agree; not required to pass tests |

## Fixtures & sample data needed

| Fixture | Path | Notes |
|---|---|---|
| Synthetic taxi/restaurant feature tables with known betas | `backend/tests/fixtures/synth_features.py` output, `synth_taxi.parquet`, `synth_bar.parquet` | Seeded; 365 train + 180 holdout days; DOW + seasonal + known β_rain, β_hot, β_win |
| Real feature tables (from C1) | `fixtures/taxi_features.parquet`, `fixtures/restaurant_features.parquet` | Needed by 6 PM; read-only |
| Example JSON: Exposure, ExposureResult, ModelCheck, BacktestResult | `fixtures/examples/*.json` + `exposure.schema.json` | Checked in by 3:30 PM for C4/C6/C7 |
| Settled contracts + candles | `fixtures/kalshi_cache/settled_<series>.json`, `candles_<ticker>.json` | From C3; include a series with sparse candles to exercise fallback |
| Hand-computed one-week backtest | `backend/tests/fixtures/backtest_week.json` | For C2-A30 |
| Frozen fixed-price sample | `backend/tests/fixtures/mock_rules.py` (C3 stub) | Lets C2 tests run before C3 lands |
| Golden outputs from real data | `fixtures/golden/exposure_taxi.json`, `backtest_taxi.json` | Regression snapshot once numbers are accepted |

## Definition of done

- [ ] All C2-A tests pass in CI offline (`pytest backend/tests/stats`), < 30 s.
- [ ] C2-H1 to H11 signed off by Stats owner plus one other teammate.
- [ ] Example JSON and schema checked in and consumed by C4/C6/C7 without field renames.
- [ ] Both businesses: `analyze` returns exposures, dropped with reasons, model check, `r2_holdout`.
- [ ] Backtest headline sentence generated from `BacktestResult` fields only (I2); pricing tier visible.
- [ ] Gaps G1-G3 resolved and recorded in the decision log of the spec (or accepted defaults below).
- [ ] No float in money path; no network or LLM import in `stats/`.

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| G1 | Rule 4's `β_S` undefined | `β_S` = OLS coefficient on the contract's **settlement flag** `S_t` in the same model as §5 with `S_t` replacing the exposure flag (same controls, HC3, `train`). `h = min(1, \|β_S\|/\|β\|)`; if sign(β_S) != sign(β) or insignificant, `h=0` -> `basis_too_loose`. `r2_flags` is the flag-to-flag R² for the 0.5 cutoff. Computed in `exposure.py`, passed to C3 |
| G2 | Backtest fallback `p̂_trailing + 0.02` makes rules 3 and 5 nearly never fire (overpay ~ 0.02 << 0.15; expected cost/β ~ fee + 0.02 per contract << 0.35); `n_declined` would be ~0 and the desk's decline story untested | Keep 0.02 as the base case but (a) `config.FALLBACK_MARKUP`, (b) label tier "frequency", (c) report a stress sweep (0.02, 0.10, 0.20) in the notebook, not the headline, (d) never claim declines from frequency tier; also trailing p̂ window = prior 365 days, so rule 3 still compares against train `fair` and can drift |
| G3 | "Exposures frozen from train" vs "re-estimate monthly" contradict | Monthly **expanding-window** refit using only data before the refit date; first month uses train fit; dropped exposures stay dropped until a later refit passes the gates |
| G4 | Which price per day: close, open, mean? Look-ahead risk | Use the previous day's candle close for the contract that settles on date t; if absent, fallback |
| G5 | "Each day it could occur" for daily contracts implies hedging every day (premium load) | Hedge daily only for rain/hot (per-day contracts); `home_win` only on home game days; N = ceil(h·\|β\|) per day |
| G6 | `home_win` baseline mixes losses and non-game days; `home_game` is listed as control but not in the §5 formula | Add `home_game` control so `home_win` = win vs loss on game days; support = home wins in train |
| G7 | Exposure example uses JSON numbers; §12 says decimals serialize as strings | Statistical estimates (effect, ci, se, p) stay floats (locked §5 shape); `BacktestResult` money fields and any contract price are Decimal strings |
| G8 | `hedge_side` for non-hedgeable exposures | Always populated from sign; UI ignores it when `hedgeable=false` |
| G9 | CI critical value (t vs normal) and "90% CI excludes zero" | Normal z=1.645 via statsmodels `use_t=False`; documented; consistent with model check coverage |
| G10 | Definitions: worst week, `reduction_pct`, weekly std | worst = lowest weekly unhedged income (hedged value = same week); `reduction_pct = 100·(1 - std_hedged/std_unhedged)` over weekly totals; std uses ddof=1 |
| G11 | Model check on which exposure | Run on `rain` of the selected business (hedgeable or not), 50 seeds, planted on random 15% of train days; cached per business; `r2_holdout` returned alongside |
| G12 | Rules 3-5 callable from backtest | C3 must expose them as pure functions taking prices and `h`, no I/O; otherwise C2 duplicates logic and risks drift |

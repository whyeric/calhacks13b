# R2 predictors: new weather, calendar, MSG-event and lag predictors

**Question:** Do any new predictors move taxi revenue, the bar (Dewey visits × $35), or MSG arena visits in a way that replicates on the holdout year *and* that a Kalshi contract can settle?

**Answer: NOT FOUND.** Of 92 tests, none pass all the gates. Two near-misses are worth knowing about:
- **Taxi × snow day:** a real-looking −$5.8k/day effect. It replicates on the holdout and survives month dummies, but misses BH by a hair (q = 0.1002). It also has no clean daily Kalshi contract.
- **Taxi × MSG non-game spike:** passes every statistical gate, but no contract can settle it.

## Data
- **Series** (`features.build`, 2024-10-01 to 2026-08-31, train = first 365 days, holdout = 335):
  - taxi
  - bar (`restaurant`)
  - MSG arena daily Dewey visits (aggregate; used as y in visits, not $)
- **Weather:** NOAA GHCN-Daily **USW00094728 (Central Park)**: PRCP, SNOW, SNWD, TMAX, TMIN, WSF2. This is the station the NWS CLI report covers, which is what KXHIGHNY and KXRAIN settle on. Heat index and RH come from Open-Meteo at the Central Park grid point. Both are cached in scratchpad `r2-cache/`.
  - GHCN vs the repo's `weather_station.parquet` (Open-Meteo): rain ≥ 0.01 in agrees on 87% of days; tmax correlation 0.993, mean bias −0.35 °F. The fixture is therefore a decent but imperfect proxy for settlement. Use GHCN for any real basis check.
- **Calendar:**
  - Payday: the 1st and 15th
  - Month start: days 1–3
  - NYC DOE recess weekdays, non-summer: hand-entered and approximate
  - Summer break
  - DST week: the 7 days from each change

## Method
- **Model:** one OLS per (series, predictor). Controls are const, DOW, season harmonics k = 1, 2, `is_holiday` and `home_game`. For the interaction and the lags, today's `rain` main effect is also included.
- **Errors and splits:** HAC (Newey-West, 7 lags), z = 1.645. Train and holdout are fitted independently.
- **BH:** at 10% over all 92 train p-values.
- **FOUND gates:** train CI excludes 0, ≥ 10 train event days, BH q < 0.10, holdout same sign with CI excluding 0, and Kalshi-settleable.
- **Follow-up checks:** month-dummy robustness, holdout leave-one-event-out, and the hedge backtest. These ran only on the 3 that replicated.

## Results (tests where something passed)

92 tests: 31 predictors × 3 series, minus the tautological MSG-spike-on-MSG-visits test. 24 were significant on train, which is about 2.6× the ~9 expected by chance. 9 have q < 0.10. **3 replicate on the holdout.** 0 are FOUND.

| series | predictor | train β [90% CI] (n ev) | q_train | holdout β [90% CI] (n ev) | settle | verdict |
|---|---|---|---|---|---|---|
| taxi | **snow_day** (SNOW ≥ 0.1 in) | −5,785 [−9,572, −1,998] (13) | **0.1002** | −9,547 [−18,242, −852] (13) | weak (see below) | NOT FOUND: misses BH by 0.0002 |
| taxi | **msg_nongame_spike** | +3,763 [+1,557, +5,970] (46) | 0.058 | +5,366 [+1,839, +8,893] (27) | none | NOT FOUND: no contract |
| msg_visits | rain_x_weekend | −2,779 [−5,104, −454] (33) | 0.238 | −3,183 [−5,745, −621] (42) | KXRAIN, Sat/Sun only | NOT FOUND: fails BH |
| msg_visits | bracket_50_60 | +4,228 [+2,851, +5,605] (57) | 0.00004 | +597 [−1,003, +2,196] | KXHIGHNY bracket | NOT FOUND: no replication |
| taxi | bracket_90_up / tmax_gt90 | +5,979 / +6,394 (14 / 10) | 0.033 / 0.050 | −1,467 / −2,934, cross 0 | KXHIGHNY > 90 | NOT FOUND: sign flips |
| taxi | heat_index_ge90 | +5,862 [+2,911, +8,813] (45) | 0.033 | −1,294, crosses 0 | none | NOT FOUND: sign flips |
| taxi | tmax_gt85 | +4,871 [+2,199, +7,543] (37) | 0.050 | +108, crosses 0 | KXHIGHNY > 85 | NOT FOUND |
| taxi | cdd (per °F-day) | +386 [+147, +624] | 0.079 | −91, crosses 0 | strike ladder | NOT FOUND: sign flips |
| bar | snow_depth_1in | −2,032 [−3,165, −899] (22) | 0.050 | +188, crosses 0 | none | NOT FOUND: sign flips |
| msg_visits | bracket_70_80 | −2,953 [−4,627, −1,280] (74) | 0.050 | −563, crosses 0 | KXHIGHNY bracket | NOT FOUND |

All other tests fail on train. These include rain lags 1–3 (null everywhere), payday (taxi train +3,841 then holdout −1,894), DST, school breaks, precip intensity (log1p mm), gusts > 25 mph (only 2 train days) and "first nice day" (4 days). The full table is in `results.csv`.

**Heat in taxi is the round 1 pattern again:** hot-day effects that are strong on train flip sign on holdout, whether as tmax > 85, > 90, a 90+ bracket, heat index or CDD. **Don't hedge taxi on temperature.**

## Near-miss 1: taxi × snow day
- **Robustness:**
  - Month dummies in place of harmonics: train −5,960 (p 0.004), holdout −9,946 (p 0.039).
  - Holdout leave-one-snow-day-out: β stays in [−11,235, −6,295], so no single storm drives it.
  - Holdout p = 0.071 on its own.
  - This looks like a **real** effect: snow cuts zone taxi revenue by roughly 10–15% of a typical day.
- **Why it isn't FOUND:**
  - BH q = 0.1002 against a 0.10 bar. I did not relax it.
  - There are only 13 snow days per season, so CIs are wide.
  - **Basis:** I'm not aware of a *daily* NYC snow contract; Kalshi's NYC snow markets are monthly or seasonal totals. A daily snow-day exposure hedged with a monthly-total contract is a loose basis, and I did not measure that basis here.
- **Hedge backtest:**
  - Setup: hypothetical daily "CP snow ≥ 0.1 in" contract, buy YES at train frequency + 0.02 = $0.06 plus fee, 5,785 contracts.
  - Holdout SD falls from 12,489 to 12,305 (−1.5%).
  - P5 day rises from 50,029 to 50,852 (+$823).
  - Average cost is −$119/day.
  - The P5 gain is the most of anything we've tested, but it assumes a daily snow contract exists.

## Near-miss 2: taxi × MSG non-sport event
Days with an MSG visit spike and no Knicks/Rangers home game (concerts and similar):
- **Size:** +$3.8k train, +$5.4k holdout. It holds up with month dummies on holdout (p 0.007), and only marginally on train (p 0.09).
- **Statistically it's the cleanest result in this folder,** but **no Kalshi contract settles on concert attendance**, so it fails gate 4. It's useful as a forecasting control, not as a hedge.
- **The bar:** its β has the same sign (+1,103, then +2,488 with holdout CI just above 0) but fails on train.

## Takeaways
1. Nothing settleable passes. The best settleable candidate (taxi snow) is honest-to-goodness borderline.
2. **Taxi heat effects flip sign** across years in every form tried, which confirms round 1's "unstable" decline.
3. **The bar is null on every new predictor** too: 0 of 31 replicate, and the one weak replication fails on train.
4. **Possible demo line:** "Snow is the one weather risk for a taxi zone that held up across two winters, but there's no daily snow contract to hedge it with, and the evidence is right at the edge of chance after testing 92 things."

Script: `predictors.py` (run from `backend/`). Output: `results.csv`.

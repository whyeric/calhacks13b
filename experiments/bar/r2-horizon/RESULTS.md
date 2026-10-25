# R2 horizon: weekly and monthly weather totals, and the contracts that settle on them

**Question.** Daily events explain ~1% of daily variance. Do weekly or monthly weather totals (rainy days, total precip, days > 85°F, cooling degree-days, snowfall) explain weekly or monthly revenue in a way that replicates? And does Kalshi list weekly or monthly NYC contracts to hedge with?

**Verdict: NOT FOUND.** Of 54 tests, 3 pass all four gates as written. None of the 3 holds up:
- The two taxi-zone monthly cells rest on 12 train months (6 residual df) and fail a small-sample check.
- The HVFHV snow cell flips sign when train is limited to the post-COVID years.
- The one hedge backtest (monthly rain, taxi) made income less steady.

Run from `backend/`: `.venv/bin/python ../experiments/bar/r2-horizon/horizon.py`. Downloads are cached in the scratchpad `r2-cache/` (`r2h_*` files).

## Kalshi contracts at weekly and monthly horizons (public API, 2026-10-24)

| Series | What | Strikes | Settles on | Status |
|---|---|---|---|---|
| **KXRAINNYCM** | Monthly rain, NYC | "Above X in", X = 1..10, strictly greater | NWS CLI, Central Park monthly total | **Live.** Aug–Dec 2026 events listed; ≈184k contracts traded in the 25 finalized markets. Sep 2026 settled at 5.31 in; GHCN gives 5.30 in. |
| **KXRAINNYCW** | Weekly rain, NYC (Mon–Sun) | 0.25 / 0.5 / 1 / 2 in | The Weather Company daily sums (weather.com/kalshi), not NWS | New. One event so far (Sep 28–Oct 4 2026), ≈1.8k contracts. Basis to Central Park CLI not verified. |
| **KXNYCSNOWM** | Monthly snowfall, NYC | 2 / 4 / 6 / 8 / 10 / 12 in | The Weather Company | Dec 2026 event open, ≈2.6k contracts so far. |
| KXSNOWNYM / SNOWNYM | Monthly snow, NYC | 0.1 to 20 in | NOAA, Central Park | Ran Nov 2021 to Feb 2025, then stopped. See the snow section. |
| KXNYCHOT ("NYC heat", monthly), KXMINNYC (monthly min temp) | Monthly temperature | – | NWS CLI | Series exist, **no markets listed**. |
| KXWEEKHTNYC | Weekly high temperature | – | The Weather Company | Series exists, no markets listed. |

So a live **monthly rain** contract exists on the same station and report as the daily ones. A weekly rain contract and a monthly snow contract have just started, and both settle on Weather Company data. Nothing monthly or weekly on temperature is live, so the only heat hedge is still daily KXHIGHNY.

## NYC snow contracts (for the taxi snow effect)

Taken from the public API's `/series`, `/events` and `/historical/markets` on 2026-10-24. Every NYC snow contract pays on a snowfall **total strictly greater than X inches** over a window, at Central Park.

| Series | Window | Strikes (in) | Station and source | History | Open now? |
|---|---|---|---|---|---|
| **KXNYCSNOWM** | Calendar month | 2, 4, 6, 8, 10, 12 | "NYC" station on The Weather Company dashboard (weather.com/kalshi), local calendar days | Only Dec 2026 | **Yes: Dec 2026**, closes 2027-01-01. Last prices: > 2 in $0.45, > 4 in $0.29, > 6 in $0.24, > 10 in $0.08. About 2.6k contracts so far. |
| KXSNOWNYM / SNOWNYM | Calendar month, closes 3 days after month end | 0.1 to 20 (varies) | Central Park, NOAA | 17 months, Nov 2021 to Feb 2025. Liquid: Jan 2025 had 512k contracts, Feb 2025 468k. | No. Retired after Feb 2025; KXNYCSNOWM looks like the replacement. |
| **KXSNOWSTORM** (NYC events) | Multi-day storm window, e.g. Jan 24–26 2026 or Feb 21–24 2026 | 2 to 24 | NWS Daily Climate Report (CLI NYC), Central Park | 3 NYC events in 2026: Jan 24–26 (6.0M contracts, settled > 8 in YES), Jan 30–Feb 3 (170k, NO), Feb 21–24 (4.0M) | No. These are one-offs listed only once a storm is forecast. |
| KXSNOWNY / SNOWNY | **Single day** | > 0 in, plus others | NWS CLI Central Park | 8 days, Dec 2021 to Feb 2022 (e.g. Jan 29 2022: 7.3 in, 51k contracts) | No. Retired in 2022. |
| KXNYCSNOWXMAS | Dec 25 only | > 0 | NWS CLI Central Park | 2025 (157k contracts, NO) | No. Annual one-off. |
| KXSNOWNYC | – | – | weather.gov | None | No markets ever listed. |

**Basis check:** monthly snow totals from NOAA GHCN for Central Park (USW00094728) match Kalshi's NOAA-settled values exactly: Dec 2024 2.8 in, Jan 2025 3.0 in, Feb 2025 7.1 in. The Jan 24–26 2026 storm is 11.4 in on GHCN, consistent with the "> 8 in YES" settlement. The current KXNYCSNOWM uses Weather Company data instead, which I have not checked against GHCN.

**What this means for the taxi snow hedge:**
- **No daily snow contract has been live since 2022.** A per-snow-day β can't be settled one-for-one.
- **The only contract open now is KXNYCSNOWM, Dec 2026, monthly.** A monthly snow-total flag tracks the taxi's daily snow days only loosely. On GHCN Dec–Mar months since 2010, R² of the monthly total against the settlement flag is 0.34 for > 2 in, 0.54 for > 4 in and 0.62 for > 6 in. Expect basis loss on top of that from the Weather Company source.
- **Storm contracts (KXSNOWSTORM) are the most liquid and fit a snow-day effect best:** a multi-day window, settled on Central Park CLI. But they're listed only once a storm is already forecast and priced on that forecast. You can't buy them ahead of time at the climatological frequency the backtest assumes. They'd work as an event-driven hedge ("a storm is forecast, buy now"), not a standing one.
- **Recommended:** for a standing hedge, use KXNYCSNOWM at the strike that best matches the train β, with p̂ from GHCN Dec–Mar frequencies (> 2 in 0.63, > 4 in 0.46, > 6 in 0.39), and report the basis R² above. For a demo, KXSNOWSTORM is the live, liquid story.

## Data and method

- **Series:**
  - taxi zone: `features.build("taxi")`, 700 days, Oct 2024 to Aug 2026; daily, weekly (99 weeks) and monthly (23 months).
  - bar: Dewey visits × $35, opaque id, 1,001 days; weekly (143 weeks) and monthly (32 months).
  - Longer, cheap, public: TLC's citywide monthly report (`data_reports_monthly.csv`) with yellow trips/day and farebox/day for 2010-01 to 2026-07, and HVFHV (app-ride) trips/day for 2015-01 to 2026-07. COVID months (2020-03 to 2022-06) are dropped.
- **Weather:** NOAA GHCN-Daily USW00094728 (Central Park), the station behind the CLI report. Hot = tmax > 85°F. CDD uses base 65°F on (tmax + tmin) / 2. Weeks run Mon–Sun. Settleable binaries: weekly precip > 0.5 or > 1 in, monthly precip > 4 in and snow > 2 in.
- **Models:** each cell is one predictor plus calendar controls.
  - Daily: DOW, holiday, 3 harmonics and a trend.
  - Weekly: holiday count, 3 harmonics and a trend.
  - Short monthly: holiday count, 1 harmonic and a trend.
  - Long monthly: log y on month dummies, year fixed effects and the weekend-day count.
  - Errors are HAC (lags 7 / 4 / 3) with z = 1.645. Train is fit, then holdout is refit independently. BH at 10% runs over all 54 train p-values.
- **Splits:**
  - taxi: train to 2025-09-30, holdout after.
  - bar: train to 2025-05-31, holdout after.
  - yellow: train 2010–2017; holdout 2018–2019 plus 2022-07 to 2026-07.
  - HVFHV: train 2015-01 to 2024-06; holdout 2024-07 to 2026-07.

## Results

**54 tests** = 5 daily (taxi) + 7 × 2 weekly + 7 × 2 short monthly + 7 × 3 long monthly. 13 pass BH at 10%, and **3 pass every gate**.

Selected rows. Units are $ per unit of the predictor, or % per unit for the long monthly series. The full table is printed by the script.

| Series | H | Predictor | Train β [90% CI] | n (events) | q_BH | Holdout β [90% CI] | n (events) | Gate verdict |
|---|---|---|---|---|---|---|---|---|
| taxi zone | D | hot_day | +5,458 [+2,889, +8,028] | 365 (37) | 0.006 | −110 [−4,938, +4,718] | 335 | not found (fails holdout) |
| taxi zone | D | rainy_day | +1,206 [−319, +2,731] | 365 (114) | 0.33 | +308 [−1,830, +2,446] | 335 | not found |
| taxi zone | W | rainy_days | +8,516 [+2,367, +14,666] | 52 (46) | 0.094 | **−10,520** [−18,488, −2,552] | 47 | not found (**sign flips**) |
| taxi zone | W | precip > 1 in | +14,860 [−2,360, +32,079] | 52 (18) | 0.30 | −7,721 [−30,015, +14,573] | 47 | not found |
| taxi zone | M | rainy_days | +43,389 [+35,575, +51,203] | **12** (12) | 0.000 | +51,116 [+17,808, +84,423] | **11** | FOUND by the letter |
| taxi zone | M | precip | +64,345 [+27,386, +101,304] | **12** (12) | 0.028 | +149,325 [+50,516, +248,133] | **11** | FOUND by the letter |
| taxi zone | M | precip > 4 in | +187,033 [−13,172, +387,239] | 12 (4) | 0.26 | −61,210 [−203,729, +81,308] | 11 | not found |
| bar | W | snow | +2,058 [+839, +3,278] | 74 (11) | 0.033 | +554 [−583, +1,690] | 69 | not found (fails holdout) |
| bar | M | snow > 2 in | −55,312 [−71,212, −39,411] | 17 (**5**) | 0.000 | −43,803 [−58,560, −29,046] | 15 | not found (only 5 event months) |
| yellow trips | M | precip > 4 in | −2.80% [−4.54, −1.05] | 96 (44) | 0.046 | −2.01% [−4.18, +0.16] | 75 | not found (holdout CI touches 0) |
| yellow trips | M | snow | −0.27%/in [−0.41, −0.13] | 96 (31) | 0.016 | +0.16% [−0.08, +0.40] | 75 | not found (sign flips) |
| yellow fare | M | snow | −0.29%/in [−0.57, −0.01] | 96 (31) | 0.21 | **+0.54%** [+0.32, +0.75] | 75 | not found (sign flips) |
| HVFHV trips | M | snow | −1.51%/in [−2.30, −0.71] | 86 (25) | 0.016 | −0.20%/in [−0.22, −0.18] | 25 (6) | FOUND by the letter |

### Why the 3 letter-passes are not real

- **Taxi zone monthly rainy_days and precip.** There are 12 train and 11 holdout months, against 6 parameters, so residual df is 6 and 5. HAC errors with n = 12 understate the error. With HC3 and a t(df) critical value, both cells' 90% CIs cross 0 on train and on holdout.
  - The size isn't plausible either. +$43k per extra rainy day in a month is ~36× the daily rainy-day effect (+$1.2k).
  - The settleable version (precip > 4 in) is null on train and the wrong sign on holdout.
- **HVFHV snow.** It passes the small-sample check: HC3-t train CI [−2.50%, −0.51%], holdout [−0.34%, −0.06%]. Leave-one-out over the 6 holdout snow months keeps it between −0.18% and −0.25%. But:
  - The train effect comes from the 2015–2019 hyper-growth years. Refit on post-COVID train only (2022-07 to 2024-06, the same design as holdout), it is **+0.50%/in (SE 0.17)**, a significant opposite sign.
  - The holdout effect is ~7× smaller than train.
  - Yellow cabs in the same city and months move the other way (+0.54%/in farebox on holdout).
  - Basis is weak. KXNYCSNOWM settles on Weather Company, not GHCN, and has no trading history. R² of monthly snow total vs the > 4 in flag (Dec–Mar) is 0.54.
  - It's a citywide aggregate, not a business.

### Hedge backtest (taxi zone, monthly, the only $ series with a live monthly contract)

The trade: buy NO on KXRAINNYCM "> 4 in" (taxi earns more in wet months, so dry months hurt).
- Price: 1 − p̂ + $0.02 plus fee, with p̂ = 0.481 (GHCN 2010 to train end). All-in cost $0.556.
- Size: |β| = 187k contracts, from the train fit on the flag itself.
- Over 11 holdout months, the hedge **adds risk**:

| Holdout months | Unhedged | Hedged |
|---|---|---|
| SD of raw revenue | $219k | $224k |
| SD of residual vs train baseline | $207k | $234k |
| Worst month (residual) | −$227k | −$331k |

## Variance share at each horizon

These are for the weather block (rainy days, precip, hot days, CDD, snow; daily: the five daily versions).

| Series | Horizon | n | Partial R² (in-sample, after calendar) | Share of total variance | Out-of-sample R² gain on holdout |
|---|---|---|---|---|---|
| taxi zone | daily | 700 | 0.072 | 0.051 | +0.059 |
| taxi zone | weekly | 99 | 0.025 | 0.015 | **−1.41** |
| taxi zone | monthly | 23 | 0.461 | 0.336 | n/a (12 train months cannot fit 10 terms) |
| bar | weekly | 143 | 0.014 | 0.011 | −0.10 |
| bar | monthly | 32 | 0.380 | 0.355 | −0.48 |
| yellow trips | monthly | 171 | 0.084 | ~0 (year FE dominate) | n/a (year FE) |
| yellow fare | monthly | 171 | 0.081 | 0.003 | n/a |
| HVFHV trips | monthly | 111 | 0.183 | 0.006 | n/a |

How to read it:
- Weekly aggregation does not raise the share; partial R² is 2.5% for taxi and 1.4% for the bar.
- The big monthly in-sample numbers (0.46, 0.38) come from fitting 5 weather terms plus controls to 23–32 points. Out of sample, they make prediction **worse**, by 10% to 141%.
- Only the long monthly series have enough n to trust. There, weather explains ~8% of the residual after month and year effects, and essentially 0% of total variance.
- One side note: daily taxi with all five weather variables (incl. snow and CDD) gains +5.9% out of sample, more than the ~1% round 1 found with rain + hot flags alone. Most of it looks like the 2026 winter snow days (holdout snow β −$3.4k/in, CI [−4.2k, −2.7k]). Train has only 13 snow days and a null there, so it doesn't count as found.

## Bottom line

- **Contracts:** monthly NYC rain (KXRAINNYCM) is live and settles on the same CLI report as the daily contracts. Weekly rain and monthly snow are new and settle on Weather Company data. No monthly or weekly temperature market is listed.
- **Signal:** longer horizons don't rescue the result. Weekly effects flip sign between years, as daily ones did. Monthly series are too short (taxi 23, bar 32 months) to fit seasonality and weather together. The long citywide TLC series (171 months) show small effects (≤ 3% of a month's trips) that don't replicate.
- **Desk:** it should decline monthly rain hedges too. The one we could backtest raised holdout SD by 2–13% and deepened the worst month by $104k.

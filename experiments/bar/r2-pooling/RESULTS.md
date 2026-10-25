# R2 pooling: a "typical venue near MSG" exposure (class rating)

**Question.** One venue's series is too noisy to measure by itself. Does pooling all 358 eligible Dewey venues near MSG
into one panel give a category-level % effect for rain, hot (>85F), home_game or home_win that is real, meaning it holds
on train and also on an independent holdout fit?

**Data.** The same 358 eligible venues as `venues/venue_scan.py` (ZIPs 10001/10119/10121; NAICS 722511/722513/722410;
coverage of at least 98%; at least 200 visits a week). That gives 130,670 venue-days in train (2024-10-01..2025-09-30,
365 days) and 119,923 in holdout (2025-10-01..2026-08-31, 335 days). The calendar, weather (MSG grid) and schedule come
from `features.build("restaurant")`. Central Park settlement flags come from `features.add_settlement(strike=85)`.

**Method.**
- **Panel model:** log(visits+1) ~ venue FE (within-demeaned) + DOW + season k=1,2 + holiday + msg_event + home_game +
  home_win + rain + hot. Standard errors are clustered by date. Every regressor is date-level, so the effective n is the
  number of days (365 / 335), not the number of venue-days.
- **Stricter standard errors:** I also computed Driscoll-Kraay-style errors (Newey-West, 7 lags, on the daily
  cross-venue mean). The gates use the larger of the two standard errors.
- **Same model on other cuts:** each NAICS subgroup, the category total (weighted by visits), and the Central Park
  station flags in place of the MSG-grid flags.
- **Heterogeneity:** for each venue, OLS (HC3) on its log visits *relative to the category mean that day*. This removes
  the shared date shock, so the venue deviations are close to independent. I shrank those deviations with
  DerSimonian-Laird empirical Bayes, and each venue's effect = pooled mean + shrunk deviation, with variance =
  (panel SE)² + posterior variance of the deviation. Train and holdout are fit separately.
- **Multiple testing:** BH 10% across **all 1,454 tests**: 22 aggregate tests plus 358 venues × 4 events.

Script: `pooling.py` (run from backend/, about 6 s). Outputs: `pooling_summary.csv` (aggregates) and `eb_summary.csv`
(shrunken effects per venue, opaque ids only).

**Basis (MSG grid vs Central Park settlement):** rain flags agree on 95.4% of days (corr 0.91), hot>85 flags on 98.7%
(corr 0.95).

## Results: pooled category effects (% change in visits; $ at the demo bar's mean of $8,048/day)

90% CIs use the larger of the two standard errors. "p" is the gate p (the larger of the two). "BH all" is the BH-adjusted
p across all 1,454 tests. "BH agg" is the BH-adjusted p across the 22 aggregate tests only.

| model | event | n tr | train % [90% CI] | p | BH all | BH agg | n ho | holdout % [90% CI] | p | $ bar tr / ho | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pooled, all 358 | rain | 148 | -0.10 [-1.40, +1.22] | 0.90 | 1.00 | 0.94 | 158 | -0.90 [-2.47, +0.70] | 0.36 | -$8 / -$72 | NOT FOUND |
| pooled, all 358 | hot >85 | 55 | **+3.28 [+1.31, +5.29]** | 0.006 | 0.36 | 0.04 | 45 | +0.66 [-1.03, +2.39] | 0.52 | +$264 / +$53 | NOT FOUND (no holdout) |
| pooled, all 358 | home_game | 90 | **-2.88 [-5.26, -0.43]** | 0.054 | 0.36 | 0.21 | 88 | **-3.70 [-6.85, -0.46]** | 0.061 | -$231 / -$298 | NOT FOUND (BH; not settleable) |
| pooled, all 358 | home_win | 49 | -1.97 [-4.66, +0.79] | 0.24 | 0.36 | 0.39 | 51 | +0.77 [-2.36, +4.00] | 0.69 | -$159 / +$62 | NOT FOUND |
| pooled, Central Park flags | rain | 145 | -0.00 [-1.27, +1.28] | 1.00 | 1.00 | 1.00 | 153 | -1.04 [-2.49, +0.43] | 0.24 | -$0 / -$84 | NOT FOUND |
| pooled, Central Park flags | hot >85 | 53 | **+3.49 [+1.45, +5.58]** | 0.005 | 0.36 | 0.04 | 38 | -0.13 [-1.72, +1.48] | 0.89 | +$281 / -$11 | NOT FOUND (no holdout) |
| bars only (722410, 61) | rain | 148 | -1.14 [-2.70, +0.45] | 0.24 | 0.36 | 0.39 | 158 | -2.81 [-4.77, -0.80] | 0.022 | -$91 / -$226 | NOT FOUND (train) |
| bars only (722410, 61) | hot >85 | 55 | +2.31 [-0.57, +5.27] | 0.19 | 0.36 | 0.39 | 45 | -1.52 [-3.71, +0.72] | 0.26 | +$186 / -$122 | NOT FOUND |
| bars only (722410, 61) | home_game | 90 | -1.09 [-3.89, +1.80] | 0.53 | 0.71 | 0.73 | 88 | -0.94 [-5.23, +3.54] | 0.73 | -$88 / -$75 | NOT FOUND |
| bars only (722410, 61) | home_win | 49 | -1.21 [-3.99, +1.64] | 0.48 | 0.65 | 0.71 | 51 | -0.53 [-3.76, +2.81] | 0.79 | -$98 / -$42 | NOT FOUND |
| full-service (722511, 225) | hot >85 | 55 | +2.66 [+0.58, +4.78] | 0.035 | 0.36 | 0.19 | 45 | +1.41 [-0.56, +3.42] | 0.24 | +$214 / +$114 | NOT FOUND |
| full-service (722511, 225) | home_game | 90 | -3.03 [-5.66, -0.32] | 0.066 | 0.36 | 0.21 | 88 | -4.37 [-8.11, -0.48] | 0.065 | -$244 / -$352 | NOT FOUND (BH) |
| limited-service (722513, 72) | hot >85 | 55 | +6.10 [+2.98, +9.32] | 0.001 | 0.36 | 0.02 | 45 | +0.20 [-2.53, +3.01] | 0.91 | +$491 / +$16 | NOT FOUND (no holdout) |
| category total (visits-wtd) | home_game | – | -3.62 [-6.75, -0.38] | 0.067 | 0.36 | 0.21 | – | -3.44 [-7.46, +0.77] | 0.18 | -$291 / -$277 | NOT FOUND |
| category total (visits-wtd) | rain / hot / home_win | – | all CIs include 0 | ≥0.18 | – | – | – | all CIs include 0 | ≥0.21 | – | NOT FOUND |

The remaining subgroup rows (722511/722513 rain and home_win, 722513 home_game) all have CIs that include 0, or fail the
holdout check; see `pooling_summary.csv`. Across all 22 aggregate tests, **0 are FOUND**.

## Heterogeneity (empirical Bayes, 358 venues × 4 events)

| event | train tau (pp) | I² | Q p | holdout tau (pp) | I² | corr(venue dev, train vs holdout) | venues with shrunk deviation ≠ 0 (tr / ho) | FOUND |
|---|---|---|---|---|---|---|---|---|
| rain | 0.75 | 0.11 | 0.05 | 0.00 | 0.00 | +0.18 | 0 / 0 | 0 |
| hot | 2.14 | 0.31 | <0.001 | 0.69 | 0.04 | **-0.15** | 6 / 0 | 0 |
| home_game | 1.50 | 0.11 | 0.06 | 1.69 | 0.09 | +0.07 | 0 / 0 | 0 |
| home_win | 0.00 | 0.00 | 0.76 | 1.25 | 0.07 | -0.15 | 0 / 0 | 0 |

The venues barely differ beyond noise. For rain and home_win the between-venue variance is about 0, so every venue
shrinks onto the category mean. For hot, train shows real dispersion (I² 0.31), but it vanishes in holdout, and the venue
ranking flips sign (corr -0.15). No venue's shrunken deviation is nonzero in both periods, and no venue passes BH. About
40 venues have a shrunken home_game effect that excludes 0 in each period, but that comes from the pooled mean, not from
the venue (no venue has a nonzero deviation). Even so, none passes BH across the 1,454 tests.

**Test count: 1,454** (22 aggregate + 1,432 venue-event). **Survivors of BH 10%: 0.**

## Verdict per candidate

- **rain (KXRAIN): NOT FOUND.** The pooled effect is about 0% on train (-0.1%) and -0.9% on holdout, and the same with
  Central Park flags. Bars-only rain is -2.8% on holdout (p 0.02) but is null on train, and I did not tune on holdout.
- **hot >85 (KXHIGHNY): NOT FOUND.** It is significant on train (+3.3% overall, +6.1% limited-service, BH-agg 0.02–0.04),
  but it collapses on holdout (+0.7%, CI includes 0; with station flags -0.1%). This is the same pattern as the taxi in
  round 1. The 55 train hot days all fall in one summer, so the effect is confounded with that summer's level relative
  to the k=2 seasonal fit.
- **home_win (Knicks/Rangers winner): NOT FOUND.** -2.0% on train, +0.8% on holdout, both CIs include 0. Pooling 358
  venues does not change the round 1 venue-scan result.
- **home_game: NOT FOUND.** This is the closest call, and it is not hedgeable anyway. It is the only effect that
  replicates. Visits are about 3% *lower* on MSG game days in both periods: -2.9% [-5.3, -0.4] on train and -3.7%
  [-6.8, -0.5] on holdout. Both 90% CIs exclude 0 even with the stricter standard errors, and the full-service subgroup
  and category total point the same way. It fails BH: 0.36 across all tests, 0.21 across the aggregates, and 0.108 even
  across only the 4 primary pooled tests. It also fails the basis criterion: a home game is on the schedule in advance,
  so no Kalshi contract settles on it. It belongs in the baseline (where `exposure.py` already treats it as a control), not
  in a hedge.

**Overall: NOT FOUND.** Pooling removes the venue-level noise, but the effective sample is still about 350 days per
period. The shared date shock (commuter/transit traffic and Dewey panel drift) does not average out across venues, so
the pooled standard errors are only somewhat smaller than for a single venue (roughly 0.8pp for rain). At that precision,
rain and home_win are null, and hot does not replicate. No hedge backtest was run because nothing passed the gates.

**What the desk can use.** The class-rating idea works as a *prior*, not as a hedge signal. For a small venue near MSG,
the defensible "typical" exposures are: rain ≈ 0% (90% CI about ±1.3% in train, so under ±$105/day at $8k/day), home_win ≈ 0, and hot not
established. That supports declining to hedge, now backed by 358 venues instead of one. A useful demo line: "pooling 358
venues pins the rain exposure of a typical bar near MSG within ±1.3% of revenue, and that is too small to be worth a
contract." The one stable effect, -3% on game days, is a forecastable baseline shift, not an insurable risk.

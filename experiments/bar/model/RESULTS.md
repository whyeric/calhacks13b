# Model specification: is the bar's effect hidden by a weak model?

**Question.** The bar's holdout R2 is 0.046 and it has no hedgeable exposure. Would a better
specification surface one, and should production change?

**Method.** `specs.py` refits the `fit_exposures` design (const, DOW, k=1,2 harmonics, controls,
HC3, hot = tmax > 85F) on `features.build("restaurant")` (the bar, p_afa556030e60) and
`features.build("taxi")`, train = first 365 days, holdout = the remaining 335. It compares
8 variants of that design. R2 is always computed on the $ scale: log uses Duan smearing, and the
ratio spec multiplies back by its baseline. Log and ratio effects are converted to $ at the train
mean. The "ratio" spec divides revenue by the mean of the previous 4 same-weekday days
(lags 7..28), which drops the first 28 days. HAC is Newey-West with 7 lags. 90% CI is ±1.645 se;
`*` marks a CI that excludes 0. Run: `cd backend && .venv/bin/python ../experiments/bar/model/specs.py`.

Multiple comparisons: 9 specs x 3 events x 2 businesses = 54 CIs, plus one extra months+HAC run.
At 90% about 5 of them would exclude 0 by chance. The specs are also highly correlated with each
other, so treat this as a robustness check and not as a search for a spec that wins.

## Results
## restaurant  (train mean $8,048)
| spec | R2 train | R2 holdout | resid AC1 | home_win | rain | hot (>85F) |
|---|---|---|---|---|---|---|
| 0 current (DOW+k2, HC3) | 0.158 | 0.046 | 0.04 | -2,026 [-4,351, 299] n=49 | -345 [-992, 301] n=148 | -118 [-1,205, 969] n=55 |
| 1 month dummies | 0.185 | 0.031 | 0.01 | -1,919 [-4,227, 389] n=49 | -310 [-963, 342] n=148 | -971 [-2,282, 339] n=55 |
| 2 harmonics k=4 | 0.180 | 0.038 | 0.02 | -2,040 [-4,452, 372] n=49 | -288 [-945, 368] n=148 | -1,071 [-2,470, 328] n=55 |
| 3 + linear trend | 0.172 | -0.813 | 0.03 | -2,038 [-4,349, 273] n=49 | -228 [-846, 390] n=148 | -398 [-1,523, 726] n=55 |
| 4 log(revenue) | 0.148 | 0.071 | 0.05 | -1,045 [-2,019, 87] n=49 | -219 [-693, 287] n=148 | +49 [-745, 930] n=55 |
| 5 ratio to 4-wk same-DOW mean | -0.172 | -0.087 | 0.08 | -1,051 [-2,414, 313] n=46 | +85 [-614, 784] n=145 | -767 [-1,948, 415] n=55 |
| 6 current, HAC(7) SEs | 0.158 | 0.046 | 0.04 | -2,026 [-4,255, 203] n=49 | -345 [-941, 251] n=148 | -118 [-1,196, 960] n=55 |
| 7 ratio + HAC(7) | -0.172 | -0.087 | 0.08 | -1,051 [-2,382, 281] n=46 | +85 [-551, 721] n=145 | -767 [-1,981, 447] n=55 |
| 8 months + trend + HAC(7) | 0.185 | -0.059 | 0.01 | -1,919 [-4,119, 280] n=49 | -310 [-903, 282] n=148 | -970 [-2,367, 427] n=55 |

## taxi  (train mean $67,442)
| spec | R2 train | R2 holdout | resid AC1 | home_win | rain | hot (>85F) |
|---|---|---|---|---|---|---|
| 0 current (DOW+k2, HC3) | 0.281 | 0.238 | 0.49 | +522 [-2,610, 3,654] n=49 | +2,212 [533, 3,890] n=148 * | +3,967 [1,281, 6,654] n=55 * |
| 1 month dummies | 0.461 | 0.311 | 0.35 | +1,581 [-1,147, 4,309] n=49 | +128 [-1,453, 1,709] n=148 | +3,332 [830, 5,833] n=55 * |
| 2 harmonics k=4 | 0.355 | 0.232 | 0.43 | +1,258 [-1,641, 4,158] n=49 | +1,575 [-60, 3,211] n=148 | +4,887 [2,125, 7,650] n=55 * |
| 3 + linear trend | 0.341 | -1.678 | 0.44 | +580 [-2,477, 3,637] n=49 | +1,633 [25, 3,241] n=148 * | +5,346 [2,591, 8,101] n=55 * |
| 4 log(revenue) | 0.280 | 0.232 | 0.46 | +626 [-2,527, 3,931] n=49 | +2,265 [447, 4,133] n=148 * | +4,281 [1,276, 7,418] n=55 * |
| 5 ratio to 4-wk same-DOW mean | 0.234 | 0.068 | 0.51 | +1,633 [-2,085, 5,351] n=46 | +1,817 [-12, 3,645] n=145 | +1,667 [-1,205, 4,540] n=55 |
| 6 current, HAC(7) SEs | 0.281 | 0.238 | 0.49 | +522 [-2,661, 3,704] n=49 | +2,212 [709, 3,715] n=148 * | +3,967 [1,129, 6,806] n=55 * |
| 7 ratio + HAC(7) | 0.234 | 0.068 | 0.51 | +1,633 [-1,583, 4,849] n=46 | +1,817 [259, 3,375] n=145 * | +1,667 [-1,530, 4,865] n=55 |
| 8 months + trend + HAC(7) | 0.461 | 0.323 | 0.35 | +1,581 [-1,276, 4,439] n=49 | +128 [-1,303, 1,559] n=148 | +3,331 [1,264, 5,398] n=55 * |

Extra run, months + HAC without trend: bar holdout R2 0.031 with nothing significant; taxi holdout
0.311, rain +128 [-1,303, 1,559] (not significant), hot +3,332 [1,266, 5,398] (significant).

## Findings
1. **The bar has no leftover structure for a better model to capture.** Its residual lag-1
   autocorrelation is 0.04 under the current spec. The 0.49 autocorrelation and the month-mean
   residuals are a taxi problem. The bar's residual SD is $4,045 on a mean of $8,048 (CV about 50%),
   which is noise in the Dewey visit series, not missing seasonality. Month dummies and k=4 add
   about 0.02-0.03 of train R2 and *lower* holdout R2 (0.031 and 0.038 vs 0.046), i.e. they overfit.
2. **No spec makes any bar exposure significant.** home_win is negative in every spec, from -1,045
   to -2,040, and every CI crosses 0. The CI that comes closest is log's [-2,019, +87]. A Knicks win
   *lowering* traffic at a bar across from MSG is not plausible, which also points to noise.
   Rain and hot flip sign across specs.
3. **The linear trend is harmful.** It extrapolates a one-year slope into the holdout:
   holdout R2 is -0.81 for the bar and -1.68 for taxi.
4. **The ratio baseline is worse.** On a series this noisy, a trailing 4-point mean is itself noisy,
   so bar R2 goes negative. It also mechanically halves the home_win estimate.
5. **HAC barely changes the CIs.** Even for taxi, where residual AC is 0.49, the event flags are
   close to serially independent, so HAC(7) SEs are within about 10% of HC3 and sometimes smaller.
   Point estimates do not change.
6. **Side finding (important for taxi): taxi rain +$2,212 is fragile.** With month dummies it falls
   to +$128 (not significant). With k=4 it is +$1,575 (not significant). Month dummies also give
   the best taxi holdout R2 (0.311 vs 0.238) and cut residual AC from 0.49 to 0.35. Across train
   months, the rain rate correlates +0.31 with mean revenue. So in the current spec, part of the
   taxi "rain effect" is probably within-season variation that 2 harmonics don't absorb.
   Taxi hot (>85F) survives every spec except ratio.

## Recommendation for production
Keep the current mean design (DOW + k=2 harmonics + controls). **Switch the SEs from HC3 to HAC
(Newey-West, maxlags=7).** The change is in `backend/app/stats/exposure.py`: `COV_TYPE = "HAC"`,
and `fit_ols` calls `.fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)`. This leaves
`ExposureResult.cov_type` reporting "HAC".

Why: autocorrelated residuals (taxi 0.49) make HC3 formally invalid, and HAC fixes that at almost no
cost in power while leaving every point estimate and R2 unchanged, so the demo numbers stay stable.
Month dummies predict taxi best out of sample, but they would remove the taxi rain hedge. With one
training year they use 11 parameters on 12 data points of seasonality, and they hurt the bar's
holdout. Don't adopt them before there is more than one train year. Do surface the fragility,
though: an optional robustness line in the model check ("rain effect under month dummies:
+$128, n.s.") would be honest. Log, ratio and trend should not ship.

**Verdict for the bar:** the effect is not hidden by a weak model. The data is too noisy
(CV about 50%, panel-visit estimates x $35) to resolve a game-night effect, and the point estimate
has the wrong sign. Model tweaks will not make it hedgeable. It needs a different or cleaner revenue
signal.

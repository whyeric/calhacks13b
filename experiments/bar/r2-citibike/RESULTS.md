# R2: bike ridership vs Central Park weather

**Question.** Does a Kalshi-settleable NYC weather event (Central Park rain, tmax vs a strike,
cold, snow) move daily bike-share demand, and does the effect hold up on a later holdout year?

**Data (all public).**
- **jc**: Citi Bike Jersey City/Hoboken trips per day from `s3://tripdata` JC monthly zips,
  counted by start date. Mean is about 2,790 trips a day.
  The NYC-system zips are about 20 GB for 2023 to 2025, and S3 gave this machine about 5 MB/s
  (over an hour), so the NYC system itself is **not** used.
- **dot**: NYC DOT automated bike counters (NYC Open Data `uczf-rk3c`), summed over a fixed
  panel of 14 counters that report on at least 95% of days in both periods. Only days where
  all 14 counters reported are kept. This stands in for Manhattan and East River ridership and
  averages about 32k counts a day.
- **Weather**: GHCN-Daily `USW00094728` (Central Park). This is the station KXRAIN and KXHIGHNY
  settle on. TMAX is converted to whole °F and rain uses the recorded 0.01 in step (a trace
  counts as 0), so each flag *is* the settlement flag. Basis R² = 1, apart from possible
  rounding differences between °C and °F.
- **Periods**: train is 2023-01-01..2024-12-31 and holdout is 2025-01-01..2025-12-31. Each is
  fitted independently. The holdout was not used for any choice.

**Method.** For each (series, event) pair:
`trips ~ const + DOW + season(k=1,2) + federal holiday + linear trend + β·event`, using
`build_design` from `app/stats/exposure.py` with HAC(7) errors and z = 1.645. There is one
event per regression. That gives 7 events × 2 series = **14 tests**. Benjamini-Hochberg at 10%
is applied over all 14, separately to the train p-values and the holdout p-values. A result
counts only if it passes both. Revenue is trips × **$4.00 per trip**, an assumed blended
member/casual rate. For the dot counters, $ is only a scale, not revenue.

Run it with `cd backend && .venv/bin/python ../experiments/bar/r2-citibike/citibike_weather.py`.
The cache lives in the scratchpad `r2-cache/`.

## Results (effect in trips/day, 90% CI)

| series | event | n tr | train β [90% CI] | n ho | holdout β [90% CI] | BH tr | BH ho | verdict |
|---|---|---|---|---|---|---|---|---|
| jc | rain ≥ 0.01 in | 248 | −550 [−648, −453] | 121 | −476 [−571, −382] | <1e-4 | <1e-4 | **FOUND** |
| jc | rain ≥ 1 mm | 207 | −641 [−748, −535] | 96 | −549 [−656, −443] | <1e-4 | <1e-4 | **FOUND** |
| jc | tmax > 80°F | 152 | +289 [+163, +414] | 81 | +471 [+342, +600] | 0.0002 | <1e-4 | **FOUND** |
| jc | tmax > 85°F | 74 | +108 [−6, +222] | 37 | +43 [−94, +180] | 0.15 | 0.60 | NOT FOUND |
| jc | tmax > 90°F | 24 | +8 [−126, +142] | 10 | +52 [−72, +175] | 0.92 | 0.53 | NOT FOUND |
| jc | tmax < 40°F | 40 | −522 [−696, −348] | 50 | −290 [−409, −171] | <1e-4 | 0.0001 | **FOUND** |
| jc | snow ≥ 0.1 in | 12 | −603 [−809, −397] | 14 | −492 [−657, −326] | <1e-4 | <1e-4 | **FOUND** |
| dot | rain ≥ 0.01 in | 232 | −6,906 [−8,030, −5,782] | 109 | −7,237 [−8,622, −5,851] | <1e-4 | <1e-4 | **FOUND** |
| dot | rain ≥ 1 mm | 193 | −7,933 [−9,088, −6,778] | 85 | −8,323 [−9,856, −6,790] | <1e-4 | <1e-4 | **FOUND** |
| dot | tmax > 80°F | 142 | +2,525 [+679, +4,370] | 81 | +4,441 [+2,269, +6,612] | 0.034 | 0.001 | **FOUND** |
| dot | tmax > 85°F | 69 | +870 [−678, +2,419] | 37 | −1,785 [−3,738, +169] | 0.38 | 0.16 | NOT FOUND |
| dot | tmax > 90°F | 20 | −1,064 [−2,767, +638] | 10 | −2,685 [−4,240, −1,130] | 0.35 | 0.006 | NOT FOUND (train CI spans 0) |
| dot | tmax < 40°F | 30 | −6,536 [−8,863, −4,208] | 34 | −3,049 [−4,539, −1,559] | <1e-4 | 0.001 | **FOUND** |
| dot | snow ≥ 0.1 in | 11 | −6,284 [−8,903, −3,666] | 9 | −5,309 [−7,361, −3,257] | 1e-4 | <1e-4 | NOT FOUND (9 holdout days < 10) |

**9 of 14 pass every criterion.** In relative terms, rain ≥ 0.01 in cuts ridership by about
20% in JC (−550 of 2,790) and about 21% on the DOT panel (−6.9k of 32k). The effect shows the
same size in both series and both years. Unlike the taxi result in round 1, it replicates
almost exactly. In dollars, the JC rain effect is **−$2,202/day** in train and −$1,906 in
holdout.

## Hedge backtest (2025 holdout, USD/day, JC, $4/trip)

The hedge is sized as |β_train| contracts on the side that pays when revenue drops. The price
is the train frequency, plus $0.02, plus a 0.07·p·(1−p) fee. "Residual" is revenue minus the
train controls-only model's prediction, i.e. the weather surprise once season and DOW are
removed. Residual is the relevant view, because raw SD is mostly seasonality, which no daily
contract can hedge.

| event | contracts | raw SD → hedged | resid SD → hedged | resid 5th pct → hedged | cost/day |
|---|---|---|---|---|---|
| rain ≥ 0.01 in (buy YES) | 2,202 | 3,822 → 3,723 | 2,054 → **1,861 (−9%)** | −4,829 → **−4,417** | $97 |
| rain ≥ 1 mm (buy YES) | 2,565 | 3,822 → 3,691 | 2,054 → **1,816 (−12%)** | −4,829 → **−4,383** | $141 |
| tmax > 80 (buy NO) | 1,156 | 3,822 → 3,620 | 2,054 → 2,020 | −4,829 → −5,119 (worse) | $52 |
| tmax < 40 (buy YES) | 2,088 | 3,822 → 3,489 | 2,054 → 2,037 | −4,829 → −4,645 | −$120* |
| snow (buy YES) | 2,412 | 3,822 → 3,687 | 2,054 → 2,017 | −4,829 → −4,588 | $1 |

\*There were 50 cold days in 2025 against a 5.5% train frequency, so this "profit" comes from a
cold year and is not edge.

On the DOT panel, the rain ≥ 1 mm hedge cuts residual SD by 13% (28.3k → 24.7k) and raises the
5th percentile from −64.7k to −53.4k. The rain hedge is the clear winner: it lowers SD and
lifts the bad-day tail in both series. The hot-80 hedge lowers SD slightly but makes the tail
worse, so it is not worth selling.

## Verdict

- **FOUND: rain (both definitions) → bike demand down about 20%.** It passes train, holdout,
  BH (14 tests) and basis (it is the settlement flag itself), and the hedge works out of
  sample. This is the strongest candidate so far.
- FOUND but less useful as a hedge: cold < 40°F, snow (JC only, few days), and tmax > 80°F (a
  positive exposure).
- NOT FOUND: tmax > 85 and > 90. The positive "warm" effect saturates, and the >90 effect turns
  negative only in 2025 on the DOT panel.

**Caveats.** The JC data is Jersey City/Hoboken Citi Bike, not the NYC system. Weather there is
nearly the same as Central Park, but the basis is not exactly 1 for that business. $4/trip is
assumed. HAC(7) is the only error spec tried. Pricing at the train frequency ignores that
Kalshi prices on the day's forecast: on a forecast-rain day the YES price will be near 1, so a
real hedge has to be bought days ahead or kept as a standing position.

**Demo idea.** Show a "Hoboken bike-rental shop" with about 2,800 rides a day at $4. Show the
rain exposure of −$2,200 on rain days, with the 2023-24 CI next to the 2025 CI side by side.
Then show the 2025 residual-revenue chart with and without a standing KXRAIN YES position of
about 2,200 contracts. The worst-5% day improves by about $400, at about $100 a day.

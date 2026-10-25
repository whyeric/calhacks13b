# R6 gas: do gasoline prices move bike-share and rideshare demand?

## Mechanism (written before any fit)
Crude oil → local retail gasoline price → marginal cost of driving a private car → some trips switch mode.
Predicted signs, fixed in advance:
- **Bike share (Divvy Chicago, Austin B-cycle, Citi Bike Jersey City): elasticity > 0.** Dearer gas pushes marginal drivers to bikes. Subscribers (commuters) should respond more than casual riders.
- **NYC FHV (Uber/Lyft) trips: ambiguous; leaning < 0.** Demand rises as people leave cars, but supply falls: drivers pay for fuel, and the 2022 fuel surcharges and TLC pay-rate bumps raise fares.
- **NYC FHV fare per trip: > 0.** This is the cost pass-through.
- **NYC yellow trips: ambiguous** (same two forces).

Pre-registered regressor: log of the EIA weekly retail regular price for the matching local area, Monday of the trip week (weeks run Mon–Sun). Local means Chicago city for Divvy, Texas for Austin (Kalshi lists Texas, not Austin), and NYC for the NYC series. The second regressor is the US national price, which is what KXAAAGASW/M settle on (via AAA).

## Answer: NOT FOUND (0 of 32)
- No gas-price elasticity passes train, then holdout, then BH.
- **Divvy:** the predicted positive bike-share effect shows up in 2014–15 (+0.66 to +3.0) and **flips sign** in 2016–17 (−0.28 to −0.54).
- **FHV fare per trip:** the one strong train result (+0.14 elasticity, q = 0.001) is fuel cost passing into fares during the 2022 spike. It is gone in 2024–25 (−0.01 [−0.11, +0.09]).
- **Hedging:** a bike-share operator or rideshare fleet cannot hedge *demand* with KXAAAGAS, because the sign of the exposure is not stable. A fleet's *fuel bill* is a direct, linear gas exposure and can be hedged against the US contract, with basis R² ≈ 0.6–0.8 monthly (see the basis section).

## Data
- **Bike share:**
  - **Divvy Chicago:** Kaggle `archive (2).zip` → `data.csv`, the "cleaned" file. It has 9.50M trips, 2014-01-01..2017-12-31, and is 99.98% Subscriber, so there is no casual/subscriber split.
  - **Austin B-cycle:** `archive (3).zip`, 649k trips, 2013-12..2017-07. All of 2016-04 and 2016-12 is missing, so those weeks are dropped.
  - **Processing:** both were aggregated with duckdb to day plus distinct active stations per month. The extracts were deleted, and only `r2-cache/r6gas_*_daily.parquet` remains.
  - **Citi Bike Jersey City:** daily 2023–2025 from r2-citibike.
- **NYC TLC:** daily HVFHV and yellow 2022–2025 from r2-taxi (`r2-cache/tlc/`). The r2-taxi yellow data-gap rule is applied. Series: FHV trips, FHV $/trip ((fare + tips) / trips), yellow trips.
- **Gas:** EIA weekly retail regular, all formulations (`hist_xls/<series>w.xls`; dated Monday):
  - US `EMM_EPMR_PTE_NUS_DPG`
  - Chicago `…_YORD_DPG`
  - Texas `…_STX_DPG` (EIA has no Austin series)
  - NYC `…_Y35NY_DPG`
  - Also downloaded but unused: Midwest, Gulf Coast, NY State, Houston. The brief's `YCHI` code returns 404, and `YORD` is EIA's Chicago series.
  - Range: Chicago went from $4.09 (2014 max) to $1.56 (2016 min), and NYC from $4.98 (2022 max) to $2.81 (2025 min).
- **Weather (NOAA GHCN):** Chicago Midway USW00014819, Austin Bergstrom USW00013904, Central Park USW00094728. Weekly mean tmax and tmax², rain days (≥ 0.01 in), total precip, total snow.
- **Kalshi:**
  - The **KXAAAGASW** (weekly) and **KXAAAGASM** (month-end) contracts settle on the AAA US average. The rule reads "If average regular gas prices for United States are strictly greater than $X on <date> according to AAA → Yes", with strike ladders $0.01–0.10 apart.
  - State daily contracts also exist: **KXAAAGASDIL / DTX / DNY**. So do KXAAAGASMTX (Texas monthly), KXAAAGASMAXM/MINM, and others.
  - The API only returns settled history from 2026-08 on, so no historical contract prices are available for a backtest.

## Method
- **Model:** weekly (Mon–Sun, full weeks only). y = log(weekly trips) or log($/trip), regressed on log(gas) + weather + federal-holiday count, plus log(active stations that month) for the bike systems. HAC with 6 lags, z = 1.645.
- **Three FE specs:**
  - **A:** month-of-year + year FE
  - **B:** year-month FE (identifies only within-month gas moves)
  - **C:** 52-week log differences (YoY), with a constant
- **Two regressors each:** local gas and US gas.
- **Train → holdout, refit independently:**
  - Divvy and Austin: 2014–15 → 2016–17
  - TLC: 2022–23 → 2024–25
  - Citi Bike JC: 2023 → 2024–25 (no spec C, because it needs a prior year)
- **Tests:** 7 units, 32 in all, with BH at 10% on the train p-values. I first ran Divvy subscriber and customer splits too. They were dropped before any interpretation because subscriber equals total and customer is empty.
- **Placebo:** gas 4 weeks ahead, spec A, local gas, both alone and jointly with the current price. The joint lead coefficient should be ~0.
- `tr_sdx`/`ho_sdx` in `results.csv` is the SD of log gas left after the FE and controls, i.e. the identifying variation. It is 2–6 log points in specs A/B and about 2× smaller in the holdouts, so all elasticities are extrapolated from small moves.

## Results (elasticity, CI90; full grid in `results.csv`, `output.txt`)
| unit | gas | spec | train β [CI90] | n | holdout β [CI90] | n | BH q | verdict |
|---|---|---|---|---|---|---|---|---|
| divvy_trips | chi | A | +0.66 [+0.06, +1.26] | 102 | **−0.28 [−0.48, −0.09]** | 103 | 0.14 | NOT FOUND (flips) |
| divvy_trips | chi | B | +1.06 [+0.29, +1.83] | 102 | −0.54 [−1.02, −0.06] | 103 | 0.071 | NOT FOUND (flips) |
| divvy_trips | chi | C | −0.63 [−1.34, +0.09] | 50 | −0.09 [−0.25, +0.07] | 51 | 0.24 | NOT FOUND |
| divvy_trips | us | B | +3.00 [+2.15, +3.86] | 102 | −0.34 [−1.33, +0.66] | 103 | 0.000 | NOT FOUND (flips) |
| austin_trips | tx | A | −0.48 [−1.54, +0.59] | 103 | −0.86 [−1.76, +0.04] | 72 | 0.51 | NOT FOUND |
| citibike_jc | nyc | A | +1.36 [−0.27, +2.98] | 52 | +0.14 [−0.18, +0.46] | 104 | 0.24 | NOT FOUND |
| fhv_trips | nyc | A | +0.05 [−0.04, +0.13] | 104 | +0.20 [+0.06, +0.33] | 104 | 0.43 | NOT FOUND |
| fhv_trips | nyc | B | +0.45 [+0.11, +0.80] | 104 | +0.14 [−0.26, +0.54] | 104 | 0.079 | NOT FOUND (holdout null) |
| fhv_usd_per_trip | nyc | A | **+0.14 [+0.08, +0.20]** | 104 | −0.01 [−0.11, +0.09] | 104 | 0.001 | NOT FOUND (holdout null) |
| fhv_usd_per_trip | nyc | B | +0.37 [+0.22, +0.53] | 104 | +0.16 [−0.14, +0.46] | 104 | 0.001 | NOT FOUND (holdout null) |
| fhv_usd_per_trip | nyc | C | +0.11 [+0.04, +0.18] | 52 | −0.05 [−0.13, +0.03] | 52 | 0.046 | NOT FOUND (holdout null) |
| yellow_trips | nyc | A | +0.24 [+0.07, +0.41] | 102 | −0.13 [−0.40, +0.13] | 104 | 0.070 | NOT FOUND (flips) |
| yellow_trips | nyc | C | +0.12 [−0.01, +0.24] | 50 | −0.30 [−0.47, −0.14] | 52 | 0.23 | NOT FOUND (flips) |

**Count:** 32 tests. 14 pass BH on train (q < 0.10): Divvy (chi B, us A, us B), FHV trips (B with both gas series), FHV $/trip (5 of 6; us C has q = 0.101) and yellow trips (A/B with both gas series). **0 replicate.**

**Reading:**
- **Divvy:** the predicted positive bike-share effect only appears where gas is collinear with something else. In 2014–15 the oil crash coincides with a 300 → 470 station expansion, a cold 2014–15 winter and the system maturing. The YoY spec (C), which strips system growth, is already negative on train. Within 2016–17 the sign is negative. **Gas → bike share is not identified with 4 years of weekly data.**
- **FHV fare:** the fare pass-through is real in 2022–23, when gas moved $3.05 → $5.01 and Uber/Lyft added fuel surcharges and the TLC raised driver pay rates. In 2024–25 gas moved within $2.81–3.67 and nothing shows. A pass-through that only shows up in a spike is not a stable linear exposure.

## Placebo (gas 4 weeks ahead; spec A, local gas)
| unit | period | lead alone | joint: current | joint: lead |
|---|---|---|---|---|
| divvy | train | +0.37 [−0.12, +0.86] | +0.64 [+0.07, +1.21] | +0.33 [−0.09, +0.75] |
| divvy | hold | −0.00 [−0.27, +0.26] | −0.33 [−0.59, −0.07] | +0.13 [−0.19, +0.45] |
| austin | hold | **−1.56 [−2.32, −0.81]** | +0.02 [−1.07, +1.11] | **−1.58 [−2.65, −0.51]** |
| fhv_trips | train | −0.05 [−0.12, +0.02] | +0.11 [−0.00, +0.21] | **−0.11 [−0.20, −0.01]** |
| fhv_usd_per_trip | train | +0.10 [+0.02, +0.19] | +0.13 [+0.07, +0.18] | +0.03 [−0.06, +0.12] |
| fhv_usd_per_trip | hold | −0.13 [−0.26, −0.01] | +0.12 [−0.04, +0.28] | **−0.21 [−0.39, −0.03]** |
| yellow_trips | train | +0.06 [−0.11, +0.23] | +0.30 [+0.11, +0.48] | −0.10 [−0.29, +0.10] |

**Placebo verdict:**
- Future gas "predicts" Austin trips (holdout), FHV trips (train) and FHV fares (holdout) as strongly as current gas does. That is the signature of slow-moving confounders (trend, policy, season), not of causation.
- The FHV fare in train is the one place where the joint lead is ~0 and current gas survives, consistent with real 2022 pass-through. It fails holdout anyway.

## Basis: local vs national (the Kalshi contract), and AAA vs EIA
| local vs US (EIA) | weekly Δlog R² | monthly Δlog R² | monthly β | level spread, mean ± sd |
|---|---|---|---|---|
| Chicago, 2014–17 | 0.46 | 0.61 | 1.09 | +$0.14 ± 0.13 |
| Chicago, 2022–25 | 0.51 | 0.79 | 1.20 | +$0.35 ± 0.18 |
| Texas, 2014–17 | 0.82 | 0.93 | 1.12 | −$0.23 ± 0.04 |
| Texas, 2022–25 | 0.65 | 0.86 | 1.13 | −$0.46 ± 0.09 |
| NYC, 2014–17 | 0.68 | 0.81 | 0.89 | +$0.02 ± 0.08 |
| NYC, 2022–25 | 0.66 | 0.78 | 0.95 | −$0.07 ± 0.10 |

- **AAA vs EIA (the settlement source vs our regressor):**
  - **US:** on the 9 settled KXAAAGASW Mondays (2026-08-24..10-19), AAA bracketed from the strike ladder minus EIA is +$0.010 ± 0.009. They are effectively the same series.
  - **State daily:** AAA state minus EIA city/state is +$0.003 ± 0.070 for Illinois vs Chicago (Chicago spikes; Illinois jumped +$0.25 in two days in Oct 2026), +$0.04 ± 0.02 for Texas, and +$0.13 ± 0.02 for NY state vs NYC (a stable level offset).
- **Chicago has the worst basis:** the city price is much spikier than the US price (weekly R² ≈ 0.5). The Illinois daily contract fits it better. Texas tracks the US contract well (monthly R² ≈ 0.9).

## Could a bike-share operator or rideshare fleet hedge with KXAAAGAS?
- **Demand, no.** The elasticity has no stable sign. On Divvy it is +0.66 in one 2-year window and −0.28 in the next. Choosing a side of "US gas above $X" would be a guess, and the hedge would add variance about half the time. There is no FOUND row, so no hedge backtest was run.
- **Rideshare fares, no.** The pass-through appears only in a price spike (2022) and disappears when gas is range-bound.
- **Fuel cost, yes, but that is the obvious exposure, not a chain.**
  - The exposure: a fleet car driving about 1,000 mi/week at 25 mpg burns 40 gal/week, so a $0.50/gal move is $20 per car per week, about $87 per car per month.
  - The trade: buy YES across a strip of KXAAAGASM month-end strikes ($0.05 apart) sized to the gallons.
  - What it pays: a payoff close to linear in the US price, which offsets about R² = 0.78 of the monthly NYC price-change variance (β ≈ 0.95). For Texas it is about 0.86–0.93. For Chicago it is 0.6–0.8, or better with KXAAAGASDIL.
  - Known gaps: the basis between AAA's state and US averages and the city pump price, plus an NY-state-vs-NYC level offset of about $0.13 that is stable, so it doesn't matter for changes.
  - It is a cost hedge on a deterministic quantity, not a statistical exposure, so it needs no regression to justify it.

## Reproduce
From `backend/`: `.venv/bin/python ../experiments/bar/r6-gas/gas.py`. The one-time cache builds are described in the script docstring: EIA xls (parsed with xlrd, installed into `r2-cache/r6gas_pylib`), duckdb aggregation of the two zips, the NCEI Austin GHCN pull and the Kalshi markets pull.

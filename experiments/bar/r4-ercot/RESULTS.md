# R4 ercot: Texas grid load, prices and a small business's power bill on hot days

**Question.** On days when a Kalshi Texas high-temperature contract settles YES (tmax > 95 °F or > 100 °F at the settlement station), do ERCOT load, wholesale prices and a small business's electricity bill go up, in a way that replicates on a later holdout?

**Answer.** **Load: yes, by a wide margin, and it is the most stable weather exposure the project has found.** All 64 tests pass every FOUND criterion. The load and fixed-rate-bill effects (+8–16% per > 95 °F day) hold in every single year from 2019 to 2026. **Prices: they pass, but they are not stable.** The price effect was +$20–60/MWh per hot day through 2023 and has shrunk to roughly $0–8 since 2024. In 2025–26 it is null at HB_NORTH. **The hedge works, but only a little.** A single > 95 °F contract cuts the within-month SD of a fixed-rate bill by 4–6%. The hot dummy explains only 5–15% of within-month variance, while tmax as a whole explains 65–75%, so a ladder of strikes is the obvious next step.

## Data (all public)

- **Load:** ERCOT Native Load by weather zone, hourly, 2019-01-01..2026-09-30 (ercot.com/gridinfo/load/load_hist, yearly xlsx). I use the ERCOT total, COAST (Houston), NCENT (Dallas–Fort Worth) and SCENT (Austin / San Antonio).
- **Prices:** ERCOT Historical DAM Load Zone and Hub Prices (NP4-180-ER, hourly). I use HB_HUBAVG, HB_HOUSTON, HB_NORTH, LZ_AEN (Austin Energy) and LZ_CPS (CPS, San Antonio).
- **Weather:** NOAA GHCN-D TMAX at the stations named in the Kalshi rules:

  | city | station (GHCN id) | Kalshi series |
  |---|---|---|
  | Austin | Bergstrom, CLIAUS (USW00013904) | KXHIGHAUS |
  | Houston | Hobby, CLIHOU (USW00012918) | KXHIGHTHOU |
  | Dallas | DFW, CLIDFW (USW00003927) | KXHIGHTDAL |
  | San Antonio | CLISAT (USW00012921) | KXHIGHTSATX |

- **Demo business:** about 1,370 kWh/day, roughly a 10k sq ft small grocery or cold-storage room. Its hourly kWh follows its zone's load shape, scaled so the train-period mean is 1,370 kWh. Two bills:
  - **billfix:** fixed retail rate, $0.14/kWh × kWh. The business carries quantity risk only.
  - **billidx:** indexed, kWh × (hourly DAM price + $0.06/kWh adder). The business carries quantity × price risk, as a retail power seller does.
- **Other related Kalshi series:**
  - **KXTXERCOTPEAKD:** daily ERCOT peak load above X MW, a direct contract on our `peak_ERCOT` outcome.
  - **KXERCOT{HOU,NORTH,WEST}{W,M}:** weekly and monthly hub price contracts.

## Method

- **Model:** OLS of y on hot (tmax > K at the paired station), day of week, federal holiday and year-month FE, with HAC (7 lags) errors and z = 1.645.
- **Split:** train 2019-01..2023-12 (5 y) and holdout 2024-01..2026-09 (2.75 y), each fit independently. The split, strikes and pairings were fixed before any fit.
- **Variance share:** partial R² of the hot dummy given DOW + holiday + ym FE, which is its share of within-month variance. For comparison, the partial R² of a full tmax linear spline with knots at 50, 65, 80, 90 and 100 °F.
- **Test family: 64 tests**, BH at 10%. The 32 outcome × station pairs are:
  - 4 stations × 3 system outcomes (log ERCOT energy, log ERCOT peak, HB_HUBAVG price).
  - 4 local pairs × 5 outcomes (log zone energy, log zone peak, local hub price, billfix, billidx). The local pairs are COAST/HB_HOUSTON/HOU, NCENT/HB_NORTH/DFW, SCENT/LZ_AEN/AUS and SCENT/LZ_CPS/SAT.

  Each pair is tested at both strikes, K = 95 and 100 °F.
- **Scripts:** `ercot.py` (about 25 s once the xlsx files are cached) and `basis.py`. Outputs: `results.csv`, `backtest.csv`, `output.txt` and `basis_output.txt`. openpyxl is installed into the scratchpad (`r4ercot_pylib`), not into the backend venv.

## Basis: GHCN reproduces Kalshi settlement exactly

`basis.py` recomputes every settled KXHIGH* market (thresholds and brackets) from GHCN TMAX. The Kalshi API returns settled markets for 2026-08-17..2026-10-20.

| series | markets | days | agreement |
|---|---|---|---|
| KXHIGHAUS | 390 | 65 | 100% |
| KXHIGHTHOU | 390 | 65 | 100% |
| KXHIGHTDAL | 390 | 65 | 100% |
| KXHIGHTSATX | 390 | 65 | 100% |

So GHCN TMAX at these stations is the settlement value. The basis is about 1.0 for this window; the agreement is not verified before 2026-08.

## Results (headline subset; all 64 rows are in `output.txt` and `results.csv`)

Effects are % per hot day for log outcomes, $/MWh for prices and $/day for bills. n is the number of event days. Partial R² (pR²) is the hot dummy's share of within-month variance on train / holdout. Every row is FOUND.

| outcome | stn | K | train β [90% CI] (n) | BH q | holdout β [90% CI] (n) | pR² hot tr/ho | pR² tmax spline tr/ho |
|---|---|---|---|---|---|---|---|
| ERCOT energy | DFW | 95 | +9.1% [+8.1, +10.0] (292) | 4e-58 | +7.3% [+6.1, +8.6] (176) | 0.091 / 0.063 | 0.58 / 0.58 |
| ERCOT peak (KXTXERCOTPEAKD) | AUS | 95 | +12.6% [+10.9, +14.2] (359) | 2e-35 | +9.4% [+7.8, +11.0] (236) | 0.088 / 0.094 | 0.58 / 0.61 |
| NCENT energy | DFW | 95 | +14.1% [+12.7, +15.4] (292) | 3e-65 | +12.5% [+10.8, +14.2] (176) | 0.112 / 0.083 | 0.72 / 0.70 |
| COAST energy | HOU | 95 | +8.8% [+7.8, +9.9] (247) | 3e-41 | +7.6% [+6.0, +9.1] (98) | 0.086 / 0.051 | 0.65 / 0.65 |
| SCENT energy | AUS | 95 | +12.5% [+10.9, +14.2] (359) | 4e-35 | +10.3% [+8.8, +11.9] (236) | 0.080 / 0.095 | 0.67 / 0.70 |
| billfix NCENT ($190/day mean) | DFW | 95 | +$32.2 [+29.1, +35.3] (292) | 6e-64 | +$31.5 [+27.4, +35.6] (176) | 0.151 / 0.109 | 0.75 / 0.74 |
| billfix SCENT | AUS | 95 | +$27.4 [+24.0, +30.8] (359) | 2e-39 | +$25.9 [+22.2, +29.6] (236) | 0.104 / 0.112 | 0.70 / 0.72 |
| billfix COAST | HOU | 95 | +$20.1 [+17.7, +22.5] (247) | 1e-42 | +$19.1 [+15.7, +22.6] (98) | 0.123 / 0.074 | 0.67 / 0.66 |
| billfix NCENT | DFW | 100 | +$35.2 [+30.3, +40.0] (106) | 3e-32 | +$23.0 [+18.6, +27.4] (57) | 0.082 / 0.027 | 0.75 / 0.74 |
| HB_NORTH price | DFW | 95 | +$27.2 [+15.6, +38.8] (292) | 1e-4 | +$4.1 [+0.8, +7.4] (176) | 0.000 / 0.001 | 0.21 / 0.36 |
| HB_HOUSTON price | HOU | 100 | +$140.7 [+69.2, +212.3] (35) | 1e-3 | +$20.8 [+11.9, +29.8] (**4**) | 0.001 / 0.002 | 0.31 / 0.45 |
| billidx HB_NORTH | DFW | 95 | +$91.2 [+63.8, +118.5] (292) | 6e-8 | +$30.9 [+23.2, +38.5] (176) | 0.001 / 0.008 | 0.23 / 0.46 |

- **Count:** 64 tests and 64 FOUND. The largest BH q is 0.0025.
- **Caveat:** at Houston Hobby, > 100 °F occurred on only 4 holdout days. Those 8 HOU > 100 rows pass the letter of the rules but are weak evidence.

### Stability by year (> 95 °F, each year fit on its own; descriptive, not in the BH family)

| series | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (to Sep) |
|---|---|---|---|---|---|---|---|---|
| NCENT energy, DFW (%) | +10.6 | +12.6 | +14.8 | +15.3 | +17.5 | +14.8 | +11.3 | +10.7 |
| billfix NCENT, DFW ($) | +24.0 | +28.3 | +33.1 | +35.3 | +41.6 | +35.9 | +28.2 | +28.9 |
| billfix COAST, HOU ($) | +14.7 | +21.2 | +20.2 | +18.1 | +27.1 | +24.7 | +15.9 | +14.7 |
| HB_NORTH price, DFW ($/MWh) | +50.4 | +15.2 | +36.7 | +20.2 | +31.1 (ns) | +7.2 | +0.9 (ns) | −0.3 (ns) |
| HB_HOUSTON price, HOU | +59.8 | +12.7 | +43.7 | +27.4 | +60.7 | +2.3 (ns) | +4.5 (ns) | +6.3 |
| LZ_AEN price, AUS | +27.4 | +7.1 | −7.5 (ns) | +9.1 (ns) | +53.5 | +8.2 | +7.5 | +2.7 (ns) |

**Load and fixed-rate bill.** The 90% CI excludes 0 in all 8 of 8 years, at every station.

**Price.** The hot-day premium has largely disappeared since 2024. That fits the large solar and battery build-out flattening summer afternoon scarcity, though this analysis does not test the cause. A price-hedging customer should not size its hedge from 2019–2023 betas.

## Hedge backtest (holdout 2024-01..2026-09; β from train; buy YES hot at p + $0.02 + fee 0.07·p·(1−p), |β| contracts of $1)

The table uses p = the train frequency for that calendar month. The "within" columns subtract each year-month's mean bill, because no daily contract can hedge the month's level. Bills are $/day.

| bill | stn | K | contracts | SD within: unhedged → hedged | p95 within: unhedged → hedged | mean cost/day |
|---|---|---|---|---|---|---|
| billfix NCENT | DFW | 95 | 32 | 23.42 → **22.12 (−5.6%)** | 35.55 → **31.55 (−11%)** | +$0.82 |
| billfix SCENT | AUS | 95 | 27 | 22.18 → **20.93 (−5.6%)** | 30.40 → **28.46 (−6%)** | +$0.11 |
| billfix SCENT | SAT | 95 | 26 | 22.18 → **20.89 (−5.8%)** | 30.40 → **28.23 (−7%)** | +$0.94 |
| billfix COAST | HOU | 95 | 20 | 16.41 → **15.75 (−4.0%)** | 24.73 → 24.70 (0%) | +$1.54 |
| billfix (all 4) | all | 100 | 14–35 | −0.1% to −1.2% | about 0% | +$0.5–1.5 |
| billidx (all 4) | all | 95 / 100 | 70–333 | +0.1% to **+4.4% (worse)** | mixed, mostly worse | +$0.3–13.2 |

- **Fixed-rate bill at > 95 °F:** the hedge reduces SD and the 95th-percentile bill day at all 4 stations. The cost is $0.1–1.5/day, or 0.05–0.7% of the bill.
- **Indexed bill:** the hedge hurts. The train β (+$70–90/day at > 95, up to +$333 at > 100) was set by the 2019–2023 price premium, which then vanished, so the hedge is far oversized.
- **Flat pricing (p = annual train frequency):** this shows larger raw-SD cuts (for example DFW 45.8 → 38.4). Those come from buying cheap summer insurance at an annual-average price that Kalshi would never offer, so I do not count them.

**Forecast caveat (it matters here).** Kalshi daily high-temperature markets trade on the day's forecast. By the morning of a 98 °F day, the > 95 contract is priced near $0.90, not at the month's 40–60% frequency. A day-ahead hedge therefore covers only forecast error, so the backtest above is an upper bound on what a daily hedge buys. Two hedges a business can actually buy early are untested here:
- **Monthly or weekly ERCOT contracts** (KXERCOT*M/W), whose prices are themselves the risk.
- **KXTXERCOTPEAKD**, which settles directly on the ERCOT peak hour we model. A retail seller could hedge peak-load quantity with it, with no weather basis.

## Verdict per candidate

| candidate | verdict | notes |
|---|---|---|
| ERCOT and zone load (energy and peak) vs tmax > 95 / 100 | **FOUND** (32 / 32) | +4–16% per hot day; stable in 8 of 8 years; hot dummy pR² 5–11% of within-month variance |
| Fixed-rate small-business bill vs tmax > 95 / 100 | **FOUND** (8 / 8) | +$20–35/day on about $190/day; hedge cuts within-month SD 4–6% and p95 by up to 11% at > 95 |
| DAM hub and zone prices vs tmax > 95 / 100 | **FOUND by the rules** (16 / 16), **but unstable** | holdout effect 5–10× smaller than train; null in 2025–26 at North; pR² < 0.5% |
| Indexed (wholesale pass-through) bill | **FOUND by the rules** (8 / 8), **hedge fails** | train-sized hedge is oversized after the price premium collapsed |

## How to demo

- **The customer:** a Dallas small grocery on a fixed-rate plan, about $190/day in power. On any day DFW tops 95 °F, the bill rises by about $32. That is +$32.2 on train (2019–23) and +$31.5 on holdout (2024–26), and it happens in every one of the 8 years.
- **The hedge:** buy 32 YES contracts on KXHIGHTDAL "> 95°". It pays $32 when the bill spikes and costs about $0.82/day net over 2.75 years. It trims the worst-decile days by about 11%.
- **The honest framing:** the dummy explains about 15% of within-month bill variance, while the full temperature curve explains about 75%. The next build is a strike ladder (> 90, > 95, > 100) or a CDD-style monthly hedge. A ladder is the natural product, because Kalshi lists several strikes for each city and day.

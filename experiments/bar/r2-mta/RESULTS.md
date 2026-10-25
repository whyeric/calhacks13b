# R2-MTA: Central Park weather and MSG games vs MTA daily ridership

**Question.** Do Kalshi-settleable NYC events (rain at three thresholds, hot, cold, snow, a Knicks/Rangers home game or win) move daily MTA ridership? Ridership stands in for transit-dependent revenue: fares, and station retail such as the Penn Station shops.

**Data.** All public.
- MTA daily ridership by mode from data.ny.gov `sayj-mze2`. This is the successor to `vxuj-8kew`, which stops on 2025-01-09.
- Central Park weather from NOAA GHCN-D `USW00094728` (PRCP, TMAX, SNOW, trace counted as 0). This is the station and daily record that KXRAIN and KXHIGHNY settle on, so the event flag is the settlement flag (basis R² = 1). For reference, the repo's Open-Meteo "station" series agrees with NOAA on only 88% of rain days (phi 0.74), with tmax correlation 0.993. Use NOAA, not Open-Meteo, for anything rain-related.
- Knicks and Rangers home games from ESPN via `app.data.sports.fetch_games`.
- Train is 2022-01-01 to 2023-12-31 (730 days). Holdout is 2024-01-01 to 2025-12-31 (731 days). 2020–2021 are skipped.

**Method.** One fit per mode and event: log(riders) on `build_design` (const, DOW, season harmonics k=1,2) plus federal holidays (and Dec 24, Dec 31, day after Thanksgiving), a Dec 24–Jan 1 week dummy, a linear trend and the event flag. Errors are HAC (Newey-West, 7 lags), with z = 1.645. Train and holdout are fitted independently. Benjamini-Hochberg at 10% is applied over all **45 tests** (5 modes × 9 events), separately to the train p-values and to the holdout p-values. FOUND requires both q ≤ 0.10, plus a train CI that excludes 0 with at least 10 event days, and a holdout CI that excludes 0 with the same sign. Nothing was tuned after looking at the holdout.

Run from backend/ with `.venv/bin/python ../experiments/bar/r2-mta/mta.py`, and add `--robust` for the robustness checks. The full table is in `results.csv`, the hedge results in `backtest.csv`.

## Results (effect in % of daily riders, 90% CI)

| mode | event | train n_ev | train % [CI] | q | holdout n_ev | holdout % [CI] | q | verdict |
|---|---|---|---|---|---|---|---|---|
| Subway | rain ≥ 0.01 in | 245 | −3.0 [−4.3, −1.8] | <.001 | 246 | −2.3 [−3.6, −0.9] | .015 | **FOUND** |
| Subway | rain ≥ 1 mm | 208 | −4.1 [−5.4, −2.8] | <.001 | 201 | −2.6 [−4.0, −1.1] | .015 | **FOUND** |
| Subway | rain ≥ 5 mm | 143 | −5.0 [−6.6, −3.5] | <.001 | 108 | −4.0 [−5.8, −2.2] | .001 | **FOUND** |
| Bus | rain ≥ 0.01 in | 245 | −4.2 [−5.6, −2.7] | <.001 | 246 | −4.2 [−5.8, −2.6] | <.001 | **FOUND** |
| Bus | rain ≥ 1 mm | 208 | −5.5 [−7.1, −4.0] | <.001 | 201 | −4.3 [−6.1, −2.5] | <.001 | **FOUND** |
| Bus | rain ≥ 5 mm | 143 | −7.1 [−9.0, −5.2] | <.001 | 108 | −6.4 [−8.5, −4.3] | <.001 | **FOUND** |
| LIRR | rain ≥ 0.01 in | 245 | −4.4 [−6.3, −2.4] | .001 | 246 | −2.7 [−4.3, −1.1] | .017 | **FOUND** |
| LIRR | rain ≥ 1 mm / ≥ 5 mm | 208 / 143 | −5.4 / −7.0 | <.001 | 201 / 108 | −3.0 / −4.9 | ≤.015 | **FOUND** |
| MNR | rain ≥ 0.01 in | 245 | −5.0 [−6.7, −3.2] | <.001 | 246 | −3.0 [−4.7, −1.3] | .013 | **FOUND** |
| MNR | rain ≥ 1 mm / ≥ 5 mm | 208 / 143 | −6.4 / −8.1 | <.001 | 201 / 108 | −3.3 / −5.8 | ≤.013 | **FOUND** |
| B&T | rain ≥ 0.01 in | 245 | −3.0 [−4.0, −2.0] | <.001 | 246 | −2.1 [−3.0, −1.2] | <.001 | **FOUND** |
| B&T | rain ≥ 1 mm / ≥ 5 mm | 208 / 143 | −3.5 / −4.3 | <.001 | 201 / 108 | −2.5 / −3.9 | <.001 | **FOUND** |
| Subway | cold < 32°F | 17 | −13.5 [−19.9, −7.1] | .001 | 20 | −4.8 [−7.7, −1.9] | .017 | FOUND* |
| Bus | cold < 32°F | 17 | −18.5 [−28.1, −8.9] | .004 | 20 | −5.9 [−10.3, −1.5] | .068 | FOUND* |
| Bus | snow ≥ 0.1 in | 12 | −16.7 [−28.7, −4.6] | .047 | 22 | −8.3 [−14.9, −1.7] | .089 | FOUND* |
| MNR | snow ≥ 0.1 in | 12 | −18.5 [−31.2, −5.8] | .035 | 22 | −8.0 [−13.7, −2.3] | .055 | FOUND* |
| B&T | snow ≥ 0.1 in | 12 | −16.7 [−27.6, −5.8] | .026 | 22 | −10.3 [−15.2, −5.5] | .002 | FOUND* |
| LIRR, MNR, B&T | cold < 32°F | 17 | −27 to −14 | .02–.11 | 20 | CI includes 0, or q > .1 | | NOT FOUND |
| Subway, LIRR | snow ≥ 0.1 in | 12 | −10 / −26 | .06 / .14 | 22 | | > .1 | NOT FOUND |
| all 5 | hot > 85°F, hot > 90°F | 83 / 23 | −2.0 to +1.3 | ≥ .11 | 76 / 25 | | ≥ .10 | NOT FOUND (0/10) |
| all 5 | MSG game, MSG home win | 173 / 106 | −1.3 to +1.4 | ≥ .37 | 192 / 115 | | ≥ .10 | NOT FOUND (0/10) |

20 of the 45 tests pass every criterion: all 15 rain tests and 5 cold/snow tests.

\*The cold and snow results pass the criteria but are weaker than rain. The effect shrinks by 2–3× from train to holdout, and there are only 12–22 event days. The train cold days fall partly in January 2022, during the Omicron wave, which the trend and harmonics do not absorb, so the train magnitude is likely inflated. I would treat these as a real sign with an uncertain size.

**Rain robustness.** With the storms above 1.5 in removed (11 train days, 11 holdout days, including the 2023-09-29 flood), rain ≥ 0.01 in still passes on every mode: train −2.6% to −4.4%, holdout −2.0% to −3.9%, with every CI excluding 0. So the result does not come from a few extreme storms.

**MSG games.** Neither a game nor a win shows any effect, even on LIRR, which serves Penn Station: train +1.4% [−1.0, +3.8], holdout −0.0%. About 18k fans is small next to roughly 230k LIRR riders a day. A system-wide count cannot see MSG traffic, and a station-level series would be needed.

## Hedge backtest (holdout 2024–2025, sized from train)

Income is daily fare revenue at a rough fare per rider (Subway and Bus $2.90, LIRR $7, MNR $9, B&T $8). The nuisance model (DOW, season, holiday, trend) is refit on holdout without the event term, so the residual keeps the rain effect. The hedge buys YES at train frequency + $0.02, plus a fee of 0.07·p·(1−p), with |β_$| contracts.

| mode | event | β ($/day) | price | SD unhedged → hedged | 5th-pct day unhedged → hedged |
|---|---|---|---|---|---|
| Subway | rain ≥ 0.01 in | −$257k | 0.37 | $637k → $633k (−0.7%) | −$1.048M → −$1.042M (better) |
| Bus | rain ≥ 0.01 in | −$137k | 0.37 | $280k → $274k (−2.2%) | −$503k → −$494k (better) |
| B&T | rain ≥ 0.01 in | −$215k | 0.37 | $325k → $320k (−1.4%) | −$551k → −$549k (better) |
| MNR | rain ≥ 0.01 in | −$62k | 0.37 | $123k → $123k (−0.4%) | −$176k → −$166k (better) |
| LIRR | rain ≥ 0.01 in | −$48k | 0.37 | $105k → $105k (−0.5%) | −$145k → −$154k (worse) |
| Bus | rain ≥ 5 mm | −$231k | 0.23 | $280k → $272k (−2.9%) | −$503k → −$508k (worse) |

The rain hedge lowers SD on all 15 rain rows, but only by 0.4–3.7%. The KXRAIN rain ≥ 0.01 in hedge also improves the 5th-percentile day on 4 of 5 modes. Cold and snow hedges raise SD on every row, because the effect shrank on holdout and the hedge was sized from the larger train effect. The hedge costs about 3.5% of the hedged amount per day (the +$0.02 markup and the fee). As in round 1, events explain little of the daily variance, so the hedge works but the gain is small.

## Verdict

- **Rain → MTA ridership: FOUND**, on all 5 modes and all 3 thresholds. A rain day at the KXRAIN threshold (≥ 0.01 in, Central Park NOAA record) costs Bus about 4%, LIRR and MNR 3–5%, Subway about 2–3% and B&T about 2–3% of the day's riders. The effect replicates on an independent 2-year holdout, survives BH over 45 tests on both periods, holds without extreme storms, and is measured on the settlement flag itself. It is the first event × series pair in this project that passes all four criteria plus the bonus (SD down on every rain row, 5th percentile better on 4 of 5 modes at the KXRAIN threshold).
- **Cold < 32°F (Subway, Bus) and snow (Bus, MNR, B&T): pass the criteria, with an unstable magnitude**, and the hedge backtest makes them worse. Treat them as directionally real but not hedgeable at the train size.
- **Hot > 85 / 90°F: NOT FOUND** (0 of 10). **MSG game or win: NOT FOUND** (0 of 10).

**Demo.** "MTA bus fare revenue on a KXRAIN day": show the train β of −4.2% (−$137k a day), the independent holdout β of −4.2%, and a buy of about 137k KXRAIN YES contracts at $0.37. The pitch is a business whose revenue moves with transit ridership, such as a station kiosk or an LIRR-dependent shop, sized by its share of riders. Be honest that the variance reduction is about 2%. The effect is real, but rain is a small part of the daily noise.

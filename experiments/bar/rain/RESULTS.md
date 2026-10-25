# Rain definition experiment (bar p_afa556030e60, plus taxi)

**Question.** Does a stricter or evening-only rain definition make the bar's rain effect measurable, and what does it do to taxi and to the hedge basis?

**Method.** Script `rain_defs.py` (run from `backend/`). It builds `features.build(business)`, swaps in each of 12 alternative `rain` flags computed from the cached MSG weather (daily and hourly Open-Meteo, inches; 1 mm = 0.03937 in; evening = hour-ending stamps 18..24 local), and refits `fit_exposures(strikes={"hot": 85})`. That is the same design as production: DOW, season k=1,2, controls, HC3, z=1.645, train = first 365 days. Basis R² is `beta_settlement(...).r2`, the Pearson² between the definition and `settle_rain` (station daily total >= 0.01 in, from `add_settlement`) on train. Markets rule 4 needs R² >= 0.5. "Agree" is the plain share of train days on which the two flags match.

## Bar (restaurant feature table, revenue = visits x $35, estimated)

| Definition | Days flagged (all / train) | n train | Effect $/day | 90% CI | p | Sig | Basis R² | Agree |
|---|---|---|---|---|---|---|---|---|
| current: daily >= 0.01 in | 43.7% / 40.5% | 148 | -345 | [-992, 301] | 0.38 | no | 0.82 | 95.3% |
| daily >= 1 mm | 33.6% / 32.1% | 117 | -58 | [-732, 616] | 0.89 | no | 0.72 | 92.3% |
| daily >= 2.5 mm | 26.7% / 26.0% | 95 | -155 | [-898, 589] | 0.73 | no | 0.53 | 86.3% |
| daily >= 5 mm | 18.4% / 17.8% | 65 | -99 | [-989, 791] | 0.86 | no | 0.33 | 78.1% |
| daily >= 10 mm | 9.6% / 8.5% | 31 | +112 | [-1342, 1566] | 0.90 | no | 0.14 | 68.8% |
| heavy: daily >= 20 mm | 3.9% / 3.3% | 12 | +551 | [-2962, 4064] | 0.80 | no | 0.05 | 63.6% |
| rain_open_hours (11-23 >= 0.05 in) | 22.1% / 20.8% | 76 | -216 | [-1101, 668] | 0.69 | no | 0.40 | 81.1% |
| open hours >= 2.5 mm | 16.9% / 15.9% | 58 | -174 | [-1247, 898] | 0.79 | no | 0.29 | 76.2% |
| evening any hour >= 1 mm/hr | 13.1% / 12.3% | 45 | +394 | [-829, 1616] | 0.60 | no | 0.21 | 72.6% |
| evening total >= 1 mm | 15.9% / 14.8% | 54 | +329 | [-712, 1371] | 0.60 | no | 0.26 | 75.1% |
| evening total >= 2.5 mm | 11.3% / 11.0% | 40 | +166 | [-1184, 1517] | 0.84 | no | 0.19 | 71.2% |
| evening total >= 5 mm | 5.7% / 5.5% | 20 | +852 | [-1517, 3221] | 0.55 | no | 0.09 | 65.8% |
| *settlement flag itself (β_S)* | — / 39.7% | — | -39 | [-707, 628] | — | no | — | — |

The bar's R² stays at 0.157–0.159 on train and 0.042–0.047 on holdout for every definition.

## Taxi (same definitions)

| Definition | n train | Effect $/day | 90% CI | p | Sig | Basis R² |
|---|---|---|---|---|---|---|
| current: daily >= 0.01 in | 148 | +2,212 | [533, 3890] | 0.030 | yes | 0.82 |
| daily >= 1 mm | 117 | +2,750 | [1000, 4500] | 0.010 | yes | 0.72 |
| daily >= 2.5 mm | 95 | +2,659 | [844, 4475] | 0.016 | yes | 0.53 |
| daily >= 5 mm | 65 | +2,121 | [190, 4053] | 0.071 | yes | 0.33 |
| daily >= 10 mm | 31 | +2,696 | [-170, 5562] | 0.122 | no | 0.14 |
| heavy: daily >= 20 mm | 12 | +2,878 | [-1844, 7600] | 0.316 | no | 0.05 |
| rain_open_hours | 76 | +2,822 | [789, 4855] | 0.022 | yes | 0.40 |
| open hours >= 2.5 mm | 58 | +2,037 | [-85, 4159] | 0.114 | no | 0.29 |
| evening any hour >= 1 mm/hr | 45 | +2,987 | [724, 5250] | 0.030 | yes | 0.21 |
| evening total >= 1 mm | 54 | +3,486 | [1460, 5512] | 0.005 | yes | 0.26 |
| evening total >= 2.5 mm | 40 | +3,385 | [1015, 5755] | 0.019 | yes | 0.19 |
| evening total >= 5 mm | 20 | +2,023 | [-966, 5012] | 0.266 | no | 0.09 |
| *settlement flag itself (β_S)* | — | +1,355 | [-338, 3048] | — | no | — |

Taxi R² ranges 0.273–0.285 on train and 0.238–0.251 on holdout.

## Verdict

None of the 12 definitions makes the bar's rain effect measurable. Every CI includes zero, the smallest p is 0.38, and the point estimate changes sign: it is mildly negative for whole-day definitions and positive for evening-only ones. That pattern is noise, not a usable effect. The threshold was too loose, though. Daily >= 1 mm flags 33.6% of days, which matches the expected 30–35%. Fixing it leaves the bar's model where it was (holdout R² about 0.05), so the problem is the noisy, estimated visit series, not the rain flag. For taxi, a moderate threshold (>= 1 mm, or evening total >= 1 mm) gives a larger and tighter effect than the current rule. The very strict definitions (>= 10 mm, heavy, evening >= 5 mm) lose significance because n gets small.

**Basis matters as much as the effect.** Kalshi pays on a station daily total at the measurable-rain threshold, so the further a definition moves from that, the worse the basis. Only daily >= 0.01 in (R² 0.82), >= 1 mm (0.72) and >= 2.5 mm (0.53) pass the R² >= 0.5 rule. Every evening, open-hours and heavy definition fails it, and the current `rain_open_hours` flag scores 0.40. The taxi's best-looking definition (evening >= 1 mm, R² 0.26) is therefore unhedgeable with the contract that exists. Separately, the effect of the settlement flag itself on taxi revenue is +$1,355 with CI [-338, 3048], which is not significant. Sizing uses β_S, so this is worth a look by whoever owns basis.

**Multiple comparisons.** That makes 12 definitions × 2 businesses = 24 fits, all on one train year, and the definitions overlap heavily, so the tests are correlated. Picking the best taxi row after the fact (evening >= 1 mm, p = 0.005) is a selection effect, so treat it as exploratory. The bar result is null across the board, so multiple comparisons can't rescue it.

**Recommendation.** Switch `RAIN_THRESHOLD_IN` from 0.01 in to about 1 mm (0.04 in) only if the station-side settlement rule is checked to still match the contract (Kalshi's rule is measurable precipitation, 0.01 in). Otherwise keep 0.01 in. Don't use evening or heavy-rain flags for hedging. Not demo-worthy for the bar. For taxi, ">= 1 mm is a bit stronger and still hedgeable" is a footnote at most.

Caveats: Open-Meteo is reanalysis, not the NWS station report, so the 43.7% wet-day share partly reflects reanalysis drizzle. The station series (`weather_station`) is the same Open-Meteo product at Central Park coordinates, not the actual CLI report Kalshi settles on.

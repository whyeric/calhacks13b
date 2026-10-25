# R2 aggregate: settleable events vs summed Dewey visit series

**Question.** One venue's Dewey series is ~50% noise. If we sum many venues, do Kalshi-settleable events (Central Park rain, high-temperature strikes, snow, Knicks/Rangers home games and wins) move the total in a way that shows up on train and again on a separate holdout?

**Verdict: FOUND (rain).** Rain at Central Park (≥ 0.01 in, the KXRAIN settlement, and ≥ 1 mm) cuts visits by about 1.5–3% in every large aggregate. That holds on train, holds again on an independent holdout, and survives BH at 10% on both. MSG home games raise visits near the arena (+3% within 0.5 km). That passes too, but it is not a weather hedge. The planned hypotheses failed: ice cream and cafés are not up on hot days, and limited-service is down in rain, not up. The hedge backtest cuts the SD of the holdout residual by only 1.6–2.4%. The effect is real but small.

## Data
- **Visits:** raw Dewey Manhattan restaurants/bars export (`data/01a16ff2-…`), 143 weeks from 2024-01-01 to 2026-09-27, expanded to days via `VISITS_BY_DAY`. Balanced panel only: stores present in all 143 weeks and with < 5% "flat" weeks (7 equal days, i.e. weekly/7 imputation). That keeps 10,189 of 11,498 stores. Only aggregates are used.
- **Baskets (stores):**

  | basket | stores |
  |---|---|
  | full-service 722511 | 7,819 |
  | limited-service 722513 | 1,394 |
  | drinking places 722410 | 976 |
  | café, by name keyword | 135 |
  | ice cream/dessert, by name keyword | 12 |
  | MSG ZIP cluster (10001, 10018, 10119–10123, 10199) | 710 |
  | ≤ 0.5 km of MSG | 277 |
  | nightlife bars (722410 in 10002/03/09/11/12/13/14) | 382 |

  The export has only three NAICS codes. There is no snack/ice-cream or café code (722515), so name-keyword baskets stand in for those.
- **Weather:** NOAA GHCN-Daily USW00094728 (Central Park, the NWS station that KXRAIN/KXHIGHNY settle on), fetched from the NCEI API. The flags are the settlement variables themselves, so basis criterion 4 holds by construction.
- **Games:** ESPN scoreboard for 2024-01 to 2024-10 (cached in the scratchpad), then the repo fixtures `schedule_{knicks,rangers}.csv`.

## Method
log(daily basket visits) ~ DOW dummies + year-month fixed effects + holiday (+ MSG home-game control for weather events) + flag, fit by OLS with HAC (7 lags) errors and z = 1.645. Train covers 2024-01-01 to 2025-03-31 (456 days). The holdout, 2025-04-01 to 2026-09-27 (545 days), is refit on its own. `msg_home_win` is fit on home-game days only, so it measures a win against a loss.

**Tests:** 8 baskets × 12 events = **96**, with BH at 10% across all 96 on each split. The events are rain ≥ 0.01 in, rain ≥ 0.04 in (1 mm), tmax > 80/85/90, tmax ≤ 32/≤ 40 (the NO side of a high-temp strike), snow ≥ 0.1 in, Knicks home, Rangers home, any MSG home game, and MSG home win.

FOUND requires all of the following:
- train CI excludes 0 with ≥ 10 events
- the holdout refit has the same sign and its CI excludes 0
- train BH q ≤ 0.10

## Results

41 of 96 were significant on train. **20 meet FOUND**, and 14 of those also have holdout BH q ≤ 0.10 (marked ★).

| basket | event | train % [90% CI] (n) | holdout % [90% CI] (n) | BH q train / holdout |
|---|---|---|---|---|
| full-service | rain ≥ 0.01 ★ | −1.88 [−2.77, −1.00] (150) | −1.75 [−2.47, −1.03] (202) | 0.007 / 0.001 |
| full-service | rain ≥ 1 mm ★ | −2.42 [−3.38, −1.47] (124) | −2.06 [−2.81, −1.31] (159) | 0.002 / 0.000 |
| limited-service | rain ≥ 0.01 ★ | −1.59 [−2.39, −0.79] (150) | −1.06 [−1.71, −0.41] (202) | 0.009 / 0.048 |
| limited-service | rain ≥ 1 mm ★ | −2.08 [−2.92, −1.24] (124) | −1.34 [−2.02, −0.65] (159) | 0.002 / 0.011 |
| drinking | rain ≥ 0.01 ★ | −1.99 [−3.20, −0.78] (150) | −2.76 [−3.82, −1.70] (202) | 0.033 / 0.000 |
| drinking | rain ≥ 1 mm ★ | −2.15 [−3.47, −0.82] (124) | −3.32 [−4.49, −2.15] (159) | 0.035 / 0.000 |
| MSG ZIP cluster | rain ≥ 0.01 ★ | −2.03 [−3.05, −1.02] (150) | −2.26 [−3.17, −1.36] (202) | 0.009 / 0.001 |
| MSG ZIP cluster | rain ≥ 1 mm ★ | −2.57 [−3.62, −1.51] (124) | −2.89 [−3.78, −2.01] (159) | 0.002 / 0.000 |
| ≤ 0.5 km MSG | rain ≥ 0.01 ★ | −2.62 [−4.06, −1.18] (150) | −2.95 [−4.15, −1.76] (202) | 0.017 / 0.001 |
| ≤ 0.5 km MSG | rain ≥ 1 mm ★ | −3.07 [−4.58, −1.57] (124) | −3.75 [−4.95, −2.55] (159) | 0.007 / 0.000 |
| nightlife bars | rain ≥ 0.01 ★ | −1.79 [−3.11, −0.47] (150) | −2.84 [−4.04, −1.65] (202) | 0.092 / 0.001 |
| nightlife bars | rain ≥ 1 mm ★ | −2.32 [−3.70, −0.93] (124) | −3.46 [−4.75, −2.18] (159) | 0.030 / 0.000 |
| ≤ 0.5 km MSG | MSG home game ★ | +3.00 [+1.56, +4.44] (141) | +3.13 [+1.38, +4.88] (105) | 0.007 / 0.024 |
| ice cream (12 stores) | MSG home game ★ | +4.04 [+1.98, +6.11] (141) | +3.45 [+1.61, +5.30] (105) | 0.009 / 0.017 |
| ice cream (12 stores) | Rangers home | +3.86 [+1.47, +6.26] (70) | +3.86 [+0.91, +6.81] (45) | 0.035 / 0.132 |
| ≤ 0.5 km MSG | Rangers home | +3.20 [+1.56, +4.84] (70) | +2.76 [+0.08, +5.43] (45) | 0.009 / 0.233 |
| MSG ZIP cluster | MSG home game | +1.48 [+0.48, +2.48] (141) | +1.52 [+0.33, +2.71] (105) | 0.062 / 0.133 |
| full-service | tmax > 90 | −3.35 [−5.76, −0.94] (15) | −1.45 [−2.75, −0.15] (19) | 0.085 / 0.208 |
| limited-service | snow ≥ 0.1 in | −3.44 [−5.46, −1.41] (19) | −4.64 [−9.03, −0.25] (13) | 0.028 / 0.232 |
| MSG ZIP cluster | snow ≥ 0.1 in | −4.34 [−6.39, −2.28] (19) | −6.16 [−12.26, −0.05] (13) | 0.007 / 0.240 |

Full table: `results.csv`; console log: `output.txt`.

**Failed planned hypotheses:**
- **Ice cream and cafés up on hot days:** no. Every hot-threshold estimate for those baskets is null or negative on both splits.
- **Limited-service up in rain:** no, it falls about 1–2%. Dewey counts foot visits, so delivery demand is invisible here.
- **Bars down in rain:** yes, drinking places −2 to −3% and nightlife bars −2 to −3.5%.
- **Hot > 85:** significant on train for five baskets, but it did not replicate on the holdout. It is the same kind of train-only false positive as round 1's taxi result.

**Robustness for rain ≥ 0.01 in (not counted in the 96 tests):**
- **Permutation placebo:** shuffling the rain flag within year-month on train gives perm p = 0.000 for full-service, limited-service and the MSG ZIP cluster, 0.010 for drinking and 0.045 for nightlife. The placebo's 95th-percentile |t| reaches 2.56 for full-service, which suggests HAC understates the SE somewhat. The real |t| still exceeds it.
- **Week fixed effects instead of year-month:** the holdout stays significant in all 5 baskets (−1.2% to −2.5%). The train estimate shrinks to −0.6% to −1.3% and its CI crosses 0. Week FE is a harsh control, because rainy days cluster within weeks. The year-month result is the primary one.

## Hedge backtest (holdout, sized from train)
The β is fit in levels on train, with $ = visits × $35. The hedge buys the side that pays on the bad outcome, at the train event frequency + $0.02 plus fee 0.07·p·(1−p), sized |β| per $1 contract. It is scored on the holdout residual after removing DOW/month/holiday.

| basket | event | price | SD change | 5th-percentile day change |
|---|---|---|---|---|
| MSG ZIP cluster | rain ≥ 1 mm | 0.29 | **−2.4%** | **+2.1%** |
| MSG ZIP cluster | rain ≥ 0.01 | 0.35 | −1.6% | +1.9% |
| ≤ 0.5 km MSG | rain ≥ 1 mm | 0.29 | −1.9% | +3.1% |
| drinking places | rain ≥ 1 mm | 0.29 | −2.2% | +1.0% |
| drinking places | rain ≥ 0.01 | 0.35 | −1.9% | +1.6% |
| nightlife bars | rain ≥ 1 mm | 0.29 | −1.6% | +0.9% |
| limited-service | rain ≥ 1 mm | 0.29 | −0.6% | +2.8% |
| full-service | rain ≥ 1 mm | 0.29 | −2.2% | **−2.4% (worse)** |
| ≤ 0.5 km MSG | MSG home game (buy NO) | 0.71 | −0.5% | +3.0% |

The hedge works in the right direction: it reduces SD in every rain case, and it improves the 5th-percentile day in all but full-service. The size is small. Rain explains a few percent of daily variance, so one rain contract removes about 2% of the day-to-day swing. Holdout rain frequency (0.37) was a bit above the train price, so the hedge also netted a small gain. That is luck, not edge. Full numbers: `hedge.csv`.

## Demo angle
"A Midtown/MSG-area restaurant loses about 2.5–3% of foot traffic on a rainy day at Central Park. That held in 2024 and again in 2025–26 across 700 nearby venues. A KXRAIN YES contract sized to the loss pays on exactly those days." Show the train and holdout bars side by side for the MSG ZIP cluster, then the hedged and unhedged holdout residual distribution.

The honest caveat: a single business's own noise (~50%) dwarfs a 2.5% effect, so the hedge is a portfolio- or neighborhood-level product, not something one bar would notice.

## Reproduce
From `backend/`: `.venv/bin/python ../experiments/bar/r2-aggregate/run.py`. The GHCN CSVs and the ESPN cache live in the scratchpad `r2-cache/`; run time is about 1 minute.

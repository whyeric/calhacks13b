# R7 deferral: does rain move NYC going-out demand instead of destroying it?

**Verdict: NOT FOUND. Rain does not move demand.** We found no next-day rebound, no Saturday-to-Sunday
shift and no indoor substitution that replicates. The weekly net loss per rain day is at least as
large as the same-day loss (point estimate about 2x larger). That is the opposite of the hypothesis.
A daily KXRAIN hedge sized on the same-day beta **under-hedges**; it does not over-hedge. The desk
should not cut the size for deferral.

Scripts: `fetch.py` (MTA, GHCN into the scratchpad cache), `run.py` (all tests). Outputs:
`results.csv`, `verdict.csv`, `net_ratio.csv`, `hedge.csv`, `output.txt`.

## Mechanism (stated before fitting)
Rain on day t cancels some outings. If a share of them is **rebooked** or **redirected**, there are
four predictions:
1. Visits on t+1 rise when t was rainy, holding t+1's own weather fixed (rain_{t-1} > 0).
2. A rainy Saturday raises Sunday visits, and a rainy Sunday (forecast ahead) pulls visits into Saturday.
3. Weekly totals fall by less per rain day than the same-day effect implies (weekly gap > 0).
4. On rain days, outdoor-dining neighborhoods lose share to indoor/transit neighborhoods
   (log outdoor − log indoor < 0), and limited-service (takeout) holds up better than sit-down.

If any of these holds, the weekly loss is smaller than the sum of the daily losses, and a daily hedge
over-hedges by (daily-implied loss) / (weekly net loss).

## Data
- **Dewey** Manhattan visits, balanced panel (venues present in all 143 weeks, <5% flat weeks),
  daily aggregates only. Baskets and venue counts:
  - bars (NAICS 722410): 976
  - full-service restaurants (722511): 7,819
  - limited-service (722513, used as the takeout proxy): 1,394
  - **outdoor** basket (722410+722511 in ZIPs 10014, 10011, 10036, 10019, i.e. West Village,
    Meatpacking/Chelsea, Hell's Kitchen): 1,465
  - **indoor/transit** basket (same NAICS in 10017, 10022, 10018, 10001, 10004, 10005, 10006, 10038,
    i.e. Midtown East, Garment/Penn, FiDi): 1,240
  - dining = bars + full-service: 8,795
- **MTA subway** daily (sayj-mze2), 2024-01..2026-09.
- **TLC HVFHV** citywide daily trips. Cached data only runs 2024-01..2025-12, so the FHV holdout is
  2025-04..2025-12 (38 weeks). **There is no delivery data:** FHV is ride-hail, not food delivery,
  and limited-service visits are the only takeout proxy.
- **Weather:** NOAA GHCN Central Park USW00094728, the KXRAIN settlement station. Rain means
  PRCP ≥ 0.01 in, so the basis to the settlement flag is identical by construction. I checked hourly
  LCD rain for a daytime-rain definition but did not use it: the NCEI v1 service returns data only
  through 2025-08-25, which does not cover the holdout.

## Method
- **Daily model:** log y ~ DOW + year-month FE + holiday + tmax + (tmax−65)² + snow + rain terms, HAC(7).
- **Weekly model:** log weekly total (Mon–Sun, the Dewey week) ~ year-month FE (by majority month) +
  mean tmax + snow + holidays + # rain days, HAC(4).
- **Displaced share:** (weekly net % per rain day) − (same-day % × the rain day's share of its week).
  CIs come from a 300-draw week-block bootstrap.
- **Splits:** train 2024-01..2025-03, holdout 2025-04..2026-09, each refit independently.
- **Multiple testing:** BH at 10% over **58 train tests**:
  - 8 series × {T1 rebound, T1b day-before, T1c 3-day sum, T2 Sat→Sun, T2 Sun→Sat, T3 weekly, T3b gap}
  - plus 2 spatial tests
  - the same-day "T0" effects and the placebos are reported but not in the family
- **Placebos:** rain_{t−7}, rain_{t+7}, and next week's # rain days in the weekly model.

## Results

### The four displacement tests
All rows are in % of visits. The holdout fit is independent of train.

| Test | Series | Train % [90% CI] | q_BH | Holdout % [90% CI] | Verdict |
|---|---|---|---|---|---|
| T1 next-day rebound (rain_{t−1}) | dining | +0.55 [−0.22, +1.34] | 0.48 | −0.30 [−0.90, +0.30] | NOT FOUND |
| | bars | +0.13 [−0.84, +1.11] | 0.87 | −0.71 [−1.64, +0.22] | NOT FOUND |
| | outdoor | +1.06 [−0.02, +2.15] | 0.30 | −0.28 [−1.03, +0.48] | NOT FOUND |
| | subway | +0.37 [−0.63, +1.38] | 0.72 | −0.90 [−2.55, +0.78] | NOT FOUND |
| T2 Sat rain → Sun | dining | +1.00 [−0.69, +2.71] | 0.55 | +1.24 [−0.22, +2.71] | NOT FOUND |
| | **outdoor** | **+3.43 [+1.07, +5.84]** (n=25) | **0.085** | +1.80 [−0.17, +3.81] (n=29) | NOT FOUND (holdout CI touches 0) |
| T2 Sun rain → Sat | dining | −2.64 [−4.83, −0.40] | 0.21 | +1.15 [−0.51, +2.84] | NOT FOUND (sign flips) |
| T3b displaced share of week per rain day (pp) | dining | −0.25 [−0.84, +0.42] | 0.65 | −0.44 [−0.94, −0.01] | NOT FOUND, and the sign is opposite the hypothesis |
| T4 outdoor − indoor on rain days | all days | −0.14 [−0.76, +0.48] | 0.84 | −0.51 [−1.01, −0.01] | NOT FOUND |
| | weekends | +0.67 [−0.31, +1.67] | 0.51 | −0.88 [−1.50, −0.26] | NOT FOUND (sign flips) |
| Takeout proxy (limited-service), same day | – | −1.50 [−2.29, −0.70] | – | −0.95 [−1.48, −0.42] | Takeout also falls on rain days, less than sit-down. No evidence of a switch. |

The only hint of a shift is a rainy Saturday nudging outdoor-neighborhood Sunday visits up by about
2–3%, and that does not clear the holdout. Even if it were real, the outdoor basket is about 17% of
dining venues, so the shift is too small to change the weekly arithmetic.

### What did replicate: rain's loss spills across days instead of rebounding
| Test | Series | Train % [90% CI] | q_BH | Holdout % [90% CI] | Verdict |
|---|---|---|---|---|---|
| T0 same-day rain (reference) | dining | −1.91 [−2.78, −1.04] | – | −1.86 [−2.49, −1.22] | (prior result reproduced) |
| T1b day before rain (rain_{t+1}) | dining | −1.45 [−2.21, −0.69] | 0.033 | −0.54 [−1.13, +0.04] | not replicated |
| **T1c 3-day sum (t−1, t, t+1)** | **dining** | **−2.68 [−4.28, −1.05]** | 0.059 | **−2.54 [−3.76, −1.32]** | **FOUND** |
| | **bars** | **−3.12 [−5.07, −1.12]** | 0.065 | **−3.77 [−5.71, −1.78]** | **FOUND** |
| | **full-service** | **−2.55 [−4.17, −0.90]** | 0.065 | **−2.18 [−3.29, −1.05]** | **FOUND** |
| | FHV trips (sign +) | +5.23 [+3.27, +7.22] | 0.000 | +2.59 [+0.43, +4.79] | FOUND (ride-hail *gains*, consistent with r2-taxi) |

The total loss across a rain episode is about **1.4x the same-day effect** (−2.68 vs −1.91 on train,
−2.54 vs −1.86 on holdout). Much of the extra loss sits on the day *before* the rain, which points to
forecast-driven cancellations or evening rain that the midnight-to-midnight station day assigns to
the next date. It does not point to a rebound.

### Weekly net vs the sum of daily effects (the over-hedge ratio)
Both columns are % of the weekly total per rain day.

| Split | Series | Daily-implied (same-day × day share) | Weekly net | Net / daily [90% bootstrap] | **Over-hedge ratio** (daily / net) |
|---|---|---|---|---|---|
| train | dining | −0.28 | −0.54 | 1.89 [−0.93, 4.09] | **0.53** |
| holdout | dining | −0.26 | −0.71 | 2.68 [1.03, 4.85] | **0.37** |
| train | bars | −0.25 | −0.45 | 1.81 [−1.92, 4.32] | 0.55 |
| holdout | bars | −0.37 | −1.05 | 2.81 [0.90, 4.94] | 0.36 |
| train | outdoor | −0.28 | −0.23 | 0.82 [−4.03, 3.01] | 1.21 |
| holdout | outdoor | −0.33 | −0.90 | 2.78 [0.70, 5.00] | 0.36 |
| holdout | subway | −0.48 | −0.68 | 1.41 [−0.28, 2.86] | 0.71 |

An over-hedge ratio below 1 means a daily hedge covers less than the weekly loss. On holdout, the
dining interval for net/daily excludes 1 (lower bound 1.03). That rejects "the weekly loss is
smaller" outright. On train the ratio is too noisy to pin down, but the point estimate is again
about 2x. Among the loss series, only 4 of 14 series × split fits have a weekly loss smaller than the
daily-implied one: train outdoor, train subway, and limited-service in both splits. None of those
gaps is significant. The weekly ratio itself is
imprecise (only 65 and 77 weeks) and may pick up storm persistence: rainy weeks are also grey and
cool. I would trust the replicated 3-day ratio of 1.4x more than the weekly 1.9–2.7x.

### Placebos
- **Weekly placebo** (next week's rain days): 2 of 16 CIs exclude 0. That is consistent with chance,
  so the weekly test is clean.
- **Daily placebos** (rain_{t±7}): 10 of 32 CIs exclude 0, against about 3 expected. The worst
  offenders are subway rain_{t−7} (−2.1% train, −1.9% holdout) and dining rain_{t+7} on holdout
  (+0.8–1.1%, but the five Dewey baskets overlap heavily, so that is really one hit).
- Taken together (12 of 48), HAC(7) CIs on the daily model look roughly 1.5x too narrow, or weekly
  weather regimes leak through.
- The FOUND 3-day effects (−2.5 to −3.8%) are larger than every Dewey placebo (|max| 1.3%), but the
  ±1% effects in this file should be read with that in mind.

## Hedge backtest (holdout, typical sit-down venue, $35/visit)
- **Setup:** buy KXRAIN YES every day at train frequency + $0.02 = $0.349, plus fee 0.07·p·(1−p).
  Size k × (same-day loss): 1.91% × the venue's within-month DOW baseline revenue.
- **Measure:** P&L added to the venue's deviation from that baseline.

| Sizing | k | daily SD | weekly SD | weekly 5th pct |
|---|---|---|---|---|
| none | 0 | $310.6 | $1,364.9 | −$2,677 |
| same-day beta | 1.00 | $305.2 | $1,330.4 | −$2,635 |
| "deferral haircut" (the hypothesis) | 0.50 | $306.1 | $1,344.5 | −$2,632 |
| 3-day net (train) | 1.40 | $307.2 | $1,323.6 | −$2,616 |
| weekly net (train) | 1.89 | $312.7 | $1,320.9 | −$2,541 |

On weekly SD, a larger size beats a smaller one: the haircut is the worst hedged option, and 1.4–1.9x
is the best. The gains are small either way (2.5–3% off weekly SD), because rain explains little of
a venue's variance. That matches the earlier rounds.

## Recommendation for the desk
1. **Do not cut daily KXRAIN size for "deferral."** There is no evidence that rain demand comes back
   the next day, on the other weekend day or in indoor neighborhoods.
2. **Size at about 1.0–1.4x the same-day beta.** 1.0x is the conservative default. 1.4x is the
   replicated multi-day loss (the episode costs about 1.4 days' worth of same-day effect). Don't go to
   the 1.9–2.7x weekly ratio: its CI is wide and it is probably partly confounded by rainy-week regimes.
3. **Where the extra loss falls:** much of it lands on the day *before* rain, when the forecast is
   already known. A same-day contract bought on the forecast won't pay it out cheaply.
4. **A weekly product would fit better than daily contracts.** Kalshi lists **KXRAINNYCW**, which
   settles on whether the Mon–Sun Central Park total exceeds a threshold. Its basis to # rain days is
   weak, though: corr(# rain days, weekly total) = 0.52, and corr with the >1 in flag = 0.46. It
   would hedge heavy-rain weeks, not rain-day counts.

## Count and honesty
- 58 BH-family tests per split, plus 48 placebo fits and 16 same-day reference fits.
- 4 rows meet FOUND: the 3-day sum for dining, bars, full-service and FHV. None of them supports
  deferral.
- Holdout data was not used for tuning. The basket ZIPs were fixed before fitting, from the brief.
- The hedge sizes come from train only. The hedge's within-month DOW baseline uses holdout means,
  but only as a variance yardstick.

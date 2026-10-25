# R3: monthly bike demand vs monthly Central Park rain (KXRAINNYCM)

**Question.** Does monthly bike demand track the monthly Central Park precipitation total
closely enough to hedge with Kalshi KXRAINNYCM ("NYC monthly rain above X in", strictly
greater, settles on the NWS CLI Central Park monthly total)? That contract can be bought
weeks ahead, unlike daily KXRAIN.

**Data (all public, cached in scratchpad `r2-cache/r3bike_*`).**
- **jc**: Citi Bike Jersey City/Hoboken trips per month, counted as rows in every
  `s3://tripdata` JC-YYYYMM zip. That covers 133 months, 2015-09..2026-09. Mean holdout
  revenue is $328k a month at $4 per trip.
- **dot**: NYC DOT automated bike counters (`uczf-rk3c`), turned into counter-months that
  report on at least 90% of days. 22 counters are used in train and 32 in holdout.
- **Weather**: GHCN-Daily `USW00094728` (Central Park), summed to inches per month, plus rain
  days (≥ 0.01 in). This is the same station and the same sum as the CLI monthly total, so
  the "> X in" flag is the settlement flag. Basis R² ≈ 1, apart from mm→in rounding. No days
  are missing in 2015–2025.
- **Periods**: train is 2016-01..2021-12 and holdout is 2022-01..2025-12. 2020-03..2021-06
  (COVID) is dropped from both. Each period is fitted independently, and nothing was tuned on
  the holdout.

**Method.** For jc: `log(trips) ~ month-of-year + year FE + β·x`, with HC3 errors and
t critical values on df_resid. That gives df = 38 on 56 train months and df = 32 on
48 holdout months. For dot: `log(mean daily count) ~ counter×year FE + month-of-year + β·x`,
clustered by calendar month, with t on G−1 (55 and 47). x ∈ {precip in, rain days,
1[> 3 in], 1[> 4 in], 1[> 5 in]}, giving 2 series × 5 = **10 tests**. BH at 10% is applied
separately to the train p-values and the holdout p-values.

Run it with `cd backend && .venv/bin/python ../experiments/bar/r3-bikemonthly/bike_monthly_rain.py`.
That writes `r3bike_results.csv`, `r3bike_backtest.csv` and `r3bike_kalshi_prices.csv`.

## Results (β is the change in log trips, ≈ % change; 90% t CI)

| series | x | train β [90% CI] | n event (tr) | holdout β [90% CI] | n event (ho) | BH tr | BH ho | verdict |
|---|---|---|---|---|---|---|---|---|
| jc | precip, per inch | −1.29% [−2.88, +0.29] | – | −1.29% [−2.72, +0.13] | – | 0.22 | 0.33 | NOT FOUND |
| jc | rain days, per day | −0.10% [−1.70, +1.50] | – | −0.79% [−1.74, +0.16] | – | 0.92 | 0.34 | NOT FOUND |
| jc | > 3 in | −4.5% [−16.1, +7.1] | 39 | −6.9% [−17.0, +3.2] | 31 | 0.57 | 0.37 | NOT FOUND |
| jc | > 4 in | −6.5% [−14.1, +1.2] | 29 | −1.9% [−10.5, +6.7] | 23 | 0.22 | 0.79 | NOT FOUND |
| jc | > 5 in | −7.8% [−15.8, +0.2] | 21 | −0.2% [−8.2, +7.8] | 12 | 0.21 | 0.96 | NOT FOUND |
| dot | precip, per inch | **−1.96% [−3.04, −0.89]** | – | **−1.04% [−1.67, −0.40]** | – | 0.014 | 0.053 | **FOUND** (small) |
| dot | rain days, per day | −0.67% [−1.44, +0.11] | – | −0.89% [−1.45, −0.33] | – | 0.22 | 0.053 | NOT FOUND (train CI spans 0) |
| dot | > 3 in | −7.7% [−14.9, −0.5] | 39 | −4.0% [−8.1, +0.2] | 31 | 0.20 | 0.33 | NOT FOUND |
| dot | > 4 in | −7.8% [−12.1, −3.4] | 29 | −1.9% [−6.4, +2.7] | 23 | 0.014 | 0.62 | NOT FOUND (no holdout replication) |
| dot | > 5 in | −10.1% [−14.8, −5.4] | 21 | −3.2% [−7.8, +1.5] | 12 | 0.007 | 0.37 | NOT FOUND (no holdout replication) |

**1 of 10 passes**: the DOT counters' continuous precipitation slope. Every sign is negative,
so more rain means fewer rides, but the effect is **small**. Monthly precipitation in Central
Park has an SD of about 2 in, so one SD of monthly rain moves ridership by only about 2–4%.
The binary strikes that KXRAINNYCM actually lists (> 3/4/5 in) were significant on train for
DOT but shrank by two-thirds and lost significance on holdout. That is the same pattern of
train-year false positives seen in round 1. JC passes nothing. Its point estimate of
−1.3% per inch is the same in both periods, but with 48–56 months and 16–18 fixed effects
the CI always includes 0.

Why the daily result disappears at the monthly level: daily rain cuts rides by about 20%, but
a "wet" month has only 2–4 more rain days than a dry one. Riders also move trips to dry days
in the same month. Month-of-year and year effects, plus system growth (JC trips grew from 12k
to more than 100k a month), dominate the variance. The full-model R² is 0.97 on train and 0.93
on holdout, almost none of it from rain.

## Hedge backtest (jc holdout 2022–2025, 48 months, USD/month, $4/trip)

The hedge buys YES "> X in" at the train frequency + $0.02 + fee 0.07·p·(1−p).
Contracts = |1 − e^β_train| × the trailing-12-month mean revenue, which is known before the
month. The "ladder" buys YES at every strike 1..10 (Σ 1[P > k] ≈ floor(P)), sized from the
per-inch β. Revenue SD is dominated by seasonality, so the SD of the year-over-year change
is also reported.

| hedge | SD revenue | SD YoY Δ | worst YoY month | 5th pct YoY | mean hedge P&L / month |
|---|---|---|---|---|---|
| none | 101,824 | 55,024 | −56,408 (2025-10) | −40,950 | 0 |
| YES > 3 in | 101,066 | 55,063 | −67,282 (2025-06) | −49,840 | −1,282 |
| YES > 4 in | 102,427 | 55,237 | −68,102 (2025-06) | −46,567 | −1,618 |
| YES > 5 in | 101,943 | 53,785 | −67,072 (2025-10) | −49,681 | −3,673 |
| ladder 1..10 | 101,651 | 54,103 | −66,107 (2025-06) | −48,997 | −3,088 |

**The hedge does not help.** SD moves by at most 2%, which is noise. Every version makes the
worst month and the 5th percentile *worse* and costs $1–4k a month. Even sized at the DOT
holdout slope (−1%/in), a hedge pays about $3k per inch against a $55k YoY SD.

## Pricing check (real KXRAINNYCM, settled)

The public API lists only 3 settled events: 2026-08 (13 strikes), 2026-09 (10) and
2026-10 (2). The settled `last_price` is just the resolved 0.01/0.99. The first daily candle
close (`r3bike_kalshi_prices.csv`) is a better guide. Strikes 3–7 opened close to
climatology:

| month | > 4 in | > 5 in | > 6 in | > 7 in |
|---|---|---|---|---|
| Aug-26 first close | – | 0.51 | 0.36 | 0.18 |
| Sep-26 first close | 0.56 | 0.54 | 0.34 | 0.37 |
| train freq (all months 2016–21) | 0.52 | 0.38 | 0.23 | 0.14 |
| same-month 1991–2025 | 0.46 / 0.46 | 0.37 / 0.34 | 0.26 / 0.23 | 0.17 / 0.17 |

Early prices sit roughly 0–20¢ above climatology. Some first candles land a few days into the
month (`day1_ts`), so they already carry forecast information. Two months is too few to say
whether the market is rich, but it does not look cheap. Volume is real, with 10k–36k contracts
on the middle strikes.

## Verdict

- **jc monthly × KXRAINNYCM (precip, rain days, > 3/4/5 in): NOT FOUND.**
- **dot monthly × precip inches: FOUND on the criteria, but economically negligible:** about
  −1 to −2% per inch, and the effect halved from train to holdout.
- **dot monthly × > 3/4/5 in (the listed strikes): NOT FOUND.** They are significant on train
  and fail on holdout.
- **Hedge: no improvement.** It raises cost and worsens tail months.

Bottom line for the demo: the daily rain effect is real, but it does **not** add up to a
monthly exposure big enough to hedge with KXRAINNYCM. Buying weeks ahead fixes the
"only hedges forecast error" problem but drops the signal almost entirely. A daily
KXRAIN hedge stays the better story.

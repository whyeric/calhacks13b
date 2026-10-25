# R3 tie-breaker: NOAA vs Open-Meteo, and why r2-pooling and r2-aggregate disagree on rain

**Question.** r2-pooling found no rain effect near MSG (−0.10%, null) and r2-aggregate found one (−2.03% on train, −2.26% on holdout, FOUND). The two differ in three ways: weather source (Open-Meteo vs NOAA), seasonality (harmonics vs year-month FE) and split dates. Which of these flips the result? Second question: does NOAA weather rescue any round-1 single-business null, or fix the taxi instability?

**Answer.** **Seasonality flips it, and nothing else does.** With harmonics k = 1, 2, 0 of 12 cells are FOUND. With year-month fixed effects, 11 of 12 are FOUND. That holds for every weather source, split and unit. Weather source and split dates only move the size a little. NOAA rescues nothing in round 1: the bar is still null and the taxi is still unstable.

## Data

- **Units.**
  - **panel358:** the 358 r2-pooling venues, at the venue-day level (2024-01-01..2026-09-27).
  - **sum358:** the same venues as one daily mean.
  - **zip710:** r2-aggregate's balanced MSG-ZIP basket of 710 stores, built by importing `r2-aggregate/run.py`'s `series()`.
- **Weather.**
  - **Open-Meteo:** the MSG grid cell, precipitation_sum ≥ 0.01 in. I refetched 2024-01..2026-09 with `app.data.weather.fetch` into the scratchpad. It is identical to `fixtures/weather_msg.parquet` on the overlapping dates.
  - **NOAA:** GHCN USW00094728 (Central Park), PRCP ≥ 0.01 in. This is the KXRAIN settlement record. The script reads its own download (`r2-cache/r3noaa_ghcn.csv`, fetched from NCEI 2026-10-24) and asserts no gaps over 2024-01..2026-09. Over 2024-01..2026-09 the PRCP, TMAX and SNOW values match the shared `ghcn_2024/2025/2026.csv` exactly. All results are unchanged after the switch.
- **Games:** r2-aggregate's `games()` (ESPN plus the repo schedules).

## Method

- **Common model in every cell:** log visits ~ DOW + holiday + MSG home game + rain + seasonality, where seasonality is either sin/cos k = 1, 2 or year-month dummies.
- **Standard errors:** for the panel, venue FE by within-demeaning, with SE = max(date-clustered, Driscoll-Kraay HAC 7), the same as r2-pooling. For the baskets, HAC 7. z = 1.645.
- **Fits:** train and holdout are fit independently.
- **BH 10% family:** 32 train tests (24 grid cells plus 8 round-1 refits).

Script: `noaa.py` (run from backend/, about 6 s). Outputs: `grid.csv`, `round1.csv` and `output.txt`.

**Reproduction check.** The zip710 / NOAA / year-month FE / A cell gives −2.01% train and −2.24% holdout (r2-aggregate: 100·β = −2.03 / −2.26, which is the same number). The panel358 / Open-Meteo / harmonics / P cell gives −0.20% [−1.55, +1.17] (r2-pooling: −0.10%; it also had msg_event, home_win and hot as controls).

## Basis: Open-Meteo MSG grid vs NOAA Central Park

| window | agree | corr | wet-day rate OM / NOAA | OM-only days | NOAA-only days |
|---|---|---|---|---|---|
| P train 2024-10..2025-09 | 87.4% | 0.74 | 40.5% / 31.2% | 40 | 6 |
| P holdout 2025-10..2026-08 | 85.4% | 0.72 | 47.2% / 37.9% | 40 | 9 |
| A train 2024-01..2025-03 | 89.3% | 0.78 | 40.1% / 32.9% | 41 | 8 |
| A holdout 2025-04..2026-09 | 85.0% | 0.71 | 47.3% / 37.1% | 69 | 13 |

The Open-Meteo Central Park grid cell is no better: it agrees with NOAA on 85–90% of days. Almost all of the disagreement is one-sided: Open-Meteo calls a day wet when the gauge recorded less than 0.01 in. r2-pooling's "95% agreement" was Open-Meteo against Open-Meteo (MSG grid vs CP grid), not against the settlement record.

## Grid: rain effect on visits (% [90% CI]), n = rain days

| unit | source | season | split | train % [90% CI] (n) | BH q | holdout % [90% CI] (n) | FOUND |
|---|---|---|---|---|---|---|---|
| panel358 | Open-Meteo | harm | P | −0.20 [−1.55, +1.17] (148) | 0.90 | −0.95 [−2.55, +0.68] (158) | no |
| panel358 | Open-Meteo | harm | A | −0.49 [−1.84, +0.89] (183) | 0.79 | −0.53 [−1.72, +0.68] (258) | no |
| panel358 | Open-Meteo | ymFE | P | −1.14 [−1.96, −0.32] (148) | 0.081 | −1.34 [−2.33, −0.33] (158) | **yes** |
| panel358 | Open-Meteo | ymFE | A | −1.28 [−2.09, −0.48] (183) | 0.048 | −1.19 [−1.90, −0.48] (258) | **yes** |
| panel358 | NOAA | harm | P | +0.46 [−1.07, +2.01] (114) | 0.83 | −1.41 [−2.89, +0.09] (127) | no |
| panel358 | NOAA | harm | A | +0.06 [−1.45, +1.59] (150) | 0.95 | −0.97 [−2.08, +0.15] (202) | no |
| panel358 | NOAA | ymFE | P | −0.95 [−1.78, −0.12] (114) | 0.118 | −1.81 [−2.87, −0.75] (127) | no (BH 0.118) |
| panel358 | NOAA | ymFE | A | −1.05 [−1.88, −0.21] (150) | 0.089 | −1.52 [−2.27, −0.78] (202) | **yes** |
| sum358 | Open-Meteo | harm | P | −0.61 [−2.34, +1.16] (148) | 0.79 | −1.51 [−3.39, +0.41] (158) | no |
| sum358 | Open-Meteo | harm | A | −1.27 [−3.01, +0.50] (183) | 0.45 | −0.99 [−2.52, +0.56] (258) | no |
| sum358 | Open-Meteo | ymFE | P | −1.77 [−3.06, −0.47] (148) | 0.081 | −1.84 [−3.10, −0.57] (158) | **yes** |
| sum358 | Open-Meteo | ymFE | A | −2.17 [−3.32, −1.00] (183) | 0.020 | −1.89 [−2.86, −0.91] (258) | **yes** |
| sum358 | NOAA | harm | P | +0.16 [−1.80, +2.16] (114) | 0.92 | −2.53 [−4.11, −0.92] (127) | no |
| sum358 | NOAA | harm | A | −0.71 [−2.65, +1.28] (150) | 0.79 | −1.87 [−3.21, −0.51] (202) | no |
| sum358 | NOAA | ymFE | P | −1.63 [−2.84, −0.41] (114) | 0.081 | −2.92 [−4.29, −1.52] (127) | **yes** |
| sum358 | NOAA | ymFE | A | −2.12 [−3.24, −0.98] (150) | 0.020 | −2.56 [−3.55, −1.56] (202) | **yes** |
| zip710 | Open-Meteo | harm | P | −0.35 [−2.05, +1.37] (148) | 0.84 | −1.16 [−2.98, +0.71] (158) | no |
| zip710 | Open-Meteo | harm | A | −0.89 [−2.61, +0.86] (183) | 0.64 | −0.88 [−2.30, +0.56] (258) | no |
| zip710 | Open-Meteo | ymFE | P | −1.41 [−2.53, −0.27] (148) | 0.090 | −1.62 [−2.68, −0.56] (158) | **yes** |
| zip710 | Open-Meteo | ymFE | A | −1.93 [−2.94, −0.90] (183) | 0.020 | −1.65 [−2.47, −0.82] (258) | **yes** |
| zip710 | NOAA | harm | P | +0.44 [−1.50, +2.41] (114) | 0.84 | −2.02 [−3.50, −0.52] (127) | no |
| zip710 | NOAA | harm | A | −0.45 [−2.38, +1.51] (150) | 0.84 | −1.63 [−2.86, −0.38] (202) | no |
| zip710 | NOAA | ymFE | P | −1.39 [−2.45, −0.31] (114) | 0.085 | −2.50 [−3.71, −1.28] (127) | **yes** |
| zip710 | NOAA | ymFE | A | −2.01 [−3.00, −1.01] (150) | 0.020 | −2.24 [−3.12, −1.35] (202) | **yes** |

**Factor summary** (mean % over the cells at each level; FOUND count):

| factor | level | mean train % | mean holdout % | FOUND |
|---|---|---|---|---|
| **seasonality** | harmonics k=2 | −0.32 | −1.37 | **0 / 12** |
| | year-month FE | −1.57 | −1.92 | **11 / 12** |
| source | Open-Meteo | −1.13 | −1.30 | 6 / 12 |
| | NOAA | −0.77 | −2.00 | 5 / 12 |
| split | P (pooling dates) | −0.70 | −1.80 | 5 / 12 |
| | A (aggregate dates) | −1.19 | −1.49 | 6 / 12 |
| unit | panel358 / sum358 / zip710 | −0.57 / −1.26 / −1.00 | −1.22 / −2.01 / −1.71 | 3 / 4 / 4 |

Within year-month FE, NOAA and Open-Meteo have about the same train effect (−1.52% vs −1.62%). On holdout NOAA is larger (−2.26% vs −1.59%).

**Why harmonics lose the effect.** Under harmonics, the month-mean residual has an SD of 6–8%, against a daily residual SD of 8–10%: most of the leftover variation is month-level drift in the Dewey series. Wetter months happen to sit above the harmonic curve (corr(month wet share, month residual) = +0.19 to +0.40 in every window). That pulls the rain coefficient toward 0 and roughly doubles its SE. Adding a linear trend does not help (train −0.6% to +0.6%, CIs still include 0). Year-month FE compares wet days with dry days in the same month, which removes this confounding. Harmonics are already negative on holdout (−1 to −2.5%) because the confounding correlation is weaker there (+0.19 to +0.25).

**Which disagreement days matter** (diagnostic, not in the BH family; zip710, year-month FE, A split):

| days | train | holdout |
|---|---|---|
| both sources wet | −2.21% [−3.31, −1.10] (n = 142) | −2.33% [−3.28, −1.37] (n = 189) |
| Open-Meteo only | −1.25% [−2.58, +0.09] (n = 41) | **+0.46%** [−0.51, +1.44] (n = 69) |
| NOAA only | −1.87% [−5.29, +1.67] (n = 8) | +0.57% [−1.30, +2.48] (n = 13) |

On holdout, the extra wet days that Open-Meteo adds behave like dry days. That dilutes its effect, which is why NOAA's holdout effect is larger.

## Part 2: round-1 single-business refits with NOAA weather

Design: `features.build` + `exposure.build_design(event_flags(hot=85))` + `fit_ols` (HC3), train = the first 365 days (2024-10-01..2025-09-30), holdout refit on 2025-10-01..2026-08-31. Values are $/day [90% CI]. The repo-weather rows reproduce round 1 exactly.

| business | weather | event | train $ [90% CI] (n) | BH q | holdout $ [90% CI] (n) |
|---|---|---|---|---|---|
| bar p_afa556030e60 | repo Open-Meteo | rain | −345 [−992, +301] (148) | 0.64 | −291 [−1,277, +694] (158) |
| bar | NOAA | rain | −442 [−1,104, +221] (114) | 0.49 | +281 [−697, +1,259] (127) |
| bar | repo Open-Meteo | hot > 85 | −118 [−1,205, +969] (55) | 0.92 | −837 [−2,156, +482] (45) |
| bar | NOAA | hot > 85 | +237 [−744, +1,218] (37) | 0.84 | −731 [−2,127, +666] (29) |
| taxi | repo Open-Meteo | rain | **+2,212 [+533, +3,890]** (148) | 0.081 | +303 [−1,823, +2,430] (158) |
| taxi | NOAA | rain | **+2,489 [+765, +4,212]** (114) | 0.070 | +774 [−1,359, +2,907] (127) |
| taxi | repo Open-Meteo | hot > 85 | **+3,967 [+1,281, +6,654]** (55) | 0.069 | −965 [−3,872, +1,941] (45) |
| taxi | NOAA | hot > 85 | **+5,490 [+2,389, +8,591]** (37) | 0.023 | −157 [−3,455, +3,140] (29) |

The bar's home_win is unchanged by weather: −$2,025 [−4,341, +291].

**Extra check (exploratory, 8 more fits, not in the BH family): the same refits with year-month FE in place of the harmonics.**
- **Bar:** still null everywhere. Rain: −$394 train / +$292 holdout. Hot: −$453 / −$601. Every CI includes 0.
- **Taxi rain:** goes to 0 (−$61 train with NOAA).
- **Taxi hot:** stays significant on train (+$5,484) but is +$283 [−3,054, +3,619] on holdout.

So the fix that rescues the venue aggregates does nothing for the single businesses.

**NOAA rescues no round-1 null and does not fix the taxi.** With NOAA, taxi's train effects get larger (hot +$5,490 on 37 days), but they still collapse on holdout (rain +$774, hot −$157, both CIs include 0). The instability is not caused by the weather source.

## Verdicts

| candidate | verdict |
|---|---|
| Near-MSG rain, venue aggregates, year-month FE (any source, any split) | **FOUND** in 11 / 12 cells (the exception, panel358 / NOAA / P, has BH q 0.118). The effect is about −1 to −2% on train and −1.2 to −2.9% on holdout. |
| Near-MSG rain, harmonics k = 2 | NOT FOUND (0 / 12) |
| Bar p_afa556030e60, rain / hot, NOAA | NOT FOUND |
| Taxi rain / hot, NOAA | NOT FOUND (passes train, fails holdout) |

**Tests:** 32 in the BH family, plus 6 decomposition fits, 8 harmonics + trend fits and 8 year-month FE round-1 fits, all reported as diagnostics only. Nothing was tuned on holdout.

**Is the near-MSG rain effect real?** Yes. It is a within-month effect of about −1.5 to −2.5% of visits on Central Park rain days, and it holds:
- on two different venue sets
- on panel and basket fits
- on both splits
- with both weather sources

r2-pooling's null comes from its harmonic seasonality, not from Open-Meteo or its dates. The effect is still small: r2-aggregate's backtest cut holdout residual SD by only 1.6–2.4%. It is not detectable in any single venue, including the demo bar.

**Which weather source?**
- **Production settlement:** NOAA GHCN USW00094728 PRCP ≥ 0.01 in. This is the record KXRAIN actually settles on. Open-Meteo, at either the MSG or the CP grid cell, agrees with it on only 85–90% of days and over-calls rain: 40–47% wet days vs 31–38%. The current `add_settlement` (Open-Meteo at CP) would misprice p̂ by about 9 points.
- **Feature flags:** also NOAA. The extra wet days that Open-Meteo adds carry no visit effect on holdout, NOAA's holdout effect is larger (−2.26% vs −1.59% under year-month FE), and the flag then equals the settlement flag, so the basis is 1.
- **Hot:** settle on the NOAA TMAX integer with a strict `>` strike.
- **Model change (larger than the source change):** the exposure model's k = 1, 2 harmonics leave month-level drift that confounds rain. Use year-month (or month) fixed effects, or a trend plus month dummies, before trusting any weather beta.

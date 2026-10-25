# R7 fidi: stock-market moves, Fed/CPI surprises and Financial District bars

**Question.** Do big S&P 500 days, or Fed/CPI surprises, move after-work traffic at Financial District and Midtown East bars and restaurants? If so, a Kalshi S&P range, Fed or CPI contract could hedge it.

**Short answer: NOT FOUND.** We ran 39 train tests (3 baskets × 13 terms). None survives BH at 10% (the smallest BH q is 0.22), and none replicates in the holdout with the same sign. The terms that are significant in train (S&P return, VIX change, FOMC days) are equally significant in the **residential placebo**, and they flip or vanish in the holdout. Big market days (|return| > 1.5%, 27 train / 38 holdout days) leave FiDi visits within about ±3% in the holdout, and the CI includes zero. No hedge is sized.

## Mechanism (stated before fitting)
A big S&P move, or a Fed/CPI print that surprises the market, changes Wall Street's mood and hours: late nights at the desk on crash days, celebrating on rally days. That should change same-evening and next-evening visits to bars and full-service restaurants near trading floors (FiDi, Midtown East). It should not change anything in a residential neighborhood (UWS/UES). Expected signs were ambiguous ahead of time (crash: fewer visits if people stay at the desk, more if they drink to cope), so tests are two-sided.

## Data
- **Visits:** raw Dewey weekly patterns → daily, balanced panel (stores present in all weeks, <5% flat weeks), NAICS 722410 (drinking places) + 722511 (full-service restaurants), summed per ZIP basket. Store counts: **FiDi** (10004, 10005, 10006, 10038, 10280) 242; **Midtown East** (10017, 10022) 538; **residential placebo** (10025, 10028) 410. Only basket sums are used. Dates run 2024-01-01..2026-09-27.
- **Market:** FRED SP500 (log close-to-close return, %) and VIXCLS (daily change). Weekends and market holidays get return 0 plus a `trading` control.
- **FOMC:** dates from Kalshi KXFEDDECISION settlement times. A surprise is a decision whose bracket traded below 0.75 thirty minutes before close. There was only one per period: 2024-09-18 (50 bp cut, priced at 0.43) and 2026-07-29 (hold, priced at 0.715).
- **CPI:** dates from Kalshi KXCPI settlement times. The implied median comes from the "greater than k" ladder 30 min before close, using mid quotes, skipping empty books (spread > 0.15) and enforcing monotonicity. A surprise is |released MoM − implied median| ≥ 0.1 pp. Counts: train 10 surprise / 5 not; holdout 8 / 10. Every 2026 print except June landed on the implied median. `macro_events.csv` lists them.
- **Weather:** GHCN Central Park (USW00094728), with flags for PRCP ≥ 0.01 and ≥ 0.5 in, plus tmax and tmax².

## Method
log(basket visits) ~ DOW + year-month FE + holiday + rain + heavy rain + tmax + tmax² + trading-day + event terms, HAC(7), z = 1.645. There are four separate model families:
- **move:** big_up / big_down (same day, return > +1.5% / < −1.5%), plus the same flags on the next calendar day.
- **macro:** FOMC surprise / no surprise, CPI surprise / no surprise.
- **weekday:** |return| > 1.5% on Mon–Wed vs Thu–Fri.
- **cont:** return, |return|, ΔVIX.

Train runs 2024-01-01..2025-03-31 and holdout 2025-04-01..2026-09-27, each fitted independently. BH at 10% covers all 39 train tests, placebo included. Falsification uses three checks: the residential basket, a permutation test (event days reshuffled among trading days, 300 draws) for every train-significant business term, and a FiDi-minus-residential difference model (secondary, not counted in BH).

## Results (% change in daily visits, 90% CI, n = event days)

| basket | term | train | holdout | BH q (train) | verdict |
|---|---|---|---|---|---|
| FiDi | big_up | −1.78 [−3.93, +0.37] (11) | −0.79 [−3.50, +1.93] (18) | 0.45 | NOT FOUND |
| FiDi | big_down | −1.46 [−4.33, +1.40] (16) | −0.21 [−2.19, +1.78] (20) | 0.74 | NOT FOUND |
| FiDi | big_up_next | +1.32 [−1.77, +4.41] (11) | +0.95 [−1.44, +3.33] (18) | 0.75 | NOT FOUND |
| FiDi | big_down_next | +1.30 [−1.18, +3.79] (16) | −0.07 [−3.24, +3.10] (20) | 0.74 | NOT FOUND |
| FiDi | big move Mon–Wed | −0.67 [−2.69, +1.34] (13) | −0.96 [−3.39, +1.46] (19) | 0.84 | NOT FOUND |
| FiDi | big move Thu–Fri | −2.83 [−6.35, +0.69] (14) | −0.01 [−2.07, +2.04] (19) | 0.45 | NOT FOUND |
| FiDi | FOMC, no surprise | **+3.54 [+1.27, +5.81] (9)** | +1.57 [−1.02, +4.15] (11) | 0.22 | NOT FOUND (no holdout, perm p 0.10) |
| FiDi | FOMC surprise | −1.85 [−5.55, +1.84] (1) | −1.48 [−3.59, +0.62] (1) | 0.74 | n = 1 |
| FiDi | CPI surprise | −0.37 [−2.36, +1.62] (10) | +1.73 [+0.25, +3.22] (8) | 0.95 | NOT FOUND (sign flips) |
| FiDi | CPI no surprise | −0.03 [−3.62, +3.56] (5) | −0.34 [−2.24, +1.56] (10) | 0.99 | NOT FOUND |
| FiDi | return (per 1%) | **−1.28 [−2.25, −0.32]** | +0.53 [−0.47, +1.53] | 0.22 | NOT FOUND (flips) |
| FiDi | ΔVIX (per pt) | **−0.60 [−1.04, −0.17]** | +0.27 [−0.18, +0.72] | 0.22 | NOT FOUND (flips) |
| Mid East | FOMC, no surprise | **+4.19 [+0.37, +8.01] (9)** | −0.01 [−1.88, +1.87] (11) | 0.30 | NOT FOUND |
| Mid East | return | **−1.24 [−2.24, −0.25]** | −0.24 [−1.04, +0.56] | 0.22 | NOT FOUND |
| Mid East | ΔVIX | **−0.66 [−1.10, −0.21]** | −0.06 [−0.48, +0.35] | 0.22 | NOT FOUND |
| Mid East | big_down_next | +0.86 [−1.48, +3.20] (16) | +2.15 [+0.39, +3.90] (20) | 0.82 | NOT FOUND (train n.s.) |
| **Placebo** | return | **−0.62 [−1.20, −0.04]** | +0.17 [−0.48, +0.81] | 0.30 | (placebo) |
| **Placebo** | ΔVIX | **−0.30 [−0.53, −0.07]** | +0.13 [−0.20, +0.47] | 0.22 | (placebo) |
| **Placebo** | big_down_next | **+2.61 [+0.43, +4.78] (16)** | **+1.82 [+0.32, +3.33] (20)** | 0.24 | (placebo, fails BH) |
| **Placebo** | big_up | **+1.62 [+0.05, +3.19] (11)** | −0.64 [−2.03, +0.75] (18) | 0.30 | (placebo) |

The full set of 39 rows is in `verdict.csv` and `results.csv`. Rows not shown are all n.s. in train.

**Counts:** 39 tests, 0 pass BH, 0 FOUND. 12 are train-significant at 90%, and 5 of those 12 are in the placebo basket. That is about what noise gives (39 × 0.10 ≈ 4 expected) plus a common market-wide/seasonal factor.

## Falsification
- **Placebo shows the same "effects".** Return and ΔVIX are significant in train with the same sign in FiDi, Midtown East *and* the residential basket, and all three vanish in the holdout. Whatever drove them in train (likely the 2024-08 / 2025-Q1 selloffs coinciding with month-level drift that year-month FE does not fully remove) is not specific to Wall Street. The one term whose CI excludes zero in both periods, big_down_next (+2.6% / +1.8%), is in the **placebo** basket, not FiDi. A replicating placebo with FiDi null is the opposite of the hypothesised chain.
- **Permutation:** FOMC-no-surprise days in FiDi give perm p = 0.10 (train) and 0.40 (holdout); in Midtown East, 0.05 and 1.00. With n = 9 FOMC days and DOW/month FE, this is a mid-week Wednesday cluster, not a Fed effect, and it does not hold up.
- **FiDi − residential difference (secondary):** big_up −3.4% [−5.1, −1.7] in train goes to −0.1% [−2.7, +2.4] in holdout. Thu–Fri big move −4.5% [−6.9, −2.0] goes to −0.9% [−3.2, +1.5]. CPI surprise −1.8% goes to +1.9%. Nothing replicates. The FOMC-surprise rows (−5.8% / −7.8%) rest on one day each, so their tight HAC CI is a single-day residual and not evidence.

## What the null rules out
FiDi holdout SEs are about 1.2–1.5% on big-move flags, so after-work effects larger than about ±3% on |return| > 1.5% days are unlikely. For a typical FiDi bar/restaurant (≈ 200 Dewey visits/day × $35 ≈ $7k/day, using the same CHECK convention as earlier rounds), that bounds the exposure at roughly ±$200 per big day, or ±$4–8k per year at 20–40 big days a year. The true effect is consistent with zero.

## Kalshi mapping (for the record; no hedge, since NOT FOUND)
- **|S&P return| > 1.5%:** KXINX (daily S&P 500 close, range and threshold strikes) settles on the official close, so a strike at prior close × (1 ± 0.015) gives basis R² = 1 with our flag (same index, same close). KXINXU covers intraday/hourly closes.
- **FOMC surprise:** KXFEDDECISION (cut/hold/hike brackets). Its pre-meeting price was used to define the surprise.
- **CPI surprise:** the KXCPI MoM ladder, used to define the surprise, with KXCPICORE / KXCPIYOY as alternatives.

The contracts exist and settle cleanly. What is missing is a revenue exposure to hedge.

## Verdict
**NOT FOUND** for every candidate: same-day and next-day big up/down days, FOMC and CPI surprise vs no surprise, weekday interactions, and continuous return/VIX, in both FiDi and Midtown East. The residential placebo "moves" as much as the business districts, which points to shared noise or seasonal drift rather than a Wall Street channel. In this Dewey data, market moves do not show up in daily foot traffic at Financial District bars.

Caveat: Dewey visits are daily, not hourly, so an after-work shift (for example, a later crowd on crash days with the same total) would not be visible. Limited-service (722513, lunch-heavy) was left out on purpose, to keep the test count down.

## Files
- `fetch.py`: FRED SP500/VIXCLS, Kalshi KXFEDDECISION/KXCPI markets and hourly candles → `r2-cache/r7fidi_*`.
- `run.py`: baskets, event flags, fits, BH, permutation and difference models.
- `macro_events.csv`: FOMC/CPI dates with implied vs released values (public data).
- `results.csv`, `verdict.csv`, `permutation.csv`, `did.csv`: coefficient tables (aggregates only).

# R5 playoffbars: Manhattan bars on Knicks/Rangers playoff nights

**Question.** Do bars fill up citywide on playoff nights, home and away (watch parties), so that a deep run adds busy nights across Manhattan and not only near MSG? If so, what is at stake per round, and can a Kalshi advancement contract hedge it?

**Short answer: no, it goes the other way.** On Knicks/Rangers **away** playoff nights, visits to Manhattan drinking places fall by about **3.5%**. This holds in train (2024–25 runs) and in holdout (2026 run), survives BH, and survives a week-FE refit and a permutation placebo. Home playoff nights are flat citywide. Near MSG the arena effect shows up as expected: full-service restaurants within 0.5 km gain **+7%** on home playoff nights (replicates), and bars within 0.5 km gain +3% (not significant, 31 stores). For a typical Manhattan bar, then, a deep run is a small *cost*, about a quarter of one day's revenue over a whole run. The hedge goes the opposite way from the brief: buy **YES** on "NYK wins the series". In the backtest that halves the variance of playoff-season revenue, but the dollars involved are small.

## Data
- **Visits:** raw Dewey weekly patterns → daily, 2024-01-01..2026-09-27, using the balanced panel from r2-aggregate (stores present in all 143 weeks, <5% flat weeks). Baskets (store counts): drinking places NAICS 722410: all 976, ≤0.5 km from MSG 31, 0.5–2 km 349, >2 km 596. Full-service 722511: all 7,819, ≤0.5 km 176. Only basket sums are used. No venue ids, names or per-venue series are written.
- **Games:** ESPN team schedules (`teams/ny`, `teams/nyr`, seasontype 2 and 3, seasons 2024–2026), tip-off converted to an ET local date. `games.csv` lists them (public data). Playoff nights by run (home/away): Knicks 2024 R1–R2 7/6; Rangers 2024 R1–ECF 8/8; Knicks 2025 R1–ECF 9/9; Knicks 2026 R1–Finals (won the title 4-1 over SAS) 9/10. Rangers missed the 2025 and 2026 playoffs. Playoff tips were almost all 19:00–20:30 ET, with a few weekend afternoons.
- **Weather control:** GHCN Central Park rain flag (≥0.01 in).
- **Kalshi:** pre-game-1 daily closes from r5-markets' cached `/historical/markets/{t}/candlesticks` (`r2-cache/r5markets_candles.json`). Kalshi has no NBA playoff markets for 2024.

## Method
log(basket visits) ~ DOW + year-month FE + holiday + rain + {reg-season home, reg-season away, playoff home, playoff away} (either team), HAC(7), z = 1.645. A second model replaces the playoff flags with round flags R1–R4. The two periods are fitted independently: **train** 2024-01-01..2025-09-30 (Knicks 24, Rangers 24, Knicks 25) and **holdout** 2025-10-01..2026-09-27 (Knicks 26). BH at 10% runs over all **42** train tests (6 baskets × 7 terms). The playoff-vs-regular-season contrasts (Wald tests) are secondary and not included in the BH count.

## 1. Uplift (main model; % change in daily visits)

| basket | term | train % [90% CI] (n) | holdout % [90% CI] (n) | BH (train) | verdict |
|---|---|---|---|---|---|
| bars, all Manhattan | playoff **away** | −3.4 [−5.3, −1.6] (22) | −3.5 [−5.7, −1.2] (10) | 0.039 | **FOUND (negative)** |
| bars, all | playoff home | −0.3 [−2.0, +1.4] (24) | −1.1 [−3.4, +1.1] (9) | 0.85 | not found |
| bars, all | reg-season home / away | +0.4 / +0.3 (n.s.) | −0.4 / +0.2 (n.s.) | 0.85 | not found |
| bars ≤0.5 km | playoff home | +3.3 [−0.6, +7.3] (24) | +1.7 [−2.3, +5.8] (9) | 0.40 | not found |
| bars ≤0.5 km | playoff away | −3.4 [−6.1, −0.6] | −2.8 [−8.4, +2.7] | 0.18 | not found |
| bars ≤0.5 km | reg-season home | +1.9 [−0.2, +3.9] | +1.5 [−0.8, +3.8] | 0.39 | not found |
| bars 0.5–2 km | playoff away | −3.7 [−5.9, −1.6] | −4.1 [−6.6, −1.5] | 0.039 | **FOUND (negative)** |
| bars >2 km | playoff away | −3.1 [−4.9, −1.2] | −2.8 [−5.2, −0.4] | 0.039 | **FOUND (negative)** |
| full-service, all | playoff away | −1.1 [−2.3, +0.0] | −1.1 [−2.9, +0.7] | 0.34 | not found |
| full-service ≤0.5 km | playoff **home** | **+7.3 [+4.9, +9.7]** | **+4.8 [+0.8, +8.9]** | 0.000 | **FOUND** |
| full-service ≤0.5 km | reg-season home | +3.2 [+1.3, +5.0] | +3.3 [+0.3, +6.3] | 0.039 | **FOUND** (as in r2-aggregate) |

Everything else (24 of the 42 train tests) is in `uplift.csv` and `verdict.csv`. In total 5 basket×term pairs are FOUND, and none of them is a citywide watch-party uplift.

**Playoff vs regular-season nights** (`contrasts.csv`): for bars, playoff away minus regular-season away = −3.8 [−6.0, −1.6] (train) and −3.7 [−6.0, −1.3] (holdout). Playoff home minus regular-season home ≈ 0. For full-service ≤0.5 km, playoff home exceeds regular-season home by +4.2 [+1.4, +7.0] in train but only +1.5 [−3.5, +6.5] in holdout, so that one did not replicate.

**Robustness** (citywide bars, all three seasons, not counted in BH):
- Week FE instead of year-month: playoff away −2.9 [−4.2, −1.7].
- Placebo (shuffle playoff-away nights within year-month, 300 draws): real t = −3.98 against a permuted |t| p95 of 2.09, perm p < 0.003.
- One run at a time, every run is negative on away nights: Knicks 24 −4.7 ± 3.0, Knicks 25 −2.0 ± 2.0, Knicks 26 −3.6 ± 2.3, Rangers 24 −4.9 ± 2.9.
- For full-service ≤0.5 km, home playoff nights are positive in every run (+5 to +9%), placebo p < 0.003.

**Does it grow by round?** No consistent pattern. For citywide bars the round coefficients are R1 −3.1, R2 −1.2, ECF −1.8, Finals −0.8 (Finals n = 5, holdout only). Bars ≤0.5 km hit +8.6% [+3.0, +14.2] on the 2026 Finals nights, but that is one series, 5 nights (2 home, 3 away) and impossible to replicate. Full-service ≤0.5 km rises with the round (R1 +0.6 → ECF +4.5 → Finals +5.6), which fits bigger home crowds, but the round CIs overlap.

**Reading.** The watch-party hypothesis is not what the device data shows. Citywide, people on away playoff nights seem to watch from home (or from venues Advan doesn't classify as 722410) rather than go out. Around MSG, home playoff nights draw crowds into restaurants, while nearby bars gain less and noisily. Caveat: Dewey visits are device-panel counts with a dwell threshold, not covers or receipts.

## 2. Exposure ($ at stake)
Assumed average check: **$35 per Dewey visit** (as in rounds 1–4). Baseline is the Apr–Jun no-game-night mean visits per store. The Dewey-scaled baseline is large (≈411 visits/day for a citywide bar, i.e. R ≈ $14.4k/day), so the % figures are more reliable than the $ figures. All $ scale linearly with R.

| basket | per playoff home night | per playoff away night | typical run (≈12–19 nights) |
|---|---|---|---|
| bar, citywide | −$74 [−272, +124] (−0.5%) | **−$507 [−716, −297] (−3.5%)** | −$3.3k to −$5.4k ≈ **−0.23 to −0.37 of one day's revenue** |
| bar ≤0.5 km | +$575 [−46, +1197] | −$676 [−1235, −117] | ≈ 0 (home and away cancel) |
| full-service ≤0.5 km | **+$627 [+425, +828]** | −$143 [−353, +68] | +$3.9k to +$4.8k |

Per round, an extra series is about 5.8 nights at an average of (a_home + a_away)/2 ≈ −1.9% for a citywide bar, i.e. about **−0.11 day of revenue per round advanced**. A bar doing $4k/day is looking at roughly −$450 per round. The uplift share near MSG versus elsewhere: the positive playoff effect sits entirely within 0.5 km (full-service +6.7%, bars +2.9%). Bars at 0.5–2 km and >2 km are only negative.

## 3. Hedge
**Contracts.** KXNBASERIES-{25DETNYK, 25NYKBOS, 26ATLNYKR1, 26PHINYKR2}-NYK (series winner, settles on NBA/ESPN), KXNBAEAST-{25,26}-NYK (wins the conference finals) and KXNBA-26-NYK (wins the Finals). Each pays a deterministic function of the advancement that creates the next round's nights. Pre-game-1 NYK YES closes:

| | 2025 | 2026 |
|---|---|---|
| R1 | 0.79 (DET) | 0.73 (ATL) |
| R2 | 0.15 (BOS) | 0.71 (PHI) |
| ECF | 0.60 (IND) | 0.71 (CLE) |
| Finals | — | 0.37 (SAS) |

These are last-trade closes. They match r5-markets' bid/ask mids at the same cutoff (`experiments/bar/r5-markets/focus_prices.csv`) to within 0.01. 2024 has no Kalshi market, so I priced it at an **assumed 0.60** per series. That is not a market price.

**Rule (myopic, re-set each round).** Before series k, the next round's nights are worth E[games | price] × (a_home + a_away)/2 × R, using effects from the **train** fit, so 2026 is out of sample. If that value is negative (citywide bars), buy YES "NYK wins series k" for that $ notional. If it is positive (full-service ≤0.5 km), buy NO. Cost is price + 0.07·p·(1−p). Neither the first round (that would need KXNBAPLAYOFF) nor series length within a round is hedged.

| basket | season | nights | unhedged $ | hedged $ |
|---|---|---|---|---|
| bar, citywide | 2024 | 13 | −3,284 | −3,648 |
| | 2025 | 18 | −4,857 | −4,215 |
| | 2026 (OOS) | 19 | −5,352 | −4,105 |
| | **SD across 3 runs** | | **1,080** | **301** |
| full-service ≤0.5 km | 2024 / 2025 / 2026 | | 3,886 / 4,797 / 4,642 | 4,143 / 4,050 / 3,281 |
| | SD | | 487 | 473 |

Simulated seasons (20k draws from the 2026 pre-series prices, 2-2-1-1-1, per-game p implied from each series price):
- **Citywide bar:** SD $1,729 → $864 (**ratio 0.50**); 5th percentile −$6,073 → −$5,213; mean cost −$50 (fees).
- **Full-service ≤0.5 km:** SD 0.59×; 5th percentile +$1,599 → +$2,686.
- **Bar ≤0.5 km:** ratio 1.0 (no net exposure to hedge).

**Verdict on the hedge.** It mechanically works, because the payout is tied to the same advancement that adds the nights. But with n = 3 runs (one of them on an assumed price), the backtest SD is anecdotal. The simulation is the real evidence, and it only shows that the hedge removes round-count variance, not that the variance is worth paying for. The stake per round is about 0.1 day of revenue.

## Honest limitations
- Playoff n is small: 22 away / 24 home nights in train, 10 / 9 in holdout. The Finals are a single 5-game series.
- Year-month FE compare playoff nights against same-month non-game nights. In May the Knicks played about every other day, so the comparison set is thin, though the week-FE refit agrees.
- Daily totals mix lunch and evening, so an evening-only bump smaller than the daytime drop would be hidden.
- The $ baseline comes from Dewey-scaled visit counts × an assumed $35, so treat the $ as illustrative and the % as the finding.
- The Kalshi 2025 and 2026 series used are all ones the Knicks won or reached; the price history covers only two runs.

Files: `run.py`, `games.csv`, `uplift.csv`, `contrasts.csv`, `verdict.csv`, `exposure.csv`, `hedge_backtest.csv`, `hedge_sim.csv`.

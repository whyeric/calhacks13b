# R5 sfplayoffs: SF meter revenue on Warriors/Giants playoff home games, and hedging advancement

**Question.** Do unscheduled home dates (play-in and playoff games) lift real SFMTA meter revenue near Chase Center and Oracle Park? If so, how many dollars ride on each round, and can a Kalshi advancement contract hedge them?

**Verdict**
- **Warriors at Chase: FOUND, with caveats.** The playoff home-game uplift is significant on train (2022) and replicates on the holdout (2023 + 2025), and it survives BH. The contracts that settle on advancement exist and are liquid: `KXNBAPLAYOFF` and `KXNBASERIES`.
  - The dollars are small. Across the 36 meter blocks it is about **$3.2k per game** and **$10–22k at stake per series**.
  - A playoff game is worth about the same as a regular-season game, not more.
- **Giants: NOT FOUND.** There are 3 playoff home games (2021 NLDS) and nothing to replicate on.
- **Placebo passes.** Warriors playoff games at Oracle Arena (Oakland, 2017–19) do not move SF meters.

## Data
- **Revenue:** SFMTA meter transactions (`imvp-dq3v`), daily `sum(gross_paid_amt)` for the blocks with a meter within 600 m of each venue.
  - `chase` is 36 blocks, `oracle` is 34.
  - Reused from r4-sfparking (cache `r4sf_rev_*`).
- **Games:** ESPN team schedules, season types 2 (regular), 3 (postseason) and 5 (play-in), dated by Pacific local time. Cached in `r5sfplayoffs_games_*`.
  - **Chase-era Warriors unscheduled home dates:**
    - 2021: 1 play-in (COVID crowds, excluded from all periods)
    - 2022: 12 playoff (title run)
    - 2023: 6
    - 2024: 0 (lost the 9–10 play-in away)
    - 2025: 1 play-in + 5 playoff
    - 2026: 0 (lost both play-in games away)
  - **2017–19:** 31 playoff home games at Oracle Arena. Used only as a placebo.
  - **Giants:** the only postseason from 2017 to 2026 is the 2021 NLDS (3 home games). There were none in 2024, 2025 or 2026.
- **Kalshi:** `/series`, `/markets` and `/historical/markets`, and `/historical/markets/{t}/candlesticks` (daily).

## Method
- **Model:** `log(rev) ~ year-month FE + DOW FE + holiday + gsw_reg + gsw_po + sfg_reg + sfg_po + oak_reg + oak_po`, on Mon–Sat with HAC(7). It uses the same gap filter as r4.
  - All game dummies are included together, so a playoff game on a Giants home day is not credited with the Giants lift.
  - `gsw_po` is a Warriors play-in or playoff home game at Chase.
  - `po − reg` is a within-model contrast.
  - The same model in $ levels gives $ per game.
- **Periods, each fitted independently:**
  - Train: 2022.
  - Holdout: 2023-01 to 2026-09.
  - Giants: 2021-06-15 to 2021-12.
  - Placebo: 2017-01 to 2019-08.
- **Multiple comparisons:** BH at 10% over all **22 tests**.
- **Exposure:** an exact best-of-7, 2-2-1-1-1 series distribution. The per-game probability is log5 on regular-season win% plus a home edge (logit +0.32, about 58%). Later-round opponents are generic (win% .62, .65, .66).
  - The $ at stake on a series is U × E[home games in all later rounds | win the series].
- **Hedge:** before the play-in (when the team isn't already in) and before each series, buy NO on "Warriors advance", sized at $ at stake / $1.
  - Contracts: `KXNBAPLAYOFF-yy-GSW`, then `KXNBASERIES-yy<matchup>-GSW`.
  - Price: the Kalshi YES bid on the last daily candle before game 1 (NO cost = 1 − bid). Where no market exists (2022–24), it's the model p + $0.02.
  - Fee: 0.07·p·(1−p) per contract.

## 1. Uplift per home game (log points)

| blocks | event | period | β [90% CI] | n games | p_BH |
|---|---|---|---|---|---|
| chase | **Warriors playoff** | train 2022 | **+0.351 [+0.146, +0.556]** | 11 | 0.010 |
| chase | **Warriors playoff** | holdout 23–26 | **+0.622 [+0.479, +0.765]** | 11 | <0.001 |
| chase | Warriors regular | train | +0.771 [+0.685, +0.856] | 34 | <0.001 |
| chase | Warriors regular | holdout | +0.669 [+0.616, +0.723] | 125 | <0.001 |
| chase | playoff − regular | train | −0.420 [−0.643, −0.196] | – | 0.004 |
| chase | playoff − regular | holdout | −0.048 [−0.197, +0.102] | – | 0.66 |
| oracle | Warriors playoff | train | +0.209 [+0.080, +0.339] | 11 | 0.015 |
| oracle | Warriors playoff | holdout | +0.227 [+0.110, +0.344] | 11 | 0.003 |
| chase | Giants NLDS 2021 | 2021 | +0.419 [+0.159, +0.679] | 3 | 0.015 |
| oracle | Giants NLDS 2021 | 2021 | +0.740 [+0.421, +1.058] | 3 | <0.001 |
| oracle | Giants NLDS − regular | 2021 | −0.285 [−0.609, +0.039] | – | 0.19 |
| chase | Oakland playoff (placebo) | 2017–19 | −0.044 [−0.105, +0.016] | 25 | 0.28 |
| oracle | Oakland playoff (placebo) | 2017–19 | −0.008 [−0.046, +0.031] | 25 | 0.74 |

The other rows (Giants regular, Oakland regular, the oracle contrasts) are in `output.txt`.

- **Replication passes.** Train and holdout are both positive, both CIs exclude 0, and n is 11 each, so ≥ 10.
- **A playoff game ≈ a regular game.** On the holdout the playoff and regular-season uplifts are the same (contrast −0.05, n.s.). In 2022 a playoff game was worth *less* than a regular one, about +42% vs +116%.
  - A plausible reason: 5 of the 12 dates in 2022 were also Giants home days, and the blocks near Chase hit meter capacity.
  - Use the regular-season uplift as the prior; playoff games are not a premium product for meters.
- **$ per game on the chase blocks (levels model):** train +$1,810 [604, 3,016], holdout +$4,496 [3,439, 5,554], pooled 2022–26 **+$3,220 (se $615)**. That is on a base of about $5k/day.
  - Per-date excess (revenue minus the same year-month × DOW non-game median) rose from about $2.3k/game in 2022 to $6.7k in 2023 and $8.3k in 2025, plausibly SFMTA event-rate pricing.
  - The pooled U is conservative for today.
- **Giants:** the 2021 NLDS lifted the oracle blocks by +$5.2k/game [2.9k, 7.6k], vs +$7.4k for a 2021 regular-season home game. With n = 3 and no later Giants playoffs, it cannot replicate: **NOT FOUND**.

## 2. $ at stake per round (chase blocks, U = $3,220/game)

| series setup | P(win) | E[home games] | P(H = 2 / 3 / 4) | $ this round |
|---|---|---|---|---|
| .65 vs .55, home court | 0.73 | 3.13 | .15 / .57 / .28 | $10.1k |
| .60 vs .60, home court | 0.53 | 3.20 | .12 / .56 / .32 | $10.3k |
| .60 vs .60, no home court | 0.47 | 2.63 | .37 / .63 / 0 | $8.5k |
| .50 vs .70, no home court | 0.12 | 2.43 | .57 / .43 / 0 | $7.8k |

The $ at stake on *winning* a series is the expected uplift from all later rounds:

| team regular-season wp | win R1 | win R2 | win WCF | whole run, E from R1 |
|---|---|---|---|---|
| .50 | $10.4k | $9.6k | $8.0k | $12.3k |
| .60 | $13.4k | $11.4k | $8.4k | $18.7k |
| .70 | $22.1k | $16.8k | $10.3k | $28.0k |

- **What happened:** realized excess on the chase blocks was $22.9k (2022, 12 dates), $40.4k (2023, 6), $0 (2024), $49.9k (2025, 6) and $0 (2026).
- **Scaling:** a business with its own uplift u per game multiplies by u / $3,220.

## 3. Kalshi basis
Every contract below pays a deterministic function of the same outcome that adds home dates.

| series | contract | Warriors / Giants markets | settle |
|---|---|---|---|
| `KXNBAPLAYOFF` | team qualifies for the playoffs (the play-in alone does not count) | GSW-25 yes, GSW-26 no, GSW-27 active | annual |
| `KXNBASERIES` | team wins the named series | 25GSWHOU GSW yes; 25GSWMIN GSW no | per round, listed about 2 days before game 1 |
| `KXNBAWCFQUAL` / `KXTEAMSINNBAWF` | reach the WCF | GSW-27 active; 26 matchup combos (no) | annual |
| `KXNBAWEST`, `KXNBA` | win the conference / title | GSW-25, -26 no; -27 active | annual |
| `KXNBASERIESGAMES`, `KXNBASERIESSCORE` | series length / exact score (fixes the home-game count given home court) | none for GSW (listed only for 2026 series) | per round |
| `KXMLBPLAYOFFS`, `KXMLBSERIES`, `KXMLBNL`, `KXMLB`, `KXTEAMSINWS` | MLB qualify / series / pennant / WS | SF-25, SF-26 playoffs: no | annual |
| `KXMLBPLAYOFFHOST` | **"team hosts ≥ N playoff games"**, the exposure itself | 2026 only, 5 teams, not SF | annual |

**Liquidity:**
- GSW series markets were tight and deep: R1 vs HOU 0.61/0.62 with 92k volume the day before; R2 vs MIN 0.36/0.37 with 256k volume.
- `KXNBAPLAYOFF-26-GSW` was 0.14/0.16 the day before the play-in.
- `KXNBAWEST-25-GSW` was 0.09/0.10 before the 2025 playoffs.
- Giants markets are thin. `KXMLBPLAYOFFS-25-SF` was 0.40/0.92 in July 2025, with open interest of 389.
- **Kalshi history starts in 2025.** Before that, no Warriors/Giants markets exist, so 2022–24 use model prices.

## 4. Hedge backtest (Warriors, Chase era, buy NO before each stage)

| season | outcome | realized excess | hedge P&L | hedged | price source |
|---|---|---|---|---|---|
| 2022 | won title (4 series) | $22,919 | −$18,755 | $4,165 | model |
| 2023 | won R1, lost R2 | $40,427 | −$2,331 | $38,096 | model |
| 2024 | lost play-in | $0 | +$2,650 | $2,650 | model |
| 2025 | play-in W, won R1, lost R2 | $49,914 | −$2,936 | $46,978 | **Kalshi** |
| 2026 | lost play-in | $0 | +$1,431 | $1,431 | **Kalshi** |
| **SD across 5 seasons** | | **$22,833** | | **$22,039 (−3%)** | |

- **The real backtest barely changes the SD.** Realized season revenue is driven more by $/game drift (2022 at $2.3k/game vs 2025 at $8.3k) and by series length than by advancement.
- **The 2022 hedge backfired.** The title run, the best outcome for home games, coincided with the lowest $/game, so the hedge premia nearly wiped it out.
- **Mean cost:** about $4k/season.

**Simulation** (20,000 seasons per profile, fair p + $0.02 + fee, per-game $ ~ N($3,220, $4,415 within-season SD)):

| profile | mean (unhedged → hedged) | SD | p5 | p95 |
|---|---|---|---|---|
| contender, wp .65, P(make) .97 | $22.3k → $20.8k | $15.8k → $12.0k (**−24%**) | $0 → $0.9k | $50.9k → $40.6k |
| middling, wp .57, P(make) .75 | $12.8k → $11.8k | $13.4k → $9.1k (**−32%**) | $0 → −$3.8k | $38.2k → $27.4k |
| bubble, wp .52, P(make) .40 | $5.3k → $4.6k | $9.6k → $5.7k (**−40%**) | $0 → −$5.5k | $25.7k → $14.3k |

- **Advancement flags explain about 42–64% of playoff-revenue variance** (1 − (hedged SD / unhedged SD)²).
- **The rest is series length plus per-game noise.** `KXNBASERIESGAMES`/`SCORE` could cover the series-length part where listed.
- **The hedge cuts SD 24–40% for about $0.7–1.6k/season of premium.**
- **It does not lift the 5th percentile for non-contenders.** Unhedged, the worst case is already "$0 extra", and the hedge converts that into a premium paid. It pays off only against a budget that already counts on expected playoff revenue.

## Caveats
- Playoff n is 11 + 11 dates. The $ uplift is three times larger on the holdout than on train; the sign and significance replicate, the size does not.
- "Revenue" is meter revenue for 36 blocks, which is small in $. A bar or lot would need its own u.
- Model prices for 2022–24 use a crude log5 model. Kalshi prices exist only for 2025–26.
- Kalshi series markets are listed after the matchup is set (about 2 days before game 1). A true *pre-playoff* hedge of later rounds has to use `KXNBAWCFQUAL`, `KXNBAWEST` and `KXNBA`, which are coarser.

## Demo
"Warriors make the playoffs: your block earns about $3k per home game. Before round 1, buy about 13k NO contracts on `KXNBASERIES-…-GSW` at the market price. If they're knocked out, the contracts pay what rounds 2–4 would have earned."

## Reproduce
`cd backend && .venv/bin/python ../experiments/bar/r5-sfplayoffs/sfplayoffs.py`

This reuses the r4 revenue cache. ESPN, Kalshi and standings data are cached as `r2-cache/r5sfplayoffs_*`. Full output is in `output.txt`.

# R5-NYCPLAYOFFS: what a Knicks/Rangers playoff run is worth to a bar near MSG, and hedging elimination

**Question.** How much does an MSG playoff home game lift nearby activity compared with a regular-season home game? What is a bar near MSG exposed to per playoff round? And do Kalshi advancement markets hedge the risk of an early exit?

**Data.**
- **Games:** ESPN team schedules (regular season + postseason, 2021-22 to 2025-26). MSG playoff home games: Knicks 2023 (5), 2024 (7), 2025 (9), 2026 (9; won the title over SA 4-1); Rangers 2022 (10), 2023 (3), 2024 (8). The Rangers missed the 2025 and 2026 playoffs (KXNHLPLAYOFF-25/26-NYR settled NO).
- **Series near MSG:**
  - `dewey_0p5km` and `dewey_zip`: Dewey daily visits summed over 277 balanced restaurant/bar stores within 0.5 km of MSG, and over the MSG ZIP basket. Same build as r2-aggregate, aggregates only, 2024-01 to 2026-09.
  - `mta_post`: 34 St-Penn entries 21-24h (r4-mtahourly cache), 2022-2024.
  - `taxi186`: TLC zone 186 daily fares (`features.build("taxi")`), 2024-10 to 2026-08.
- **Weather:** NOAA GHCN USW00094728 rain flag.
- **Kalshi:** live markets plus the `/historical/markets` archive, with daily candles (`fetch.py`).

**Method.** Each series is fit as log(y) on `reg` (regular-season MSG home game) and `po` (playoff MSG home game), with DOW, year-month FE, holiday and rain, using HAC(7) errors. For MTA, only evening games count; I add log(system entries in the same window) and a matinee dummy. Each series has a train period and an independent holdout refit:
- Dewey: 2024-01..2025-03 | 2025-04..2026-09
- MTA: 2022-23 | 2024
- Taxi: 2024-10..2025-09 | 2025-10..2026-08

There are 3 tests per series (po, reg, po − reg) × 4 series = **12 tests per period, 24 fits**, with BH at 10% within each period. A further 16 per-team-season playoff dummies (one full-sample fit per series) are descriptive replication and are not in the BH family. FOUND uses the r5 criteria. Run `fetch.py`, then `nycplayoffs.py`, from backend/.

## 1. Uplift per playoff home game

| series | test | train % [90% CI] | n | q | holdout % [90% CI] | n | q | verdict |
|---|---|---|---|---|---|---|---|---|
| dewey 0.5 km | **playoff** | **+5.7** [+4.0, +7.4] | 15 | <.001 | **+5.7** [+3.4, +8.1] | 18 | <.001 | **FOUND** |
| dewey 0.5 km | playoff − regular | **+3.4** [+1.2, +5.5] | 15 | .022 | **+3.5** [+0.4, +6.6] | 18 | .12 | **FOUND** |
| dewey 0.5 km | regular | +2.3 [+0.6, +4.0] | 126 | .036 | +2.2 [+0.0, +4.3] | 87 | .14 | FOUND (barely) |
| dewey ZIP | **playoff** | **+2.9** [+1.9, +4.0] | 15 | <.001 | **+2.9** [+1.7, +4.2] | 18 | <.001 | **FOUND** |
| dewey ZIP | playoff − regular | +2.0 [+0.5, +3.5] | 15 | .039 | +2.0 [+0.1, +3.9] | 18 | .13 | FOUND |
| dewey ZIP | regular | +1.0 [−0.2, +2.2] | 126 | .22 | +0.9 | 87 | .45 | NOT FOUND |
| MTA Penn 21-24h | playoff | **+28.1** [+23.5, +32.8] | 15 | <.001 | **+32.6** [+23.1, +42.8] | 12 | <.001 | **FOUND** |
| MTA Penn 21-24h | playoff − regular | −0.7 [−5.0, +3.8] | 15 | .80 | +0.6 [−7.0, +8.9] | 12 | .90 | NOT FOUND (same as regular) |
| MTA Penn 21-24h | regular | +29.0 [+25.4, +32.7] | 137 | <.001 | +31.8 [+26.9, +36.8] | 71 | <.001 | FOUND |
| taxi zone 186 | playoff | −1.3 [−3.8, +1.2] | 9 | .42 | −3.2 [−18.0, +14.3] | 9 | .82 | NOT FOUND (n < 10) |
| taxi zone 186 | playoff − regular | −5.5 [−8.9, −1.9] | 9 | .024 | −8.6 [−22.8, +8.3] | 9 | .46 | NOT FOUND |
| taxi zone 186 | regular | +4.4 [+1.3, +7.6] | 81 | .034 | +5.8 [+1.6, +10.3] | 79 | .057 | FOUND |

**Replication by season** (full sample, one dummy per team-season, % vs a non-game day):

| series | Rangers 2022 | Knicks 2023 | Rangers 2023 | Knicks 2024 | Rangers 2024 | Knicks 2025 | Knicks 2026 | pooled playoff | pooled regular |
|---|---|---|---|---|---|---|---|---|---|
| dewey 0.5 km | | | | +6.8 [4.5, 9.1] | +4.9 [2.3, 7.6] | +7.8 [4.8, 11.0] | +3.7 [0.9, 6.6] | **+5.8** [4.2, 7.4] (33) | +2.3 [1.0, 3.6] (213) |
| dewey ZIP | | | | +4.2 | +1.8 (n.s.) | +4.2 | +1.6 (n.s.) | +2.9 [2.0, 3.8] | +1.0 |
| MTA post | +22.1 | +33.9 | +38.1 | +42.1 | +21.9 | | | +29.4 [24.6, 34.3] (27) | +29.6 (208) |
| taxi 186 | | | | | | −1.1 (n.s.) | −3.8 (n.s.) | −2.5 (n.s.) | +5.2 [2.6, 7.9] |

- **Foot traffic near MSG rises about 2.5× more on playoff nights than on regular nights.** It is +5.8% within 0.5 km (vs +2.3%), and positive with the CI excluding 0 in all 4 team-seasons Dewey covers. The playoff premium over a regular night is +3.4 pts in train and +3.5 pts in holdout. My reading is that watch-party demand comes on top of the ticket holders.
- **The station count doesn't change.** Penn post-game exits are +29% on both kinds of night. The arena is full either way, so the extra playoff demand is people without tickets, not more people leaving MSG.
- **Taxi zone 186 shows no playoff lift.** The point estimate is −1 to −4%, and n = 9 per period, below the 10 the criteria require. The regular-season lift (+4–6%) replicates.

## 2. $ at stake per round (ASSUMED check and covers)

The revenue basis is foot-traffic uplift × average check, and **both inputs are assumptions**. I use the round-1 convention of a $35 average check and a scenario bar with 300 covers/night (about $10,500/night). The 0.5 km playoff uplift of +5.8% [4.2, 7.4] then gives **u ≈ $604 per playoff home game**, with a range of [$438, $772]. On the Dewey panel scale, the same uplift is +16.6 panel visits per store per game, about $580/store at $35. For a different bar, scale linearly: each 1% of nightly revenue is worth u/5.8.

The series maths uses best-of-7 with a 2-2-1-1-1 home pattern. Expected home games in a round are about 3.1–3.2 with home court and 2.5–2.6 without, and they barely depend on the series price. Losing a series means losing every later round's home games. With later rounds at 50/50:

| eliminated in | later home games lost (expected) | $ at stake (u = $604) |
|---|---|---|
| round 1 | 5.1 | $3,072 |
| round 2 | 4.4 | $2,633 |
| conference final | 2.9 | $1,755 |
| final | 0 | $0 |

Season playoff revenue by outcome (Monte Carlo from the 2026 pre-round prices): out in R1 (p = .28) ≈ $2.0k (3.3 home games); R2 (.21) $3.8k; conference final (.15) $5.7k; final (.23) $7.1k; title (.13) $7.1k. Across all outcomes, the mean is $4.8k and the SD $2.2k. This is **small money**: a deep run is worth about $7k, roughly 2% of one month's revenue ($315k) for a $10.5k/night bar.

## 3. Kalshi markets (basis)

Kalshi's sports series start in 2025. There are no Knicks/Rangers advancement markets for 2023 or 2024, in either the live or the historical archive. NY markets found (`kalshi_markets.csv`, 84 markets with daily candles):

| purpose | ticker | settles YES iff | NY prices before the round (yes bid/ask) |
|---|---|---|---|
| round winner | `KXNBASERIES-25DETNYK-NYK`, `-25NYKBOS-NYK`, `-26ATLNYKR1-NYK`, `-26PHINYKR2-NYK` | NY wins that series | 2025 R1 .78/.79, R2 .14/.15; 2026 R1 .72/.73, R2 .70/.71 |
| conference final | `KXNBAEAST-25-NYK`, `KXNBAEAST-26-NYK` | NY wins the East | before ECF G1: 2025 .59/.60, 2026 .70/.71 |
| final | `KXNBA-26-NYK` (also `-25`, `-27`) | NY wins the title | before Finals G1: .36/.37 |
| make playoffs | `KXNBAPLAYOFF-25/26/27-NYK`, `KXNHLPLAYOFF-25/26/27-NYR` | qualifies | NYR 25/26 settled NO |
| home-game count proxies | `KXNBASERIESGAMES-26*` (series goes 5/6/7), `KXNBASERIESSCORE-26*` (exact score), `KXNBAPLAYOFFWINS-26NYK-k` (≥ k playoff wins) | series length / wins | thin except in the Finals |
| NHL | `KXNHLEAST-*-NYR`, `KXNHL-*-NYR`, `KXNHLSERIES` (no NYR series: they missed both years) | | |

- **The basis is exact.** KXNBASERIES's rule is "If New York wins the X vs New York series… resolves Yes". Elimination in round k deterministically removes every later home game, so "NO on NY" pays in exactly the state where the bar loses those dates.
- The 2026 conference-final and Finals series markets for NYK are not in either the live or the historical archive. Once NY is in the conference final, KXNBAEAST is the same event, and once in the Finals, KXNBA is; I use those.
- Liquidity is ample for this size. The round markets traded 1.5–10.6M contracts, and KXNBA-26-NYK 72M. The spread is 1¢.
- The context is The Jeffrey's June 2026 hedge, as reported in the news. The owner put about $5k on the Knicks to win Finals Game 1 at about 37%, to cover a "free tab if the Knicks win" promotion. That exposure is self-created and depends on the **game result**, and a game-winner contract (KXNBAGAME) hedges it exactly. The exposure here is the organic one, **elimination**, and it needs the series and conference contracts above. Rounds 1–4 found game results don't move nearby demand, while game dates do.

## 4. Backtest: "hedge elimination risk"

Before each round, the bar buys "NY loses this round" (NO on the round market) at 1 − yes bid, plus the Kalshi fee of 0.07·q(1−q). The size is the $ of later home games that elimination removes (table above). Rounds with no market (2023, 2024, Rangers) use an **assumed** P: 0.75 for the home-court team in NBA, 0.60 in NHL.

**Realised runs (u = $604/home game):**

| run | home games | rounds won | revenue unhedged | hedge P&L | revenue hedged |
|---|---|---|---|---|---|
| Knicks 2023 (assumed P) | 5 | 1 | $3,020 | −$404 | $2,616 |
| Knicks 2024 (assumed P) | 7 | 1 | $4,227 | +$1,132 | $5,359 |
| Knicks 2025 (Kalshi) | 9 | 2 | $5,435 | −$1,993 | $3,442 |
| Knicks 2026 (Kalshi) | 9 | 4 | $5,435 | −$2,284 | $3,151 |
| Rangers 2024 (assumed P) | 8 | 2 | $4,831 | −$1,354 | $3,477 |

Over the 5 runs, the SD is $1,011 unhedged and $1,037 hedged, and the hedge P&L totals −$4,903. **The realised backtest does not show a benefit.** NY won 10 of 14 rounds. Insurance that pays on elimination costs its premium in the runs that go deep, so it can't look good over 5 seasons. Short series also cut the home-game count (2026: 4 rounds but only 9 home games after three sweeps or near-sweeps), and the round-level hedge doesn't cover that.

**Monte Carlo (20k seasons per run, drawn from the pre-round prices; hedge at fair price + fee):**

| run | mean unhedged → hedged | SD unhedged → hedged | 5th pct unhedged → hedged |
|---|---|---|---|
| Knicks 2023 | $2,510 → $2,449 | $1,896 → $547 (−71%) | $1,208 → $1,935 |
| Knicks 2024 | $4,754 → $4,659 | $2,049 → $660 (−68%) | $1,812 → $3,573 |
| Knicks 2025 | $3,348 → $3,295 | $1,333 → $776 (−42%) | $1,812 → $2,078 |
| Knicks 2026 | $4,780 → $4,691 | $2,183 → $692 (−68%) | $1,812 → $3,793 |
| Rangers 2024 | $4,137 → $4,044 | $2,239 → $629 (−72%) | $1,812 → $2,999 |

In simulation, the hedge removes 42–72% of the playoff-revenue SD and roughly doubles the 5th-percentile season. It costs $53–95 per season in fees. The 1¢ spread adds about the same again in the realised version.

## Verdict

- **Playoff home night → foot traffic within 0.5 km of MSG: FOUND.** It is +5.7% train and +5.7% holdout, positive in all 4 team-seasons, and **+3.4 pts above a regular home night** (FOUND, replicated). The MSG ZIP basket gives the same result at about half the size.
- **Playoff → Penn post-game entries: FOUND but not playoff-specific.** It is +28–33%, the same as a regular game.
- **Playoff → taxi zone 186: NOT FOUND** (n = 9 per period, point estimate ≤ 0).
- **Hedge:** exact basis (KXNBASERIES / KXNBAEAST / KXNBA, all deterministic in the advancement outcome), deep liquidity, and a 42–72% SD cut in simulation. The money involved is about $1.8–3.1k per round for a $10.5k/night bar (assumed). Realised 2023–26 runs lost $4.9k on the hedge because NY kept advancing, which is how insurance is supposed to behave. Kalshi prices exist only for 2025–26 (7 rounds), so the 2023–24 rows rest on assumed probabilities.
- **Tally:** 24 fits (12 train + 12 holdout), 8 of 12 candidates FOUND, plus 16 descriptive per-season estimates outside the BH family.

**Demo line.** "Playoff nights bring about 6% more people to the blocks around MSG, more than double a regular game, because fans without tickets come to watch nearby. You don't know how many playoff nights you'll get. Before each round, buy 'Knicks lose this series' for about $2–3k of contracts. If they're knocked out, the payout replaces the home nights you lost. If they advance, you paid a premium of about a quarter of that, and the extra nights cover it."

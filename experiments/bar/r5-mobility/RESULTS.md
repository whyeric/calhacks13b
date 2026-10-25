# R5-MOBILITY (playoffmobility): taxi, Uber/Lyft and subway on Knicks and Rangers playoff nights

**Questions.**
1. **Uplift:** how much does a playoff home night lift taxi/rideshare and subway activity at MSG, and how does that compare with a regular-season home night? Does the lift hold across seasons?
2. **Exposure:** how many dollars per playoff round are at stake for an MSG-area fleet or driver?
3. **Hedge:** does a Kalshi advancement hedge reduce the variance of playoff-season revenue?
4. **Reverse (natural hedge):** do playoff nights pull riders away from other neighbourhoods or modes?

**Data.** All public, aggregated only.
- **TLC trip records:** yellow + HVFHV (Uber/Lyft), hourly. Pickups, pickup driver gross and dropoffs for the MSG area: zone 186 Penn Station/Madison Sq West plus 100 Garment District and 164 Midtown South. Pickups for 11 nightlife zones (EV, LES, West/Greenwich Village, Union Sq, East Chelsea, Flatiron, Hell's Kitchen, Williamsburg N/S). Driver gross is fare + tip for yellow and driver_pay + tips for HVFHV.
  - **Sources:** 2022–25 from filtered SoQL `GROUP BY` queries on NYC Open Data. 2026 from duckdb httpfs over the TLC CloudFront parquet; it isn't on Open Data yet.
  - **Coverage:** Apr–Jun 2022–2026 only, 429 evenings. Unfiltered hourly SoQL took >10 min per HVFHV month and CloudFront returned 403 after a few months of reads, so the other season months were not all fetched.
  - **Citywide daily trips:** from the r2-taxi daily cache, 2022–25.
- **MTA hourly entries:** 34 St–Penn (complexes 164 + 318) and system-wide. 2022–24 from r4mh_*; 2025–Jun 2026 from `5wq4-mkjj` (new pull).
- **Games:** ESPN scoreboards, 2022–Jun 2026 (2026 newly fetched), with home/away, tip-off, round and game number.
  - **Playoff home games at MSG:** Rangers 2022 (10), 2023 (3), 2024 (8); Knicks 2023 (5), 2024 (7), 2025 (9), 2026 (9, the title run). That is 51 in total, 44 of them evening starts.
  - **Playoff away nights:** 44 evening ones.
- **Rain control:** GHCN-D USW00094728 PRCP ≥ 0.01 in (the KXRAIN flag).
- **Kalshi:** pre-series prices from r5-markets `series_quotes.csv`. KXNBASERIES / KXNHLSERIES resolve YES if the named team wins the series; source is the league/ESPN. They are listed from 2025, so only the 7 Knicks series of 2025–26 have real prices.

**Method.**
- **Model:** one row per evening. The outcome is the log of a fixed clock-window count. Regressors are `post_home` (playoff game at MSG, evening start 18–21h), `post_away` (playoff away game, no MSG game that day) and `reg_home` (regular-season or play-in MSG game). The `post_home − reg_home` contrast is also tested.
- **Controls and errors:** DOW, year-month FE, holiday and KXRAIN, with HAC(7) errors. Matinee-game days are dropped.
- **Windows:** pickups and Penn entries 21:00–00:59 (post-game exit wave); MSG-area dropoffs 17:00–19:59 (arrivals); nightlife pickups 19:00–02:59; system entries 19:00–00:59.
- **Periods:** train is 2022-01..2023-12 (Rangers 2022–23 and Knicks 2023 playoffs). Holdout is 2024-01..2026-06, refit independently.
- **Tests:** 7 outcomes × 4 contrasts × 2 periods = **56 tests**, with BH at 10% inside each period.
- **Code:** `fetch.py` (data), `games.py` (schedule), `mobility.py` (fits, exposure, report) and `hedge.py` (series model, backtest, simulation). Outputs are `output.txt`, `results.csv`, `by_season.csv`, `series.csv`, `backtest.csv` and `simulate.csv`.

## Q1: uplift (effect vs a non-game evening, 90% CI; q = BH)

| outcome | event | train | n | q | holdout | n | q | verdict |
|---|---|---|---|---|---|---|---|---|
| MSG-area pickups 21–01h | playoff home | **+15.1%** [+10.9, +19.5] | 15 | <.001 | **+12.9%** [+5.8, +20.5] | 29 | .008 | **FOUND** |
| | playoff − regular home | +9.9% [+4.1, +16.0] | 15 | .013 | +6.9% [+1.4, +12.6] | 29 | .073 | **FOUND** |
| | regular home | +4.7% [+0.4, +9.2] | 14 | .14 | +5.6% [+1.9, +9.6] | 22 | .028 | NOT FOUND (train q) |
| | playoff away | +5.4% [+1.7, +9.1] | 17 | .030 | −2.9% [−10.3, +5.2] | 27 | .64 | NOT FOUND |
| **MSG-area driver gross 21–01h** | **playoff home** | **+39.8%** [+31.0, +49.3] | 15 | <.001 | **+36.0%** [+27.8, +44.8] | 29 | <.001 | **FOUND** |
| | **playoff − regular home** | **+25.0%** [+14.8, +36.0] | 15 | <.001 | **+24.5%** [+16.4, +33.2] | 29 | <.001 | **FOUND** |
| | regular home | +11.9% [+6.0, +18.1] | 14 | .003 | +9.3% [+4.2, +14.5] | 22 | .008 | FOUND (scheduled) |
| | playoff away | +8.6% [+2.8, +14.8] | 17 | .030 | −1.3% [−8.3, +6.3] | 27 | .79 | NOT FOUND |
| MSG-area dropoffs 17–20h | playoff home | **+17.8%** [+14.3, +21.4] | 15 | <.001 | **+12.2%** [+4.8, +20.0] | 29 | .014 | **FOUND** |
| | regular home | +8.3% | 14 | .004 | +14.2% | 22 | <.001 | FOUND (scheduled) |
| | playoff − regular / away | +8.7% / −1.6% | | .016 / .71 | −1.8% / +0.9% | | .70 / .73 | NOT FOUND |
| **Penn subway entries 21–01h** | **playoff home** | **+28.2%** [+22.1, +34.6] | 15 | <.001 | **+38.9%** [+32.0, +46.1] | 29 | <.001 | **FOUND** |
| | regular home | +27.1% [+23.0, +31.3] | 121 | <.001 | +25.8% [+22.4, +29.4] | 174 | <.001 | FOUND (scheduled) |
| | **playoff away** | **+7.2%** [+2.3, +12.3] | 17 | .030 | **+12.9%** [+5.5, +20.8] | 27 | .010 | **FOUND** |
| | playoff − regular home | +0.9% | 15 | .89 | +10.3% | 29 | .008 | NOT FOUND (train) |
| *Reverse:* nightlife pickups 19–03h | home / away / reg / diff | −0.4 / −0.0 / −3.4 / +3.1% | | ≥ .26 | +1.3 / +3.0 / −1.4 / +2.7% | | ≥ .21 | NOT FOUND ×4 |
| *Reverse:* citywide TLC trips (day) | home / away / reg / diff | +0.5 / +1.5 / −0.3 / +0.8% | | ≥ .26 | −1.7 / −0.3 / +1.4 / −3.1% | | .02–.79 | NOT FOUND ×4 |
| *Reverse:* subway system 19–01h | home / away / reg / diff | +0.8 / +0.9 / +0.4 / +0.4% | | ≥ .71 | +3.0 / +1.3 / +1.2 / +1.7% | | .005–.52 | NOT FOUND ×4 |

**Tally:** 56 tests and 10 FOUND contrasts.
- **Hedgeable (6), in that the uncertain count of playoff home nights drives them:**
  - playoff-home pickups;
  - playoff-home driver gross;
  - playoff-home dropoffs;
  - playoff-home Penn entries;
  - playoff-minus-regular pickups;
  - playoff-minus-regular driver gross.
- **Playoff away → Penn (1):** FOUND, but small and tied to the same advancement outcome.
- **Scheduled, not risk (3):** the regular-season home effects on driver gross, dropoffs and Penn entries. Regular-season home pickups fail train q.

**Across seasons (descriptive, one dummy per playoff season, full sample).** Playoff-home lift by season:

| season | driver gross | pickups | Penn |
|---|---|---|---|
| 2022 | +33% | +9% | +21% |
| 2023 | +47% | +21% | +39% |
| 2024 | +40% | +16% | +36% |
| 2025 | +38% | +17% | +47% |
| 2026 | +35% | +11% (CI crosses 0) | +34% |

**Every season is positive, and every CI excludes 0 except 2026 pickups.**

**What this means.**
- **Playoff nights are worth more per trip than regular-season nights.** Pickups rise only +13–15%, but driver gross rises +36–40%. Gross per pickup goes from $24.85 to $30.10 (+21%). Surge pricing plus longer trips (fans heading to NJ, LI and the outer boroughs) make a playoff night about **+25% more lucrative than a regular-season MSG night**, in both periods. Penn subway entries show the same picture in holdout (+39% playoff vs +26% regular).
- **There is no natural hedge.** Playoff nights, home or away, don't measurably drain nightlife-zone pickups, citywide trips or system subway ridership. The MSG-area gain is additive and isn't offset elsewhere in the same modes. A citywide fleet doesn't get cover from other neighbourhoods losing riders.
- **Away playoff nights bring people to Penn but not to taxis.** Penn post-game entries rise +7–13% on away nights, consistent with watch parties near MSG. MSG-area taxi pickups and driver gross don't replicate (holdout −3% / −1%).

## Q2: dollars at stake

The per-game uplift comes from a pooled 2022–26 fit, n = 44 evening playoff home games. The baseline is the average Apr–Jun non-game evening.

| unit | baseline / evening | uplift per playoff home game [90% CI] |
|---|---|---|
| MSG-area TLC driver gross, all drivers | $117k | **$44.8k** [$37.6k, $52.3k] (+38%) |
| Penn entries × $2.90 (transit fare revenue) | $29.0k | $10.1k [$8.6k, $11.6k] (+35%) |
| **10-car fleet** working MSG pickups 21–01h | — | **$666** |
| **single driver** | — | **$67**; $42 from higher pay on the same 8 trips |

The fleet assumes a constant share: 10 cars × 2 trips/hr × 4 h = 80 of the 5,379 game-night area pickups.

**Per-round stake** is the value of advancing out of round r: U × the expected later home games. Later rounds are priced at 50/50, with E[home games per series] = 2.91.

| unit | R1 | R2 | R3 (conf. finals) |
|---|---|---|---|
| all MSG-area drivers | $228k | $195k | $130k |
| 10-car fleet | $3.4k | $2.9k | $1.9k |
| single driver | $339 | $291 | $194 |
| Penn transit | $51k | $44k | $29k |

**The home-game count is skewed.** Once in R1 with a coin-flip team, total MSG playoff home games are 2–4 with 50% probability, and 8–13 with 25%. Realized NY counts were 3–10 per team-season.

## Q3: hedge (buy "opponent wins series" before each round)

The hedge holds N_r = the round-r stake in YES contracts. Price is the pre-series Kalshi price + $0.01 + fee 0.07·p·(1−p), or 0.5 for 2022–24. The contract pays exactly when the later home games disappear. The remaining basis is series length and home-court within a round.

**Backtest, 7 NY playoff team-seasons (10-car fleet; the other units scale linearly):**

| team-season | home games | revenue | hedge cost | payout | hedged |
|---|---|---|---|---|---|
| Rangers 2022 | 10 | $6,662 | $4,344 | $1,938 | $4,256 |
| Rangers 2023 | 3 | $1,999 | $1,789 | $3,391 | $3,601 |
| Knicks 2023 | 5 | $3,331 | $3,322 | $2,906 | $2,916 |
| Rangers 2024 | 8 | $5,330 | $4,344 | $1,938 | $2,923 |
| Knicks 2024 | 7 | $4,663 | $3,322 | $2,906 | $4,248 |
| Knicks 2025 (priced) | 9 | $5,996 | $4,173 | $1,938 | $3,760 |
| Knicks 2026 (priced) | 9 | $5,996 | $2,589 | $0 | $3,407 |

- **SD across seasons: $1,540 → $512 (−67%).**
- **Worst season: $1,999 → $2,916.**
- **The realized mean fell $4,854 → $3,587.** The 2022–24 series were priced at 0.5 while NY mostly advanced, and the 2025 R2 hedge bought "BOS wins" at 0.855 and lost. That cost is realized luck plus favourite pricing; the expected cost is the spread and fee.

**Simulation (20,000 playoff runs at the same prices):**

| scenario | SD unhedged → hedged | 5th percentile | expected cost |
|---|---|---|---|
| coin-flip team | $2,090 → $562 (−73%) | $1,332 → $2,916 | $139 (≈3% of mean) |
| Knicks 2026 prices | $2,447 → $772 (−68%) | $1,999 → $4,073 | $159 |
| Knicks 2025 prices | $1,453 → $844 (−42%) | $1,999 → $2,229 | $129 |

**Not covered:** making the playoffs at all. Rangers 2025 and 2026 missed, with zero playoff home nights. A pre-season NO on KXNHLPLAYOFF-26-NYR would have covered that: it was at 0.65 in Sep 2025 and 0.36 on Jan 1. It wasn't backtested here because there is only one priced miss.

## Verdict
- **Playoff home night → MSG-area taxi/HVFHV driver gross: FOUND.** +40% train, +36% holdout, every season 2022–26 positive. It is about +25% above a regular-season MSG night, so the playoff premium is real and not just "a game happens".
- **Playoff home night → pickups (+15% / +13%), pre-game dropoffs (+18% / +12%) and Penn post-game entries (+28% / +39%): FOUND.**
- **Playoff away night → Penn entries: FOUND (+7% / +13%). → MSG-area taxis: NOT FOUND.**
- **Natural hedge from other neighbourhoods or modes: NOT FOUND (0/12).** Playoff nights don't measurably pull riders off nightlife zones, citywide TLC or the system subway.
- **Exposure and hedge:** the count of playoff home nights is the risk; per night it is about $45k market-wide, $666 for a 10-car fleet or $67 per driver. A per-round KXNBASERIES/KXNHLSERIES "opponent wins" hedge cuts season-revenue SD by **42–73%** in simulation and 67% in the 7-season backtest, at about 3% of expected revenue. Basis is clean (settles on the series winner). The caveat is that real prices exist only for 2025–26 (7 series).
- **Caveats:**
  - Playoff n is small (15 train / 29 holdout evenings).
  - TLC covers Apr–Jun only, so `reg_home` there is April regular-season nights (n = 14 / 22).
  - The fleet/driver dollars rest on a stated constant-share assumption.
  - Daily zone-186 fares (r5-nycplayoffs) dilute this signal to null. The post-game hourly window is what resolves it.

**Demo.** "You drive Uber near Penn Station. A Knicks playoff home night pays about 21% more per trip than a normal evening, and about 25% more than a regular-season Knicks night. But you don't know how many there will be: 3 or 10. Before each series, buy the 'opponent wins' contract sized to the next round's nights. If the Knicks go out, the contract pays what you lose; if they keep winning, you earn the playoff nights."

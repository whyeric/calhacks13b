# R4-MTAHOURLY: MSG games and rain timing in MTA Subway hourly ridership

**Questions.**
1. At the station-hour level (34 St–Penn Station, the two MSG stations), does an MSG home game, or a Knicks or Rangers **win**, move subway entries around the game?
2. Does rain cut ridership differently depending on whether it falls in the morning or the evening, and does the daily KXRAIN flag capture the effect?

**Data.** All public.
- MTA Subway Hourly Ridership 2020–2024 (data.ny.gov `wujg-7c2s`), pulled with SoQL `$group` aggregates only: one query per month, 2022-01 to 2024-12. I took hourly entries for complexes 164 (34 St–Penn A,C,E) and 318 (34 St–Penn 1,2,3), summed as "Penn", plus system-wide hourly entries. The dataset counts **entries only**, so fans arriving at MSG are not counted (they exit at Penn). Fans leaving after the game are counted.
- Games: cached ESPN scoreboards with venue = Madison Square Garden, completed games, regular season and playoffs. These give the local start time, the result and OT. There are 235 evening games (start 18:00–20:36; 108 Knicks, 127 Rangers) and 37 matinees, which get a control dummy. On the 7 doubleheaders I keep the evening game.
- Weather: NOAA GHCN-D USW00094728 daily PRCP ≥ 0.01 in is the KXRAIN settlement flag. NOAA LCD Central Park (72505394728, the same station) gives hourly precipitation from the FM-15 reports, converted from LST to the local clock. Any-hour LCD rain agrees with the GHCN flag on 99.3% of days (phi 0.984), and every rain bucket implies KXRAIN = 1.
- Train is 2022-01-01 to 2023-12-31; holdout is 2024-01-01 to 2024-12-31, refit independently. 2020–21 are excluded.

**Method.** For Q1 the outcome is log(Penn entries) in pre-registered clock windows: pre 17–19h (a placebo), post 21–24h and late 00–02h the next day, plus late share = (23h + 00h) / (21h–00h). Controls are log(system entries in the same window), DOW, year-month FE, holiday, NOAA rain and a matinee dummy, with HAC(7) errors. The win fits use evening game nights only, with DOW, month and year FE, rain, log system entries, OT, playoff, start hour and team, and HC3 errors. For Q2 the outcome is log(system entries) per bucket: AM 06–10, MID 10–16, PM 16–20, EVE 20–24. I fit the rain flags for all four buckets jointly, and separately the daily KXRAIN flag. I also fit daily totals on morning-only vs afternoon-only rain days. **30 tests**; BH at 10% is applied to each period. FOUND uses the shared criteria.

Run `fetch.py` then `mtahourly.py` from backend/. The full table is in `results.csv`, the log in `output.txt`, the hedge in `hedge.csv`.

## Q1: MSG games at 34 St–Penn

| event | window | train effect [90% CI] | n_ev | q | holdout effect [90% CI] | n_ev | q | verdict |
|---|---|---|---|---|---|---|---|---|
| MSG game | post 21–24h | **+28.8%** [+25.6, +32.2] | 152 | <.001 | **+31.9%** [+27.3, +36.6] | 83 | <.001 | **FOUND** (not hedgeable) |
| Knicks game | post | **+35.6%** [+31.2, +40.2] | 65 | <.001 | **+36.8%** [+32.3, +41.4] | 43 | <.001 | **FOUND** (not hedgeable) |
| Rangers game | post | **+24.3%** [+21.3, +27.4] | 87 | <.001 | **+26.8%** [+22.0, +31.8] | 40 | <.001 | **FOUND** (not hedgeable) |
| MSG / Knicks / Rangers game | pre 17–19h (placebo) | +0.1 / +0.7 / −0.3% | | ≥ .81 | +0.6 / +0.3 / +0.8% | | ≥ .52 | NOT FOUND (as expected) |
| MSG / Knicks / Rangers game | late 00–02h | −2.8 / −0.5 / −4.3% | | ≥ .23 | −4.0 / −5.5 / −2.4% | | ≥ .30 | NOT FOUND |
| **MSG win** | post | +0.9% [−1.6, +3.3] | 95 | .81 | +1.0% [−2.1, +4.3] | 52 | .68 | NOT FOUND |
| Knicks win | post | +1.3% [−3.2, +6.0] | 39 | .88 | −3.7% [−10.6, +3.6] | 29 | .57 | NOT FOUND |
| Rangers win | post | +2.9% [−0.3, +6.2] | 56 | .31 | +3.5% [−2.6, +10.0] | 23 | .57 | NOT FOUND |
| MSG / Knicks / Rangers win | late 00–02h | +0.8 / +2.2 / +1.1% | | ≥ .88 | +4.2 / +4.3 / +8.2% | | ≥ .21 | NOT FOUND |
| MSG / Knicks / Rangers win | late share | −0.003 / −0.001 / −0.009 | | ≥ .79 | +0.002 / +0.027 / +0.014 | | ≥ .57 | NOT FOUND |

- **The game effect is large and very stable.** It adds about 1,100–1,900 entries to the 21:00–24:00 window, roughly +30% at Penn, a level daily system totals could never resolve (r2-mta). The placebo window shows nothing, which supports the reading. **No contract hedges it**, though. A game is on the schedule weeks ahead, so there is no uncertainty to hedge, only to plan around. A postponement is the one risk, and it is too rare to estimate.
- **The win effect is null at station level, too.** The pooled win estimate is +0.9% (train) and +1.0% (holdout) on the post window, with CIs of about ±2.5–3%. The minimum detectable effect is roughly ±4% of post-game Penn entries, or about 300 riders. There is no lingering signature either: the late window and the late share don't move with wins in train, and the holdout late-window points (+4–8%) have q ≥ 0.21. A win changes **who is happy, not how many people leave or when they leave**.
- **Kalshi game-winner hedge (KXNBAGAME / KXNHLGAME): not useful.** Both series exist on Kalshi, but the outcome they settle on has no measurable effect on station ridership, so the optimal hedge ratio is about 0. A Penn-area business should treat game nights as a known, scheduled +30% evening, not as a bet on the score.

## Q2: morning vs evening rain (system-wide, by hour bucket)

| event | outcome | train [90% CI] | n_ev | q | holdout [90% CI] | n_ev | q | verdict |
|---|---|---|---|---|---|---|---|---|
| rain in AM bucket | AM entries | −3.2% [−5.5, −0.9] | 98 | .08 | −4.7% [−9.3, +0.2] | 48 | .28 | NOT FOUND |
| rain in MID bucket | MID entries | −4.7% [−6.0, −3.3] | 116 | <.001 | −3.6% [−5.8, −1.4] | 55 | .04 | FOUND (not settleable) |
| rain in PM bucket | PM entries | −1.4% [−3.3, +0.6] | 104 | .43 | −2.8% [−5.3, −0.3] | 49 | .21 | NOT FOUND |
| rain in EVE bucket | EVE entries | −1.0% [−2.8, +0.9] | 97 | .63 | +1.9% [−0.5, +4.5] | 49 | .43 | NOT FOUND |
| AM rain carry-over | PM / EVE entries | −2.3 / −1.4% | 98 | .08 / .30 | −3.0 / −1.5% | 48 | .15 / .46 | NOT FOUND |
| **KXRAIN daily flag** | AM entries | −1.9% [−4.0, +0.3] | 245 | .32 | −1.1% [−4.0, +1.8] | 124 | .66 | NOT FOUND |
| **KXRAIN daily flag** | MID entries | −3.0% [−4.0, −2.0] | 245 | <.001 | −1.9% [−3.6, −0.2] | 124 | .21 | NOT FOUND (holdout q) |
| **KXRAIN daily flag** | PM entries | **−4.0%** [−5.2, −2.7] | 245 | <.001 | **−3.1%** [−4.9, −1.2] | 124 | .04 | **FOUND** |
| **KXRAIN daily flag** | EVE entries | **−5.3%** [−6.4, −4.2] | 245 | <.001 | **−3.5%** [−5.2, −1.7] | 124 | .009 | **FOUND** |
| rain 00–12h only | day total | −1.6% | 80 | .23 | −1.6% | 46 | .57 | NOT FOUND |
| rain 13–24h only | day total | −1.7% | 76 | .02 | −0.3% | 41 | .86 | NOT FOUND |

- **Rain hits the evening hardest, and the daily KXRAIN flag captures it.** On a KXRAIN day, the evening (20–24h) loses 3.5–5.3% of riders and the PM peak 3–4%, while the AM commute barely moves (−1 to −2%, n.s.). Discretionary trips get cut and commutes don't.
- **The timing pattern (exploratory, not in the 30 tests):** in the joint model, each bucket responds to rain in the *preceding* bucket more than to rain falling during it. Rain at 16–20h cuts 20–24h ridership by −6.0% (train) and −7.3% (holdout), while rain during 20–24h itself has no effect. Rain at 10–16h cuts PM by about −5.9%. People decide whether to go out before they leave. For an evening business, the risk is **afternoon rain**, and that risk sits inside the daily KXRAIN flag.
- AM-only vs PM-only rain days have similar small daily-total effects (about −1.6%) and are not significant on holdout. The timing doesn't change the daily total much; it mostly shifts which hours lose riders.
- **Basis.** The bucket flags can't settle a contract (no hourly Kalshi market). The daily KXRAIN flag *is* the settlement flag (GHCN USW00094728), and phi between it and each bucket flag is only 0.55–0.60. So hedge with the daily flag, which is also the strongest predictor for PM and EVE.

## Hedge backtest (holdout 2024, sized from train; income = $2.90 × entries in the window)

| event | income window | β ($/day) | YES price | SD unhedged → hedged | 5th-pct day unhedged → hedged |
|---|---|---|---|---|---|
| KXRAIN | system PM 16–20h | −$104k | 0.356 | $209.2k → $208.8k (−0.2%) | −$301k → −$287k (better) |
| KXRAIN | system EVE 20–24h | −$49k | 0.356 | $78.0k → $76.8k (−1.5%) | −$148k → −$136k (better) |

The hedge cuts SD and improves the 5th-percentile day on both rows, which is the same small-but-real picture as r2-mta. The evening window gets about 7× more SD reduction than the PM window, because rain is a larger share of evening noise.

## Verdict
- **MSG game → Penn post-game entries: FOUND** (+29% train, +32% holdout; Knicks +36%, Rangers +25%). **Not hedgeable**: the game is on the schedule, and no Kalshi contract settles on "a game happens".
- **Knicks / Rangers / MSG win → Penn entries (volume or timing): NOT FOUND**, 0 of 9 tests, even at station-hour resolution, the least diluted series tried so far. A KXNBAGAME or KXNHLGAME hedge would have a hedge ratio of about 0. This closes the "win" thread: wins showed no effect anywhere in the NYC data, now including the station next to the arena.
- **KXRAIN → evening and PM-peak ridership: FOUND** (−3.5% to −5.3% evening, −3% to −4% PM), with a hedge that lowers SD and improves the 5th-percentile day. **The AM commute is not rain-sensitive** (NOT FOUND).
- **Midday-bucket rain → midday ridership: FOUND but not settleable** (no hourly contract; phi with KXRAIN is 0.60).
- Tally: 30 tests; 6 pass FOUND (3 game-schedule, 2 KXRAIN, 1 hourly bucket), and only the 2 KXRAIN rows are hedgeable.

**Demo.** "An evening business near a subway station: rain costs your 8 pm to midnight crowd about 4%, mostly from afternoon rain that keeps people home. KXRAIN pays on the same day." And: "Game nights are +30% at Penn, but whether the Knicks win makes no difference, so don't buy the game-winner contract."

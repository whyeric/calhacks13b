# Arena and team split: does a win show up in foot traffic at all?

**Question.** If MSG's own daily visits don't respond to a Knicks/Rangers *win* (beyond the game happening), no nearby bar will. Does pooling the two teams hide a win effect at the bar?

**Method.** OLS with HC3 errors and 90% CI (z=1.645), on the window 2024-10-01 to 2026-08-31 (n=700 days; train = first 365). Controls: DOW dummies, season (Fourier k=1,2, with year-month fixed effects as a robustness check), holiday, and `other_event` (an MSG visit spike on a non-game day, such as a concert). Terms per team: `{team}_home_game` and `{team}_home_win`, where the win term is win minus loss among home games. Outcomes: MSG arena POI visits (`fixtures/msg_visits_daily.parquet`) and bar revenue (`features.build("restaurant")`, which is visits x $35, so it is estimated). Script: `arena_split.py`, which prints summaries only.

## Arena visits (full window, Fourier season; plain-day mean 32,142 visits)

| term | effect (visits) | 90% CI | n days | sig |
|---|---|---|---|---|
| knicks_home_game | +2,373 | [576, 4,171] | 99 | yes |
| knicks_home_win | +1,006 | [-1,044, 3,056] | 68 | no |
| rangers_home_game | +5,547 | [3,952, 7,142] | 82 | yes |
| rangers_home_win | -932 | [-3,504, 1,641] | 33 | no |
| other_event (non-game spike) | +9,605 | [8,517, 10,692] | 73 | yes (spike-defined, so circular) |
| pooled home_game | +4,074 | [2,796, 5,352] | 178 | yes |
| pooled home_win | -334 | [-1,894, 1,226] | 100 | no |

Robustness: the home_win terms are not significant in any of the 4 specs (Fourier or month FE, all or train). Knicks win ranges from -184 to +2,522; Rangers win ranges from -3,219 to -785.

## Bar revenue (p_afa556030e60, $/day, full window, Fourier)

| term | effect ($) | 90% CI | n days | sig |
|---|---|---|---|---|
| knicks_home_game | -405 | [-1,657, 848] | 99 | no |
| knicks_home_win | +450 | [-1,057, 1,957] | 68 | no |
| rangers_home_game | +793 | [-1,341, 2,927] | 82 | no |
| rangers_home_win | -1,837 | [-4,151, 477] | 33 | no |
| other_event | +1,497 | [202, 2,793] | 73 | yes (full window); no in train (p=0.15) |
| pooled home_win | -720 | [-2,225, 785] | 100 | no |

Train only (the sample the app fits on): knicks_home_win -$1,366 [-3,182, 450], n=31; rangers_home_win -$2,386 [-6,792, 2,021], n=19. Neither is significant. The team split does not uncover anything that pooling had cancelled out: both teams' terms are noisy, and the Rangers term is the more negative one.

## Penn Station dilution
- The commuter pattern is weak, not dominant. On plain days the weekday/weekend ratio is 1.085 (Wed 34.8k, Sun 28.9k). Holidays without a game average 27.7k against a 33.0k weekday mean.
- DOW, season and holiday alone give R2 0.40. Adding games and other_event raises it to 0.56, so events are clearly visible in the POI.
- The real constraint is noise. Plain-day SD is 6,643 (CV 0.21), so a home game is only +7% (Knicks) to +17% (Rangers) of the base. The win-term CI is about ±2,000–2,500 visits. A win effect would have to be roughly as large as the whole game-day bump to be detected.

## Extra (away games, exploratory)
Arena knicks_away_win +2,096 [286, 3,906], p=0.057. Bar knicks_away_game -$1,691 [-2,738, -644], p=0.008. There is no mechanism for either (an away win can't move arena visits), and both are what chance alone produces, see below.

## Multiple comparisons
I ran 26 win-related tests (13 arena, 13 bar). One came out p<0.10 (the arena away-win term above), against about 2.6 expected by chance. There is no win signal.

## Verdict
The arena POI clearly registers games (+2.4k Knicks, +5.5k Rangers, +9.6k concerts and other spikes, all highly significant). So the data can see MSG crowds. It does **not** register *winning*: win minus loss is null for both teams, in every specification, with CIs about 2x the size of a Knicks game bump. Part of the reason is mechanical: arena attendance is ticketed before the result is known. So a win can only show up as post-game lingering or bar spillover, and the arena's daily count is a weak test for that. The bar test is the direct one, and it is also null for both teams (it is only 0.08 correlated with arena visits on plain days). Splitting by team does not rescue home_win. The pooled -$2,026 is noise, and no team-level version meets significance at 90%, |effect| >= $150 and >= 10 train events together. The only bar term near hedgeable is `other_event` (non-game MSG spikes, +$1.5k), but it fails in train.

**Demo-worthy?** Not as a hedge. As a story it is: "games show up in MSG foot traffic, wins don't, so the desk correctly declines to sell a win hedge." That is an honest negative result.

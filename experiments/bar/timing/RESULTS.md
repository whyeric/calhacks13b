# Bar exposure: next-day spillover timing

**Question.** Is the bar's (p_afa556030e60) win effect landing on the wrong date? Games tip around 7:30 PM and end around 10 PM, so celebration visits after midnight could fall on the next local date.

**Method.** I took `features.build("restaurant")` and the `fit_exposures` design (DOW, season k=1,2, holiday, msg_event, home_game, home_win, rain, hot>85), then added calendar-date lag/lead flags: `win_day_after` (yesterday was a home win), `win_day_before` (lead placebo: a home win tomorrow), `game_day_after` and `game_day_before`. I also split games by ESPN tip-off time: 32 early (before 7 PM, NY time) and 146 late. As a check on the dates, I ran the same design on the MSG arena's daily Dewey visits. OLS with HC3 errors and 90% normal CI. Script: `timing.py`.

## Bar revenue ($/day), train = first 365 days (the window `fit_exposures` uses)

| spec | flag | effect | 90% CI | n | sig |
|---|---|---|---|---|---|
| baseline | home_win | -2,026 | [-4,351, 299] | 49 | no |
| + lags/leads | home_win | -2,153 | [-4,497, 191] | 49 | no |
| | win_day_after | **-1,472** | [-2,569, -375] | 49 | yes |
| | win_day_before (placebo) | **-1,111** | [-2,213, -8] | 49 | yes |
| | game_day_after | +835 | [-292, 1,962] | 90 | no |
| | game_day_before | -122 | [-1,205, 961] | 90 | no |
| early/late split | win_early | -2,481 | [-5,435, 474] | 10 | no |
| | win_late | -1,991 | [-4,272, 290] | 39 | no |
| | win_after_early | -791 | [-2,350, 769] | 10 | no |
| | win_after_late | -1,641 | [-2,783, -498] | 39 | yes |

Adding the flags moves R² on train from 0.158 to 0.172.

## Bar revenue, full 700-day window (robustness check)

| flag | effect | 90% CI | n | sig |
|---|---|---|---|---|
| home_win | -753 | [-2,285, 780] | 100 | no |
| win_day_after | -658 | [-1,732, 416] | 100 | no |
| win_day_before (placebo) | +341 | [-770, 1,452] | 100 | no |
| game_day_after | +316 | [-638, 1,270] | 178 | no |
| win_after_late | -873 | [-1,996, 249] | 78 | no |

## MSG arena visits/day (mean 33,674): checking the date alignment, full window

| flag | effect (visits) | 90% CI | n | sig |
|---|---|---|---|---|
| game_day | **+3,020** | [2,049, 3,991] | 178 | yes |
| game_day_after | -1,234 | [-2,199, -270] | 178 | yes |
| game_day_before | +38 | [-947, 1,023] | 178 | no |
| early tip, same day | +7,422 | [5,028, 9,815] | 32 | yes |
| early tip, day after | +977 | [-809, 2,763] | 32 | no |
| late tip, same day | +1,364 | [380, 2,347] | 146 | yes |
| late tip, day after | -1,654 | [-2,654, -653] | 146 | yes |

## Verdict

There's no sign of a celebration spillover onto the next day. Every next-day coefficient for the bar is negative, never positive. On train, `win_day_after` reaches significance (-$1,472), but so does the placebo lead `win_day_before` (-$1,111). A home win tomorrow can't cause anything today, so both coefficients are most likely picking up the same confounder, probably which weeks games cluster in during the 2024-25 season, not a timing effect. Both lose significance on the full 700-day window. I tested about 45 coefficients across 11 fits (6 on the bar, 5 on the arena), so at 90% roughly four or five "significant" results are expected by chance.

The MSG arena check shows Dewey dates are aligned correctly. The game bump sits on the game date (+3,020 visits/day), there's nothing on the day before, and the day after is lower, not higher. A lower day after is what you'd expect when consecutive event nights are rare: the baseline includes concert days, and the day after a game usually has no event. Late tip-offs still show their bump on the same date (+1,364). Early tip-offs show a much larger bump (+7,422), probably because weekend matinees draw longer visits during the day; this is a guess I haven't checked. In short, date attribution isn't hiding the effect. The bar simply doesn't show a positive win effect on any day.

**Demo-worthy?** Not as an exposure. Nothing here is hedgeable: no positive effect, the one significant lag fails its placebo, and it doesn't replicate on the full window. The arena result could be a one-line "we checked the date alignment" footnote.

# Stakes experiment: is the bar's win effect limited to high-stakes games?

Business: bar across from MSG (`p_afa556030e60`), revenue = Dewey daily visits x $35 (`estimated=True`).
Script: `stakes.py` (run from backend/). ESPN scoreboards were fetched for all 366 final Knicks/Rangers
games in the window (cached in the session scratchpad, not the repo). 0 games were missing details.

## Method
- Each game is classified as playoff (ESPN season type 3) or regular season, weekend (Fri-Sun) or
  weekday, close (NBA margin <= 5, NHL <= 1) or blowout, and home or away.
- On `features.build("restaurant")` train rows, the `fit_exposures` design is refit (DOW, season
  k=1,2, holiday, msg_event, home_game controls, plus rain and hot>85, OLS HC3, 90% z CI). `home_win`
  is replaced by class-split win flags. Away flags are a separate spec.
- Train playoff games are all Knicks games from the 2025 run (9 home, 9 away). The Rangers did not
  make the playoffs that year.

## Results (train, 2024-10-01..2025-09-30)
| spec | term | effect $/day | 90% CI | n | significant |
|---|---|---:|---|---:|---|
| baseline | home_win | -2,026 | [-4,351, 299] | 49 | no |
| playoff | home_win_playoff | -3,346 | [-7,471, 779] | 4 | no (anecdotal) |
| playoff | home_win_regular | -1,898 | [-4,223, 426] | 45 | no |
| weekend | home_win_weekend | -2,157 | [-5,155, 840] | 20 | no |
| weekend | home_win_weekday | -1,931 | [-4,040, 178] | 29 | no |
| margin | home_win_close | -2,503 | [-5,283, 277] | 14 | no |
| margin | home_win_blowout | -1,841 | [-4,153, 471] | 35 | no |
| away | away_game | +156 | [-1,653, 1,965] | 78 | no |
| away | away_win | -672 | [-2,608, 1,265] | 50 | no |
| any game | any_win_playoff | -2,234 | [-4,545, 77] | 10 | no |
| any game | any_win_regular | -1,586 | [-3,400, 227] | 85 | no |
| playoff game | playoff_game (home or away, won or lost) | -2,202 | [-3,612, -792] | 18 | yes |
| playoff game | regular_game_nonhome | +56 | [-1,012, 1,124] | 69 | no |

Out-of-sample check of the one significant term, refit on holdout rows (2025-10..2026-08, the 2026
Knicks playoff run, n=19): playoff_game is **-36, CI [-1,916, 1,843], not significant**. It does not replicate.

## Verdict
No game class carries a positive, hedgeable win effect. Every win term, split by playoff, weekend,
margin or home/away, has a negative point estimate with a CI that crosses zero. That is the same
picture as the pooled -$2,026, so the null is not caused by low-stakes games diluting the pool. Away
games add nothing (+$156 for a game, -$672 for a win). The one significant term, playoff_game at
-$2,202 (n=18), is 1 of 15 terms tested, and about 1.5 of those would come up at p<0.10 by chance.
The playoff days also fall in one block (Apr-May 2025), which the season terms can confound. The term
collapsed to -$36 on the holdout playoff run. Treat it as noise. Playoff home wins (n=4) are anecdotal.

**Demo-worthy?** No as an exposure. The honest line works as a talking point: "We split by playoff,
weekend, margin and away games. The bar still shows no win effect, so the desk declines to hedge it."

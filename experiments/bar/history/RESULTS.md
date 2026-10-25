# Bar: longer history (2024-01-01 onward)

**Question.** Does using the full Dewey history make the bar's Knicks/Rangers home-win (or rain) effect measurable? The shared window starts on 2024-10-01 and leaves out about 9 months, including the Apr–May 2024 playoffs.

**Method.** Bar `p_afa556030e60` daily revenue (Dewey visits x $35, `estimated`) for 2024-01-01..2026-09-27 (1001 days, none missing). MSG weather comes from Open-Meteo for the same span. Knicks/Rangers home games come from ESPN, with ESPN season type 3/5 counted as playoff. The columns and the `fit_exposures` design (DOW, season k=1,2, holiday, msg_event, home_game controls, HC3, z=1.645) are unchanged, with hot strike 85F. Script: `run.py` (caches go to the scratchpad, and it prints summary numbers only).

Coverage: 69 MSG home games before 2024-10-01 (47 wins, 15 playoff). Over the full span there are 250 home games: Knicks 25 playoff / 110 regular, Rangers 8 playoff / 107 regular.

## Results

| fit | event | effect $ | 90% CI | n event days (train) | significant |
|---|---|---|---|---|---|
| baseline (2024-10-01.., train 365d) | home_win | -2025.97 | [-4350.74, 298.80] | 49 | no |
| | rain | -345.21 | [-991.71, 301.29] | 148 | no |
| | hot | -118.11 | [-1205.40, 969.17] | 55 | no |
| (a) 2024-01-01.., train first 365d | home_win | -2027.96 | [-4583.14, 527.23] | 63 | no |
| | rain | +158.36 | [-521.37, 838.09] | 147 | no |
| | hot | -50.57 | [-1356.07, 1254.92] | 53 | no |
| (b) all 1001 days as train | home_win | -752.46 | [-1935.87, 430.96] | 146 | no |
| | rain | -225.60 | [-659.81, 208.62] | 441 | no |
| | hot | -343.59 | [-1010.05, 322.87] | 156 | no |
| (c) split, train first 365d | home_win regular | -1883.51 | [-4454.06, 687.04] | 53 | no |
| | home_win playoff | -2824.74 | [-5532.45, -117.02] | 10 | yes (see below) |
| (c) split, all data | home_win regular | -696.45 | [-1898.82, 505.91] | 125 | no |
| | home_win playoff | -1090.09 | [-3027.25, 847.07] | 21 | no |

| fit | R2 train | R2 holdout |
|---|---|---|
| baseline | 0.158 | 0.046 |
| (a) | 0.137 | 0.091 |
| (b) | 0.138 | n/a |

The baseline row is the same as the brief's numbers, so the pipeline matches `features.build`.

## Verdict

More history does not make the bar's exposures measurable. In (a), home_win keeps the same point estimate (about -$2,028) and its CI still crosses zero. Rain changes sign, and hot stays well below the $150 size gate. In (b), with 2.7x the data, the CIs narrow by about half. The home_win point estimate also shrinks to -$752, and nothing is significant. That pattern looks like a noisy series with no real effect, not a real effect that lacks power. The one "significant" cell is (c) playoff wins in the 2024 train year: -$2,825, CI just excludes zero, with n=10, which is exactly the support floor. It is one of 14 new event coefficients fitted in (a)–(c) (at 90%, about 1.4 false positives are expected by chance). It has the counterintuitive sign (fewer visits on win nights, net of the home_game control), and it disappears on all data (-$1,090, CI [-3,027, 847], n=21). I'd treat it as noise. R2 stays at 0.14 in-sample, and holdout improves only from 0.05 to 0.09.

**Demo-worthy?** No, not as a hedgeable exposure. It does work as an honest "declined: not measurable" example: with almost 3 years of data the bar still shows no reliable win or weather effect.

# R6 broadway: do snow, heat and Knicks/Rangers playoff runs move Broadway and Times Square?

## Pre-registration (written before any fit)

### Mechanisms
- **(a) Weather -> theatergoers -> grosses.** A snowstorm (or a heat wave) in NYC makes tourists
  and suburban/bridge-and-tunnel ticket buyers cancel or not buy walk-up tickets, and some
  performances are cancelled outright, so the Broadway week's gross and attendance fall. The same
  people eat before the show, so Times Square restaurant visits fall too. Predicted sign: negative.
- **(b) Playoff runs -> competing evening -> Broadway.** A Knicks/Rangers playoff home night at MSG
  pulls the Midtown evening-entertainment crowd and dollar to the game, bars and TV, so Broadway
  and Times Square restaurants lose that night/week. Predicted sign: negative. If real, a theater
  district business is long "Knicks eliminated" risk the wrong way round: it would buy the
  *advance* side (equivalently "eliminated: NO") so it is paid when the run continues.

### Data
- Broadway League weekly grosses per show, 1985-06-09..2020-03-01 (TidyTuesday 2020-04-28
  redistribution of the Playbill tables). Summed to the week: total gross, total seats sold,
  aggregate capacity (seats sold / (seats x performances)), number of shows.
- Dewey (Advan) weekly patterns -> daily visits, balanced panel (stores present every week, <5%
  flat weeks), summed over restaurants/bars in ZIPs 10036 + 10019 (Times Square / theater district),
  2024-01-01..2026-09-27. Placebo series: ZIP 10028 (Upper East Side, no theaters, far from MSG).
- Weather: NOAA GHCN Central Park USW00094728 (the KXHIGHNY / KXNYCSNOWM settlement station).
- Games: ESPN Knicks/Rangers schedules; playoff home games = postseason games with homeAway=home,
  not neutral site, deduped by local date. ESPN has no Rangers postseason before 1994, so the
  Broadway playoff test uses weeks from 1993-07 onward.

### Tests (the BH family, 18 tests, q = 10%)
Broadway weekly (y in {log gross, log seats sold, capacity in pct pts}) x events:
1. `snow_days`: number of days in the Mon-Sun week with CP snowfall >= 1.0 in
2. `big_snow`: the week has a day with snowfall >= 6 in
3. `heat_days`: number of days with CP tmax >= 90 F
4. `heatwave`: the week has >= 3 days with tmax >= 90 F
5. `playoff_home`: number of Knicks + Rangers playoff home games in the week

Controls: year-month FE, holiday-week dummies (MLK, Presidents, Easter, Memorial, July 4, Labor,
Thanksgiving, Christmas, New Year), log(number of shows), and for (5) the count of MSG
regular-season home games. HAC(4) errors. Train 1985-06..2002-12 / holdout 2003-01..2020-03
(weather); train 1993-07..2006-12 / holdout 2007-01..2020-03 (playoffs).

Dewey daily, Times Square series (log visits) x {`snow_day` (>= 1.0 in), `heat_day` (tmax >= 90 F),
`playoff_home`}. Controls: DOW, year-month FE, holiday, MSG regular-season home game. HAC(7).
Train 2024-01-01..2025-03-31 / holdout 2025-04-01..2026-09-27.

### Placebos (reported, not in the BH family; should be null)
- Broadway: each event shifted to the *following* week (lead), same model.
- Dewey: each event on the *day before*; and the same three events on the ZIP 10028 series.

## Data access note
- **Broadway grosses after 2020-03 were NOT fetched.** Playbill's robots.txt disallows `ClaudeBot`,
  `anthropic-ai` and `Claude-Web` outright (and sets `ai-input` unsigned, `ai-train=no`), so we
  stopped there. BroadwayWorld's robots.txt disallows the grosses export (`/grossesshowexcel.*`)
  and its terms page returned 403, so we didn't scrape its weekly pages either. We used the public
  TidyTuesday redistribution (1985-06-09..2020-03-01, 1,812 weeks), which is the same Broadway
  League data the Kaggle "Broadway grosses" dataset comes from. As a result, Broadway (to 2020)
  and Dewey (2024+) don't overlap in time.
- Dewey balanced panel: 1,034 restaurants/bars in 10036+10019 and 315 in placebo ZIP 10028.

## Results (run.py; 18 pre-registered tests, BH q = 10%)
Effects are log points (x100 = %) per event unit, or pct points of capacity; 90% CIs.

| series | event | train beta [90% CI] (n_ev) | holdout beta [90% CI] (n_ev) | BH q | verdict |
|---|---|---|---|---|---|
| Broadway log gross | snow_days (per >=1in day) | **-2.2% [-3.6, -0.7]** (72 wk) | **-2.5% [-4.4, -0.6]** (92 wk) | 0.076 | **FOUND** |
| Broadway log seats | snow_days | **-2.2% [-3.5, -0.9]** | **-2.2% [-3.6, -0.8]** | 0.056 | **FOUND** |
| Broadway capacity | snow_days | **-1.29 pp [-2.22, -0.36]** | **-1.11 pp [-1.82, -0.40]** | 0.080 | **FOUND** |
| Broadway log gross | big_snow (>=6in day) | -0.1% [-5.5, 5.3] (11) | -5.6% [-9.6, -1.6] (23) | 0.98 | not found |
| Broadway log seats | big_snow | -2.1% [-7.0, 2.8] | -4.4% [-7.4, -1.4] | 0.54 | not found |
| Broadway capacity | big_snow | -1.6 pp [-4.9, 1.6] | -2.7 pp [-4.0, -1.3] | 0.54 | not found |
| Broadway log gross | heat_days (per >=90F day) | -0.38% [-0.67, -0.09] (121) | **+1.09% [+0.60, +1.58]** (97) | 0.082 | not found (sign flips) |
| Broadway log seats | heat_days | -0.50% [-0.78, -0.22] | +0.64% [+0.29, +0.99] | 0.056 | not found (sign flips) |
| Broadway capacity | heat_days | -0.30 pp [-0.52, -0.07] | +0.16 pp [-0.06, 0.39] | 0.082 | not found |
| Broadway log gross | heatwave (>=3 days >=90F) | -1.3% [-2.7, 0.1] (38) | +3.6% [+1.6, +5.6] (25) | 0.24 | not found (sign flips) |
| Broadway log seats | heatwave | -1.9% [-3.2, -0.6] | +2.2% [+0.8, +3.6] | 0.080 | not found (sign flips) |
| Broadway capacity | heatwave | -1.1 pp [-2.1, -0.2] | +0.5 pp [-0.6, 1.6] | 0.11 | not found |
| Broadway log gross | playoff_home (per game) | -0.47% [-1.5, 0.6] (42 wk) | -0.39% [-1.7, 0.9] (41 wk) | 0.54 | not found |
| Broadway log seats | playoff_home | -0.43% [-1.4, 0.5] | -0.17% [-1.2, 0.9] | 0.54 | not found |
| Broadway capacity | playoff_home | -0.44 pp [-1.12, 0.24] | -0.77 pp [-1.41, -0.14] | 0.43 | not found |
| Times Sq Dewey (daily) | snow_day (>=1in) | -3.2% [-7.2, 0.8] (7) | -10.8% [-16.0, -5.7] (7) | 0.35 | not found (n < 10) |
| Times Sq Dewey | heat_day (>=90F) | -1.8% [-4.5, 0.9] (15) | -2.2% [-4.5, 0.1] (19) | 0.43 | not found |
| Times Sq Dewey | playoff_home night | +0.02% [-1.7, 1.8] (15) | -0.04% [-2.0, 1.9] (18) | 0.98 | not found |

Splits: Broadway weather train 1985-06..2002-12 / holdout 2003..2020-03; Broadway playoffs
1993-07..2006 / 2007..2020-03; Dewey 2024-01..2025-03 / 2025-04..2026-09.

### Placebos (should be null)
- **Broadway, next week's event (lead):** snow_days lead is null on all three outcomes in both
  splits (gross -0.8% [-2.1, 0.5] train, -0.8% [-2.6, 0.9] holdout). So the snow effect sits in
  the week it snows, not the week after. (big_snow lead is negative in train only, n=11, and
  holdout null; heat leads are noisy, consistent with heat not being a stable effect anyway.)
- **Broadway, permutation (hedge.py, 500 draws, snow_days shuffled across years within calendar
  month):** the mean permuted beta is +0.07% / +0.14%, the true beta lies outside the 90% band, and
  perm p = 0.020 (train), 0.016 (holdout).
- **Dewey, placebo ZIP 10028:** snow days cut visits there too (-4.9% train, -8.3% holdout), as
  much as in Times Square. The Dewey snow drop is citywide, not theater-specific. The day-before
  placebo is null for all three Dewey events.

### Robustness of the FOUND result (exploratory; not in the BH family; robustness.csv)
| check | train | holdout |
|---|---|---|
| baseline log gross | -2.2% [-3.6, -0.7] | -2.5% [-4.4, -0.6] |
| + log(performances) control | -2.3% [-3.7, -0.9] | -1.7% [-3.3, -0.1] |
| y = log(performances) | +0.3% [-0.4, 1.1] | -1.0% [-2.1, 0.1] |
| drop the 3 snowiest weeks | -2.3% [-3.8, -0.7] | -3.2% [-5.1, -1.3] |

Most of the effect is lost demand (fewer seats sold at performances that still happen), not
cancellations. In the 2003-2020 holdout about a third of it is cancelled performances (the
blizzards of the 2010s). It isn't driven by a few extreme storms.

## Basis and hedge backtest (hedge.py)
- **Contract:** KXNYCSNOWM ("Snow in New York City in <month>?", YES if Central Park monthly
  snowfall is *strictly greater* than K in, K in 2/4/6/8/10/12). It settles on the same station
  as our event flag. A monthly contract can be bought weeks ahead, so there's no forecast caveat.
- **Basis:** in Dec-Mar months, the correlation of the monthly count of >=1in snow days with the
  YES flag is 0.65-0.71 on train and 0.57-0.65 on holdout. K = 8 in was picked on train (corr 0.71;
  YES months average 2.1 more snow days).
- **Size of the exposure (2018-19 scale, ~$33M/week industry gross):** -2.2% x $33M = about
  **-$0.7M per >=1in snow day, industry-wide**, or about -$20k per show per snow day (~33 shows).
- **Backtest** (holdout Dec-Mar months 2003-2020, n = 71, 27 YES months; buy YES at the train
  frequency 0.30 + 0.02 = $0.324 plus a $0.015 fee; 1.5M contracts per month, i.e. 2.1 days x
  $0.7M): SD of the monthly gross residual is **$6.56M unhedged vs $6.58M hedged**; the 5th
  percentile is **-$10.3M vs -$10.6M**; mean cost is $61k per month. **The hedge doesn't help.**
  The monthly gross residual is almost uncorrelated with the payout (-0.03). A 2-3 snow-day month
  costs about $1.5M against $6.6M of other monthly noise (show openings and closings, tourism,
  the economy), and the monthly contract also misses which week the snow falls in.

## Verdicts
- **(a) Snow -> Broadway grosses/attendance: FOUND** (3/3 outcomes: train, holdout, BH, lead
  and permutation placebos). About -2.2% of weekly gross and seats per >=1in snow day, stable
  across 1985-2002 and 2003-2020. **Not hedgeable in practice:** the KXNYCSNOWM backtest reduced
  neither the SD nor the 5th percentile, because snow is a small share of monthly variance. It is
  real but small: about 1-2% of a winter month's gross.
- **(a) Heat -> Broadway: NOT FOUND.** It is slightly negative in 1985-2002 and positive in
  2003-2020; the sign flips, so it doesn't replicate. (One explanation: summer tourists in
  air-conditioned theaters. We didn't test that.)
- **(a) Snow/heat -> Times Square restaurants (Dewey): NOT FOUND.** There are only 7 snow days
  per split (< 10), and the placebo ZIP falls just as much, so the drop is a citywide snow effect
  and nothing theater-specific. Heat CIs include 0.
- **(b) Knicks/Rangers playoff home games -> Broadway / Times Square: NOT FOUND, a clean null.**
  Broadway gross per playoff home game is -0.5% [-1.5, 0.6] train and -0.4% [-1.7, 0.9] holdout.
  Times Square restaurant visits on playoff nights are +0.0% +-1.8% in both splits, against the
  +5.7% within 0.5 km of MSG found in r5-nycplayoffs. So the MSG halo stops before 10036/10019,
  and there's no measurable substitution loss either. **The unintuitive "theater district buys
  Knicks-advance" hedge has no support.**

Tests run: 18 in the BH family, plus 30 Broadway lead placebos, 6 Dewey day-before placebos,
6 placebo-ZIP fits, 8 robustness fits and 2 permutation runs (none of which were used to choose
anything). Nothing was tuned on holdout. The strike K was chosen on train.

## Files
- `fetch.py`: grosses (TidyTuesday) and ESPN schedules into the scratchpad cache.
- `run.py`: the 18 pre-registered tests and placebos -> `results.csv`, `verdicts.csv`, `output.txt`.
- `hedge.py`: robustness, basis and KXNYCSNOWM backtest -> `robustness.csv`, `basis.csv`, `hedge.csv`.

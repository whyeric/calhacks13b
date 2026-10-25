# R4 iowa: Iowa liquor orders vs college football and weather

**Question.** Do Iowa liquor-store orders from the state, which are real B2B revenue, move with Kalshi-settleable events? The candidate events are Hawkeyes and Cyclones home games and wins, and Des Moines or Iowa City weather.

**Answer: NOT FOUND (0 of 18).**
- One test survives BH on train: Iowa City orders fall 28% in the week after a Hawkeyes win. It vanishes on holdout (−1.4%, CI spans 0).
- The only holdout-significant results (Ames home-game week +14%, statewide after an ISU win −10%, statewide snow day +5%) were not significant on train.

## Data

- **Liquor orders:**
  - **Source:** the Kaggle mirror of Iowa Liquor Sales (`archive (1).zip` → `Iowa_Liquor_Sales.csv`, 3.47 GB, 12.59M line items, **2012-01-03..2017-10-31**, $1.47B). The data ends in Oct 2017, not 2020, and grep finds no 2018/2019 rows.
  - **Who orders:** Class E licensees, i.e. off-premise stores ordering from the state, not bars.
  - **Aggregation:** duckdb (`iowa.py build`) aggregates to date × area × liquor group, where area is DSM metro, ICY (Iowa City, Coralville, North Liberty), AMES or OTHER. The raw CSV was extracted to the scratchpad and deleted afterwards. Only `r2-cache/r4iowa_daily.parquet` is kept.
  - **The live portal:** data.iowa.gov moved off Socrata in 2026, so `m3tr-qhgy` now returns 404.
- **Football:** ESPN team schedules for Iowa (2294) and Iowa State (66), seasons 2012–2017 regular season. Neutral-site games are not counted as home.
- **Weather:** NOAA GHCN Des Moines USW00014933 and Iowa City USC00134101.
  - rain = PRCP ≥ 0.01 in
  - snow = SNOW ≥ 1 in
  - hot = TMAX ≥ 90 °F

## Method

- **Split:** train 2012–2015, holdout 2016-01..2017-10, refit independently. This differs from the lead's plan (train 2012–16, hold out 2017–19) because the file ends in Oct 2017. I fixed this split before seeing any results.
- **Football (weekly, Mon–Sun):**
  - y = log(area orders) − log(rest of state), which removes statewide shocks. A second unit uses log statewide orders.
  - Controls: year-month FE, a holiday-week dummy, HAC with 4 lags.
  - Events:
    - `home_L0`: orders in the week of a home game (stocking)
    - `home_L1`: the week before a home game
    - `win_post1`: the week after a win, conditional on a game having been played
    - `homewin_post1`: the week after a home win
- **Weather (daily, order days only):** log statewide orders vs DSM flags, and log ICY/rest vs Iowa City flags. Controls: DOW, year-month FE, holiday, HAC with 7 lags.
- **Multiple comparisons:** BH at 10% across all 18 train p-values.

## Results (effects are log points, ≈ %; 90% CIs)

| # | unit | event | train β [90% CI] | n_ev | holdout β [90% CI] | n_ev | BH q | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | ICY/rest | home week | −0.075 [−0.137, −0.014] | 28 | +0.041 [−0.020, +0.102] | 12 | 0.27 | NOT FOUND (flips) |
| 2 | ICY/rest | week before home | −0.039 [−0.121, +0.044] | 28 | −0.003 [−0.079, +0.073] | 12 | 0.61 | NOT FOUND |
| 3 | ICY/rest | week after home win | −0.095 [−0.246, +0.056] | 17 | −0.052 [−0.182, +0.078] | 7 | 0.61 | NOT FOUND |
| 4 | ICY/rest | **week after win** | **−0.277 [−0.410, −0.144]** | 31 | −0.014 [−0.072, +0.044] | 12 | **0.011** | NOT FOUND (holdout null) |
| 5 | state | Iowa home week | +0.035 [−0.090, +0.159] | 28 | −0.020 [−0.095, +0.055] | 12 | 0.78 | NOT FOUND |
| 6 | state | week after Iowa win | +0.110 [−0.016, +0.235] | 31 | +0.003 [−0.077, +0.082] | 12 | 0.46 | NOT FOUND |
| 7 | AMES/rest | home week | +0.086 [−0.013, +0.185] | 26 | +0.143 [+0.002, +0.285] | 12 | 0.46 | NOT FOUND (train CI spans 0) |
| 8 | AMES/rest | week before home | +0.056 [−0.024, +0.136] | 26 | +0.064 [−0.051, +0.180] | 12 | 0.61 | NOT FOUND |
| 9 | AMES/rest | week after home win | +0.097 [−0.105, +0.300] | 8 | +0.120 [−0.112, +0.352] | 4 | 0.61 | NOT FOUND (<10 events) |
| 10 | AMES/rest | week after win | −0.064 [−0.188, +0.060] | 14 | +0.039 [−0.100, +0.178] | 8 | 0.61 | NOT FOUND |
| 11 | state | ISU home week | −0.001 [−0.095, +0.093] | 26 | −0.064 [−0.138, +0.010] | 12 | 0.98 | NOT FOUND |
| 12 | state | week after ISU win | −0.053 [−0.202, +0.096] | 14 | −0.100 [−0.177, −0.024] | 8 | 0.72 | NOT FOUND |
| 13 | state daily | DSM rain | −0.025 [−0.065, +0.016] | 247 | +0.012 [−0.013, +0.037] | 144 | 0.61 | NOT FOUND |
| 14 | state daily | DSM snow ≥ 1 in | +0.008 [−0.051, +0.068] | 25 | +0.054 [+0.011, +0.097] | 10 | 0.87 | NOT FOUND |
| 15 | state daily | DSM hot ≥ 90 °F | +0.020 [−0.018, +0.057] | 69 | +0.031 [−0.010, +0.073] | 36 | 0.61 | NOT FOUND |
| 16 | state daily | day after DSM snow | −0.165 [−0.320, −0.010] | 25 | −0.015 [−0.072, +0.043] | 10 | 0.36 | NOT FOUND |
| 17 | ICY/rest daily | Iowa City rain | −0.342 [−0.593, −0.091] | 268 | +0.270 [−0.188, +0.729] | 133 | 0.23 | NOT FOUND (flips; noisy) |
| 18 | ICY/rest daily | Iowa City snow | +0.232 [−0.865, +1.329] | 18 | +0.409 [−1.027, +1.846] | 3 | 0.82 | NOT FOUND |

The full table is in `results.csv` and the run log in `output.txt`. Since nothing was FOUND, there is no hedge backtest.

## Basis

- **Football:** today Kalshi `KXNCAAFGAME` lists Iowa and Iowa St. game-winner markets (e.g. `KXNCAAFGAME-26OCT30WISIOWA-IOWA`), so a win event settles directly. Those markets did not exist in 2012–2017. Home games are on the published schedule, so they are a forecast input and not a hedgeable risk.
- **Weather:** no Kalshi weather contract settles in Iowa, and the only Des Moines series (`KXEMERGENCYDES`) is a disaster market. Agreement of the DSM daily flags with the stations nearest to a Kalshi contract (phi):

| | rain | snow | hot |
|---|---|---|---|
| Minneapolis USW00014922 | 0.37 | 0.19 | 0.52 |
| Chicago Midway USW00014819 | 0.33 | n/a (no SNOW) | 0.49 |

Even a real Iowa weather effect would hedge poorly. With a rain phi near 0.35, roughly 88% of the variance would remain as basis risk.

## Reading

- **Football:** the order data does not show a football stocking cycle. The order calendar is set by delivery routes, and weekly totals per area are dominated by order timing (which week a big store's order lands). That lumpiness is the likely source of the large, non-replicating train effects (rows 1, 4, 16, 17).
- **Ames home weeks** have a positive sign in both periods (+9%, +14%) but do not pass. Even if real, they would be a deterministic schedule effect and not something Kalshi can hedge.
- **Weather** has no effect on statewide spirits orders.

## Tests run

- **18 candidates:** 12 football and 6 weather, each fitted on train and on holdout, so 36 fits. BH was applied over the 18 train p-values.
- **Not tested:** liquor-group (vodka, whiskey, etc.) splits. They are in the parquet but were not tested, to keep the count down.

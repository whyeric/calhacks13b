# R4 sfparking: SF parking meter revenue vs SFO weather and Warriors/Giants games

**Question.** Does real SFMTA parking meter revenue (citywide, and for the blocks around Chase Center and Oracle Park) move with a Kalshi-settleable event: SFO rain or high temperature, or a Warriors or Giants win?

**Verdict: NOT FOUND for anything Kalshi can settle.** Home games have huge effects that replicate, but a home game is on the published schedule, so no contract settles on it (criterion 4). Every weather and win effect failed to replicate on the holdout.

## Data
- **Revenue:** SFMTA Parking Meter Detailed Revenue Transactions (data.sf.gov `imvp-dq3v`, 215M rows, 2017-01 to 2026-10). I aggregated it server-side with SoQL to daily `sum(gross_paid_amt)` by session start date.
  - `city`: all meters, about $188k per Mon–Sat day in train.
  - `chase`: 36 street blocks with a meter within 600 m of Chase Center, about $4.9k/day.
  - `oracle`: 34 street blocks within 600 m of Oracle Park, about $7.9k/day.
  - The block lists come from the meter inventory `8vzz-qzz9` via `within_circle`.
- **Weather:** GHCN-Daily `USW00023234` (SFO). This is CLISFO, the exact station that `KXHIGHTSFO` (daily high, "> T°F" / "< T°F") and `KXRAINSFOM` (monthly SFO precipitation > X in) settle on. **Kalshi has no daily SF rain contract.** Daily rain is tested for completeness; its tradable form is the monthly test.
- **Games:** ESPN team schedules, regular plus post season, dated by the Pacific local start time.
  - Warriors: home games at Chase Center only (from 2019-10).
  - Giants: home games at Oracle Park.

## Method
- **Daily model:** `log(rev) ~ year-month FE + DOW FE + holiday + event`, with HAC(7) errors and t on df_resid. Sundays are dropped (meters mostly free).
- **Win tests** include the home-game dummy, so the win coefficient is win vs loss on home days.
- **Periods:** train 2017–2019 plus 2022–2023 (COVID 2020–21 dropped); holdout 2024-01 to 2026-09. Each is fitted independently.
- **Gap filter:** days with revenue below 30% of their (year-month, DOW) median are dropped as transmission gaps (city 38, chase 45, oracle 55 days).
- **Monthly model:** `log(city monthly rev) ~ month-of-year FE + year FE + {precip in, rain days}`, HC3, complete months only.
- **Strikes:** hot is tmax > 75°F and cold is tmax < 60°F, both fixed in advance.
- **Multiple comparisons:** 26 tests. BH at 10% is applied separately to the train p-values and the holdout p-values.

## Results (beta = log points; p_bh = BH-adjusted)

| series | event | train β [90% CI] | n_ev | p_bh | holdout β [90% CI] | n_ev | p_bh | verdict |
|---|---|---|---|---|---|---|---|---|
| city | rain ≥0.01 | −0.017 [−0.026, −0.008] | 271 | 0.004 | −0.027 [−0.061, +0.008] | 136 | 0.31 | not found |
| city | rain ≥0.25 | −0.039 [−0.052, −0.025] | 109 | 0.000 | −0.007 [−0.037, +0.024] | 50 | 0.81 | not found |
| city | tmax>75 | +0.003 [−0.007, +0.012] | 208 | 0.81 | −0.081 [−0.135, −0.026] | 90 | 0.035 | not found |
| city | tmax<60 | −0.006 [−0.018, +0.005] | 278 | 0.56 | +0.028 [−0.010, +0.065] | 137 | 0.31 | not found |
| city | GSW home | +0.034 [+0.024, +0.044] | 101 | 0.000 | +0.062 [+0.039, +0.086] | 93 | 0.000 | real, not settleable |
| city | GSW win | +0.025 [+0.000, +0.050] | 70 | 0.22 | −0.006 [−0.046, +0.035] | 53 | 0.89 | not found |
| city | SFG home | +0.088 [+0.081, +0.094] | 338 | 0.000 | +0.083 [+0.045, +0.121] | 202 | 0.002 | real, not settleable |
| city | SFG win | +0.005 [−0.001, +0.011] | 166 | 0.31 | +0.074 [+0.026, +0.121] | 96 | 0.030 | not found |
| chase | rain ≥0.01 | −0.008 [−0.058, +0.042] | 270 | 0.81 | −0.076 [−0.152, −0.001] | 135 | 0.18 | not found |
| chase | rain ≥0.25 | +0.011 [−0.061, +0.084] | 109 | 0.81 | −0.187 [−0.288, −0.087] | 50 | 0.008 | not found |
| chase | tmax>75 | +0.012 [−0.058, +0.081] | 206 | 0.81 | −0.152 [−0.246, −0.058] | 90 | 0.026 | not found |
| chase | tmax<60 | −0.114 [−0.172, −0.057] | 278 | 0.003 | −0.072 [−0.156, +0.011] | 135 | 0.25 | not found |
| chase | GSW home | +0.650 [+0.582, +0.718] | 101 | 0.000 | +0.642 [+0.583, +0.702] | 94 | 0.000 | real, not settleable |
| chase | GSW win | +0.105 [−0.000, +0.209] | 70 | 0.22 | +0.024 [−0.062, +0.110] | 54 | 0.77 | not found |
| chase | SFG home | +0.833 [+0.791, +0.874] | 338 | 0.000 | +0.574 [+0.514, +0.635] | 202 | 0.000 | real, not settleable |
| chase | SFG win | +0.006 [−0.036, +0.048] | 166 | 0.81 | +0.119 [+0.042, +0.197] | 96 | 0.030 | not found |
| oracle | rain ≥0.01 | −0.022 [−0.062, +0.018] | 269 | 0.56 | −0.041 [−0.118, +0.037] | 134 | 0.50 | not found |
| oracle | rain ≥0.25 | −0.038 [−0.082, +0.006] | 108 | 0.31 | −0.102 [−0.181, −0.022] | 49 | 0.071 | not found |
| oracle | tmax>75 | −0.009 [−0.068, +0.049] | 207 | 0.81 | −0.097 [−0.207, +0.013] | 88 | 0.25 | not found |
| oracle | tmax<60 | −0.105 [−0.156, −0.055] | 278 | 0.002 | −0.003 [−0.072, +0.065] | 135 | 0.94 | not found |
| oracle | GSW home | +0.166 [+0.118, +0.214] | 101 | 0.000 | +0.206 [+0.144, +0.268] | 93 | 0.000 | real, not settleable |
| oracle | GSW win | +0.064 [−0.021, +0.150] | 70 | 0.37 | +0.072 [−0.026, +0.170] | 53 | 0.31 | not found |
| oracle | SFG home | +0.784 [+0.739, +0.828] | 338 | 0.000 | +0.826 [+0.763, +0.890] | 202 | 0.000 | real, not settleable |
| oracle | SFG win | +0.025 [−0.022, +0.072] | 166 | 0.56 | +0.100 [+0.026, +0.173] | 96 | 0.057 | not found |
| city monthly | precip in | +0.001 [−0.004, +0.006] | – | 0.81 | −0.002 [−0.048, +0.043] | – | 0.94 | not found |
| city monthly | rain days | +0.000 [−0.002, +0.003] | – | 0.81 | +0.006 [−0.011, +0.023] | – | 0.68 | not found |

Full output, including the dollar effects, is in `output.txt`.

## Reading it
- **Game days are the big, stable driver, but they are not hedgeable.** Meters near Chase Center earn about +90% (e^0.65) on Warriors home days. Meters near Oracle Park earn about +120% (e^0.8) on Giants home days, roughly +$6k/day. Both replicate tightly on the holdout. SFMTA's special-event meter pricing plausibly drives this.
  - Because the schedule is known months ahead, this belongs in the revenue forecast, not in a Kalshi hedge.
  - The two areas overlap in game exposure: Giants days lift the Chase blocks too, because those blocks are close to Oracle Park's lots.
- **Wins don't matter on train.** Every win coefficient is null on train. Meter revenue is mostly paid before the result is known, so this is expected. Giants-win betas are positive on the holdout (+7–12%, BH ≈ 0.03–0.06) but sit at zero on train. Treat that as noise or a playoff-run artefact, not an effect.
- **Weather doesn't replicate.**
  - Citywide rain is −1.7% on train with a tight CI. On the holdout the point estimate is a similar −2.7%, but the CI includes 0. This matches the small rain effect seen in NYC, but it does not pass.
  - Cold-day effects near the arenas (−11%) and hot-day effects on the holdout each show up in only one period.
  - Monthly SFO precipitation, the only SF rain Kalshi actually lists (`KXRAINSFOM`), has no effect on monthly revenue.
- **Hedge backtest:** not run, because no settleable event was FOUND. A backtest on home-game days is not meaningful: there is no contract, and the outcome is known in advance.

## Reproduce
`cd backend && .venv/bin/python ../experiments/bar/r4-sfparking/sfparking.py`

The first run makes about 120 SoQL aggregate calls (about 3 minutes). Results are cached in `scratchpad/r2-cache/r4sf_*`.

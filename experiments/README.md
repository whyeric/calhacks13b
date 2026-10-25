# Research: which event risks can a small business actually hedge?

About 40 experiments, run 2026-10-24 during the hackathon, ask one question: **does a Kalshi-settleable event measurably and repeatably move a business's revenue, and does hedging it make income steadier?**

Each folder under `bar/` has its own script and `RESULTS.md` with the full tables. This page covers the method, the verdicts and what changed in the product.

## Method

The early rounds produced several convincing results that fell apart a year later. Every experiment from round 2 on had to clear all of these before counting as **FOUND**:

1. **Mechanism first.** The causal chain is written down before any fit (rounds 6–8).
2. **Train, then an independent holdout.** The effect must be significant (90% CI excludes 0, at least 10 event days) on a training period. It must then **replicate with the same sign** on a later, non-overlapping period refit on its own.
3. **Multiple comparisons.** Benjamini-Hochberg at 10% across every test in the experiment, with the count reported.
4. **Placebos.** Shifted dates (the day before, a week earlier), a wrong city, unaffected neighborhoods, and within-month permutation.
5. **Basis.** The event is something a Kalshi contract settles on. Weather uses the **NOAA GHCN station record Kalshi settles on** (Central Park USW00094728 for NYC), not reanalysis.
6. **Hedge backtest.** Out of sample, at real or train-frequency prices plus Kalshi's fee: does the hedge reduce variance or improve the worst days?

Lessons learned along the way, now applied to the product:

- **Seasonality.** Smooth seasonal harmonics leave month-level drift that confounds weather effects. Year-month fixed effects fix it (`bar/r3-noaa`).
- **Weather source.** Open-Meteo calls rain on 40–47% of days against NOAA's 31–38%, and those extra days carry no effect (`bar/r3-noaa`, `bar/r2-mta`).
- **Error bars.** HAC standard errors are too narrow for daily foot-traffic series (placebos fire about 1.5× too often, `bar/r7-deferral`), and they collapse for events lasting under 10 days (`bar/r7-displacement`). Small effects (±1%) are treated as suspect.
- **Data privacy.** Dewey venue data is licensed. Only aggregates and opaque ids are stored, and no venue names or daily single-venue series.

## What held up (FOUND)

| Exposure | Effect (train → holdout) | Hedge result | Folder |
|---|---|---|---|
| **Playoff home games**, foot traffic within 0.5 km of MSG | +5.7% → +5.7% on playoff nights, positive in all 4 runs | Series hedge cuts season swing 42–72% (simulated) | `bar/r5-nycplayoffs` |
| **Playoff home games**, bike trips ≤450 m of Wrigley (Cubs) | +126% → +107%, every season | "Hosts ≥ N games" ladder cuts swing 76% (simulated) | `bar/r6-wrigley` |
| **Playoff home games**, rideshare driver earnings near MSG | +40% → +36%, every season 2022–26 | Per-round series hedge −67% (7 real seasons) | `bar/r5-mobility` |
| **Playoff home games**, SF meters near Chase Center | +0.35 → +0.62 log pts | −24–40% simulated; little in 5 real seasons | `bar/r5-sfplayoffs` |
| **Kalshi playoff contracts** themselves | Series prices beat a coin flip (Brier 0.207) | Rolling hedge removed **~87%** of home-game variance at 2–3% cost on real 2025–26 prices | `bar/r5-markets` |
| **DC government shutdown**, federal-district bike activity | −15% (2018–19) → −20% (2025) | A duration ladder covered most of 2025's loss; "shutdown happens" lost money | `bar/r8-dcshutdown` |
| **Texas heat** (>95°F) → fixed-rate power bill | +$32/day, significant in all 8 years | SD −4–6%, worst days up to −11% | `bar/r4-ercot` |
| **Rain** → bike share (Citi Bike JC, NYC counters) | −20% trips | **SD −9–13%** (daily KXRAIN) | `bar/r2-citibike` |
| **Rain** → MTA ridership (all 5 modes) | −2% to −5% | SD about −2% | `bar/r2-mta`, `bar/r4-mtahourly` |
| **Rain** → Uber/Lyft demand | +2.2% → +2.4% | about −1% | `bar/r2-taxi` |
| **Rain** → NYC foot traffic (aggregated) | −2% to −3%; the loss spans day −1 to day +1 (~1.4× same-day) | about −2% | `bar/r2-aggregate`, `bar/r7-deferral` |
| **Bars on away playoff nights** (Manhattan) | −3.4% → −3.5% (people watch at home) | Small stakes | `bar/r5-bars` |
| **Snow** → Broadway grosses | −2.2% → −2.5% | Unhedgeable (monthly contract doesn't track it) | `bar/r6-broadway` |

## What didn't (NOT FOUND or not hedgeable)

| Hypothesis | Why it failed | Folder |
|---|---|---|
| Knicks/Rangers **wins** move nearby revenue | No effect in any data, at any granularity, including station-hour subway | `bar/arena`, `bar/r4-mtahourly`, `bar/stakes`, `bar/timing` |
| The original "bar across from MSG" has a weather exposure | One venue's visits × $35 are ~50% noise; 8 approaches null | `bar/history`, `bar/venues`, `bar/model`, `bar/rain` |
| Taxi rain and heat (one zone) | Significant on the train year, flipped or vanished on holdout; hedging *added* variance | `bar/hedgesim`, `bar/r3-noaa` |
| Weekly or monthly weather totals | Effects flip sign between years; monthly series too short | `bar/r2-horizon` |
| Pooling 358 venues near MSG | Tight null for rain (±1.3%) | `bar/r2-pooling` |
| Natural hedge (subway vs Uber/Lyft) | Opposite on rain days, but correlated +0.42 otherwise; portfolio SD +11% | `bar/r4-natural` |
| Storms in other cities → NYC Penn area | Wrong sign, citywide, placebo cities hit as often | `bar/r6-crosscity` |
| Gas prices → bike share / rideshare | Sign flips; future prices "predict" as well | `bar/r6-gas` |
| Game outcomes → electricity load | The playoff dip appears the day *before* games too | `bar/r6-tvpower` |
| Austin heat → Sixth Street nightlife | Wrong sign | `bar/r6-austin` |
| Market moves / Fed / CPI → FiDi bars | Residential placebo moved as much | `bar/r7-fidi` |
| TSA travel → Midtown tourist restaurants | Pure seasonality; last year's number predicts as well | `bar/r7-tsa` |
| Big-TV nights generally → bars | Knicks/Rangers result doesn't generalize | `bar/r7-displacement` |
| Iowa liquor orders vs football and weather | Train effects vanish on holdout (delivery timing) | `bar/r4-iowa` |
| SF parking vs weather | Not settleable (no daily SF rain contract); rain doesn't replicate | `bar/r4-sfparking` |

## What changed in the product

- **Playoff home games.** Added as an exposure, with a season-level hedge on Kalshi advancement futures. Sizing uses the minimum-variance math from `bar/r5-markets/hedge.py`.
- **"unstable" decline rule.** An exposure must hold up on the most recent window before the desk quotes it.
- **Settlement data.** Weather settlement and fair prices use NOAA, the source Kalshi settles on.
- **Rain sizing.** Rain hedges are sized at 1.0–1.4× the same-day effect, never haircut for "deferral".
- **Chat.** It declines to predict games or weather. The research shows outcomes aren't the exposure.

## Data sources

All public except Dewey, which is licensed and aggregate-only:
- MTA ridership (data.ny.gov), NYC TLC trip records (via NYC Open Data), Citi Bike / Capital Bikeshare / Divvy / Austin B-cycle trip data
- NOAA GHCN-Daily, ERCOT load and prices, SFMTA meter revenue, the Broadway League (TidyTuesday copy), EIA gas prices, TSA checkpoint counts, ESPN schedules
- The Kalshi public API (markets, settled history, candlesticks)

Raw downloads were cached outside the repo; only scripts and summary results are committed.

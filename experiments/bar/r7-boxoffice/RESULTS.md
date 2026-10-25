# R7 boxoffice: blockbuster weekends and restaurants next to Manhattan multiplexes

## Mechanism (written before fitting)

A blockbuster opens bigger than expected, so more people go to the big Manhattan multiplexes
that weekend, so restaurants and bars within about 300 m of those multiplexes get more visits
before and after showtimes than similar venues at least 1 km from any cinema. A Kalshi contract
would settle on the first step: opening-weekend domestic gross versus a strike.

Predictions, if the chain is real:
1. The near-minus-control (DiD) log visits on Fri–Sun rise with log total weekend gross and with
   the gross of new openers, and jump on mega-opening weekends (> $100M 3-day).
2. The effect is in the DiD, not only in near-basket levels, which share citywide weekend swings.
3. Placebo: the same events assigned to the weekend BEFORE the opening show nothing.
4. The effect replicates on the independent holdout.

(Results below.)

## Verdict: NOT FOUND, and there is no Kalshi contract to settle on (basis fails)

1. **Kalshi:** no box-office contracts exist. I scanned the full `/series` list (15,392 series) and
   all ~907k events (settled, open and closed). No KXBOX / opening-weekend / domestic-gross market
   exists, live or settled. The only series that settles on Box Office Mojo is `KXSLATECOUNT`,
   which counts wide releases per quarter, not grosses. Kalshi's movie markets are Rotten Tomatoes
   scores (`KXRT*`) and streaming top-movie rankings. So criterion 4 (basis) cannot be met even
   if the effect were real.
2. **Effect:** no event passes train + holdout + BH. The mega-opening jump is about +1% on train
   (9 weekends, under the 10-event floor, BH q = 0.19) and +0.0% on holdout. The placebo
   (the weekend before) is just as large.

## Data
- **Dewey** (balanced panel: every week present, < 5% flat weeks). Three NAICS codes: 722410 bars,
  722511 full-service, 722513 limited-service.
  - **Near basket:** 441 venues within 300 m of AMC Empire 25 / Regal Times Square, AMC Lincoln
    Square, Regal Union Square, AMC 34th St and AMC 84th St (47 bars, 310 full-service, 84 limited).
  - **Control basket:** 1,775 venues at least 1 km from those multiplexes and from 16 other
    Manhattan cinemas. It is reweighted to the near basket's NAICS mix and averaged per venue.
  - Coordinates come from public knowledge and are in `run.py`. Only aggregates are written
    (`basket_counts.csv`).
- **Box office:** The Numbers weekend charts, 146 weekends from 2024-01-05 to 2026-10-16,
  fetched at 1 request every 3 s. Their robots.txt allows generic agents.
  **Box Office Mojo was not used:** its robots.txt disallows `User-agent: *` and its terms forbid
  automated access, so I stopped there and did not try to get around it.
  `boxoffice_weekends.csv` has the weekend totals, new-opener gross and top opener.
  There are 15 mega weekends (top new opener > $100M 3-day), listed in `mega_weekends.csv`:
  - 9 in train: Inside Out 2, Deadpool & Wolverine, Beetlejuice Beetlejuice, Wicked, Moana 2,
    Minecraft, Lilo & Stitch, Superman, Fantastic Four.
  - 6 in holdout: Wicked: For Good, Zootopia 2, Super Mario Galaxy, Toy Story 5, The Odyssey,
    Spider-Man: Brand New Day.
- **Weather:** NOAA GHCN Central Park (rain days in the window as a control).

## Method
- **Unit:** the weekend (Fri+Sat+Sun visits).
- **Outcome:** y = log(near) − log(control), the difference-in-differences.
- **Model:** y ~ year-month FE + holiday weekend + rain-days + event, with HAC(4) errors.
- **Events:**
  - log total weekend gross (effect reported as % per doubling);
  - log gross of new openers;
  - mega-opening dummy.
- **Specs:** DiD with all NAICS codes, near-only levels, DiD per NAICS code, control-only, Mon–Thu
  after the weekend, and the placebo (the next weekend's event assigned to this one, i.e. the
  weekend BEFORE the opening).
- **Periods:** train 2024-01-05 to 2025-09-28 (91 weekends), holdout 2025-10-03 to 2026-09-27
  (52 weekends), refit independently.
- **Multiple comparisons:** BH across the **24 train tests**.

## Results (DiD, % effect, 90% CI; full table in `results.csv` and `verdict.csv`)

| spec | event | train | n ev | BH q | holdout | n ev | FOUND |
|---|---|---|---|---|---|---|---|
| main DiD | log total gross | +0.31 [−0.66, +1.28] | 91 | 0.62 | +1.54 [−0.09, +3.18] | 52 | no |
| main DiD | log new-opener gross | −0.37 [−0.54, −0.20] * | 91 | 0.005 | +0.11 [−0.53, +0.74] | 52 | no |
| main DiD | mega > $100M | +1.20 [+0.01, +2.38] | **9** | 0.19 | +0.02 [−1.80, +1.83] | 6 | no |
| bars DiD | mega | +0.50 [−1.18, +2.17] | 9 | 0.63 | +1.32 [−3.74, +6.38] | 6 | no |
| full-svc DiD | mega | +1.11 [−0.49, +2.72] | 9 | 0.39 | −0.12 [−2.70, +2.46] | 6 | no |
| limited DiD | log total | +1.51 [+0.14, +2.87] | 91 | 0.18 | +1.34 [−0.09, +2.78] | 52 | no |
| limited DiD | mega | +2.47 [+0.23, +4.71] | 9 | 0.18 | −1.28 [−4.61, +2.05] | 6 | no |
| Mon–Thu after, DiD | log total | +2.24 [+0.59, +3.90] | 91 | 0.13 | +1.40 [−0.27, +3.06] | 51 | no |
| **placebo: weekend before** | log total | +0.98 [−0.44, +2.39] | 91 | 0.39 | +1.55 [−0.03, +3.14] | 52 | (should be 0) |
| **placebo: weekend before** | mega | +1.41 [−0.87, +3.69] | 9 | 0.44 | +1.70 [−1.23, +4.63] | 6 | (should be 0) |

\* **Artifact.** Only one weekend (2024-01-26) had no new wide opener, so log(1 + 0) = 0 is a
huge-leverage point. Without it, train is +0.07 [−0.37, +0.51] and holdout is
+0.11 [−0.53, +0.74]. The near-only and per-NAICS `log_new` "hits" come from the same weekend.

**Event study** (DiD residual net of year-month mean, averaged over 15 mega openings, %), by
weekends from the opening:

| weekend | −2 | −1 | 0 (opening) | +1 | +2 |
|---|---|---|---|---|---|
| DiD residual | +0.14 ± 0.78 | +0.59 ± 0.69 | +0.67 ± 0.60 | −0.74 ± 0.81 | −0.47 ± 1.09 |

The opening weekend looks no different from the weekend before it.

## Reading
- The point estimates for total gross lean positive: about +0.3 to +1.5% per doubling of the
  weekend gross, and the Mon–Thu spec is the most consistent (+2.2 train, +1.4 holdout).
- But the weekend-before placebo is the same size, and no effect clears train + holdout + BH.
- Even a real +1% effect on a $31k Fri–Sun weekend per near venue (Dewey visits × $35) is about
  $300 per mega weekend, and only about 6–9 such weekends happen a year.
- Possible reasons the signal is weak:
  - multiplex audiences are a small share of Midtown/UWS foot traffic;
  - mega openings cluster in summer and holiday weeks, which the year-month FE absorbs;
  - Dewey's weekly-panel noise.

## Basis / hedge
There is no hedge to backtest: Kalshi has no box-office settlement. The nearest proxy would be
"Rotten Tomatoes score ≥ X" (`KXRT*`), a third step removed from attendance, and I did not test it.

Tests run: 24 train tests in the BH family (8 specs × 3 events), plus holdout and pooled refits,
one event study and one leverage sensitivity check. Nothing passes.

## Files
`run.py` (analysis), `fetch_weekends.py` (The Numbers fetch), `kalshi_scan.py` (full event
scan), `results.csv`, `verdict.csv`, `event_study.csv`, `mega_weekends.csv`,
`boxoffice_weekends.csv`, `basket_counts.csv`. The raw HTML and Kalshi scan are cached in
r2-cache/r7boxoffice_*.

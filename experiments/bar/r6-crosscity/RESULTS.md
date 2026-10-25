# R6-CROSSCITY: does weather in other cities move Penn Station / MSG demand?

## Pre-registered mechanism (written before any fit)

Chain: a storm, snow or extreme heat at a remote airline hub or Northeast Corridor city (Chicago O'Hare, DC Reagan,
Boston Logan, Philadelphia, Atlanta, Denver) leads to ground stops, cancellations and Amtrak/NJT delays. That strands
or reroutes travelers through NYC: missed connections at EWR/LGA/JFK, and rail passengers stuck at Penn. They pass time
near Penn/MSG, so foot traffic and spending there rise. The predicted sign is **positive** at Penn/MSG on the event day
(lag 0) and possibly the day after (lag 1). The opposite chain also exists: cancelled inbound trips mean *fewer*
visitors arriving. So I test two-sided but read the result against the + prediction.

Falsification tests:
1. **Wrong-city placebo:** Phoenix (PHX) and Los Angeles (LAX) have Kalshi weather contracts but no NYC rail link and
   small hub overlap. They should show nothing.
2. **Lead placebo:** remote weather 3 days in the future should show nothing.
3. **Penn-specific test:** a real chain should raise Penn/MSG *relative to* the rest of NYC. A shared regional storm
   moves both.

Main confounder: shared regional weather (a storm hitting PHL/BOS/DCA also hits NYC). Every fit controls for Central
Park weather (rain ≥ 0.01, rain ≥ 0.5, snow ≥ 1, tmax and tmax², prior-day rain).

Remaining sections are filled from `run.py` output below.

## Data

- **Penn/MSG demand:** Dewey visits, balanced panel (same filter as r2-aggregate): 277 stores within 0.5 km of MSG,
  710 in the MSG ZIP basket, and 6,736 "rest of NYC" stores (outside those ZIPs, > 2 km away) used as a control.
  Train is 2024-01..2025-03; holdout is 2025-04..2026-09.
- **Penn Station entries:** MTA hourly (r4-mtahourly cache), complexes 164 + 318, daily and 17–24h, controlled for
  log(system entries in the same window). Train is 2022–23; holdout is 2024. I did not pull LIRR/NJT or BTS (time box).
- **Remote weather:** GHCN-D at the Kalshi settlement stations, confirmed from market rules where listed:
  KXRAINCHIM = CLIORD, KXHIGHTDC = CLIDCA, KXHIGHTBOS / KXRAINSBOS = CLIBOS (KBOS), KXPHILHIGH = CLIPHL,
  KXHIGHLAX = CLILAX, KXHIGHTEMPDEN = CLIDEN. Atlanta is ATL (USW00013874). Placebos are PHX (USW00023183) and LAX.
- **Events** per city: rain ≥ 0.5 in, snow ≥ 1 in, thunder (GHCN WT03), and heat (tmax ≥ 95 F; PHX ≥ 110, LAX ≥ 90).
  Plus a composite, HUB_storm = any of ORD/DCA/BOS/PHL/ATL with rain ≥ 0.5, snow ≥ 1 or thunder. Each is tested at
  lag 0 and lag 1.

## Method

log(outcome) ~ remote-event flag + DOW + year-month FE + holiday + MSG home game + Central Park weather (rain ≥ 0.01,
rain ≥ 0.5, snow ≥ 1, tmax, tmax², prior-day rain), with HAC(7) errors. The MTA fits add log(system) as a control.
The holdout is refit independently. **184 train tests** (4 outcomes × 33 events × 2 lags, dropping fits with fewer
than 10 event days); BH at 10% is applied across all 184, placebo cities included. Run from backend/:
`.venv/bin/python ../experiments/bar/r6-crosscity/run.py`. The full table is in `results.csv`, the log in `output.txt`.

## Results

12 of 184 train fits survive BH. Three also replicate on the holdout and so meet the formal FOUND bar:

| outcome | event | train % [90% CI] | n | BH q | holdout % [90% CI] | n | formal |
|---|---|---|---|---|---|---|---|
| Dewey ≤ 0.5 km | HUB_storm, lag 0 | −2.34 [−3.64, −1.03] | 208 | 0.060 | −2.05 [−3.30, −0.80] | 298 | pass |
| Dewey MSG ZIP | HUB_storm, lag 0 | −2.07 [−3.04, −1.11] | 208 | 0.025 | −1.70 [−2.62, −0.79] | 298 | pass |
| Dewey MSG ZIP | ORD rain ≥ 0.5, lag 0 | −3.29 [−4.99, −1.59] | 27 | 0.044 | −1.76 [−2.82, −0.70] | 39 | pass |
| Dewey ≤ 0.5 km | ORD rain ≥ 0.5, lag 0 | −3.91 [−6.34, −1.48] | 27 | 0.106 | −1.74 [−3.35, −0.14] | 39 | fails BH |
| MTA Penn | HUB_storm, lag 0 | −0.46 [−1.13, +0.22] | 289 | 0.62 | −0.08 [−1.22, +1.05] | 166 | null |
| MTA Penn 17–24h | HUB_storm, lag 0 | −0.39 [−1.37, +0.59] | 289 | 0.81 | +0.12 [−1.38, +1.62] | 166 | null |

## Falsification: all three formal passes fail

1. **Wrong sign.** The chain predicts *more* activity near Penn. Every replicated hit is *negative*.
2. **Not Penn-specific (the decisive test).** Rest-of-NYC Dewey visits fall by the same amount on HUB_storm days:
   −2.10% [−2.79, −1.41] train and −1.50% [−2.17, −0.83] holdout. Once log(rest-of-NYC) is a control, the Penn/MSG
   effect is zero: ≤ 0.5 km −0.03 [−1.09, +1.03] train and −0.61 [−1.67, +0.44] holdout; MSG ZIP −0.06 / −0.47, both
   CIs straddle 0. ORD rain is the same: relative −0.17 [−1.84, +1.49] on the holdout. So a remote storm is not
   sending anyone to Penn; it lines up with a citywide dip.
3. **Penn Station entries see nothing.** MTA Penn relative to system entries is null for HUB_storm in both periods,
   daily and evening. Travelers stranded at Penn would show up there first.
4. **Placebo cities do just as well.** Nominal p < 0.10 rate on train: real cities 21%, PHX/LAX 32%. Rate of
   same-sign hits in both periods: real 4.5%, placebo 3.6%. Phoenix thunder alone is train-significant on MTA Penn
   (q = 0.048) and doesn't replicate. The design gives about the same hit rate whether or not a travel link exists.
5. **Lead placebo is not clean either.** HUB_storm three days *ahead* is −0.85 [−1.62, −0.08] on the MSG-ZIP
   holdout. That points to persistent regional weather regimes, not a same-day travel shock.

The likely explanation for the citywide −2%: HUB_storm fires on 46% of days. In effect it flags "an active eastern
weather pattern", which comes with cloud, humidity and rain at hours or places the Central Park daily totals miss.
The effect survives on dry Central Park days (−2.0 to −2.6%), so it isn't just NYC rain leaking through. But it is
regional, not a travel chain, and no single Kalshi contract settles on it.

## Hedge backtest (formal passes only, holdout)

| outcome | event | SD unhedged → hedged | 5th pct unhedged → hedged |
|---|---|---|---|
| Dewey ≤ 0.5 km | HUB_storm | 6241 → 6209 (−0.5%) | −9674 → −9354 |
| Dewey MSG ZIP | ORD rain ≥ 0.5 | 10268 → 10264 (−0.04%) | −15730 → −16063 (worse) |
| Dewey MSG ZIP | HUB_storm | 10268 → 10195 (−0.7%) | −15730 → −15479 |

(Units are visits; $ = × $35.) Even taking the betas at face value, the hedge barely moves risk.

**Basis:** HUB_storm is a 5-city composite that no Kalshi contract settles on. Chicago daily rain ≥ 0.5 in isn't
listed either; Kalshi has KXRAINCHIM, monthly at CLIORD. The daily remote contracts that do exist are highs
(KXHIGHTDC, KXHIGHTBOS, KXPHILHIGH, KXHIGHLAX), and the heat tests on them do not replicate, apart from PHL heat on
MTA Penn: q = 0.34, n = 16 / 14, and its lead-3 and dry-day checks are noisy.

## Verdict

**NOT FOUND.** Three fits formally pass train + holdout + BH, but all three fail the pre-registered falsification:
the sign is opposite to the mechanism, the effect is the same in the rest of NYC, Penn Station subway entries don't
move, and the placebo cities have the same hit rate. No remote-city Kalshi contract hedges Penn/MSG demand. The
stranded-traveler chain is not visible in daily foot traffic or subway entries. Not tested: LIRR/NJT ridership, BTS
cancellations as the mediator, and hourly or overnight hotel/bar data, where a small stranded-traveler effect might
still exist.

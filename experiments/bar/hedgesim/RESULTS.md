# Hedge backtest: does hedging the measured exposure make holdout income steadier?

Script: `hedgesim.py` (run from `backend/`: `.venv/bin/python ../experiments/bar/hedgesim/hedgesim.py`).
Businesses: taxi (zone 186) and the bar near MSG (`p_afa556030e60`, revenue = visits x $35, estimated).

## Method
- `fit_exposures` on train (365 days, from 2024-10-01), strike hot = 85F (strict `>`). Size = |beta| $1 contracts,
  using the point estimate, the CI90 lower bound and the CI90 upper bound (the sign of the bound decides the side).
- Side: beta > 0 -> buy NO, beta < 0 -> buy YES. Price = train frequency of that side + $0.02 ("frequency" tier).
  Fee = ceil-to-cent(0.07 x C x P x (1-P)) per order; a harsher per-contract rounding is also shown (it barely matters).
- Settlement: rain/hot on the Central Park station series (what the contracts settle on); home_win on the game.
  Eligible days: every holdout day for rain/hot (335), holdout home games for home_win (88). A "perfect basis" row
  settles on the business's own MSG flag instead.
- Metrics on the 335 holdout days: std dev, 5th percentile, mean (cost = mean drop), sd of calendar-adjusted revenue
  (revenue minus the train model's DOW/season/controls baseline), and hit rate = share of eligible days where the
  hedge paid, split by whether revenue was below vs above the model's expected value.

## Results (holdout, 335 days; sd change < 0 means steadier)

| business / event | sig? | sizing | beta ($) | side @ price | fee/day | sd change | resid-sd change | p5 unhedged -> hedged | cost/day | hedge paid when below / above expected |
|---|---|---|---|---|---|---|---|---|---|---|
| taxi rain | yes, CI [533, 3,890], n=148 | point | 2,212 | NO @ 0.62 | 36 | **+0.76%** | +0.57% | 50,029 -> 48,787 | 212 | 52% / 56% |
| | | CI lo | 533 | NO @ 0.62 | 9 | +0.11% | +0.04% | 50,029 -> 49,860 | 51 | |
| | | CI hi | 3,890 | NO @ 0.62 | 64 | +1.85% | +1.70% | 50,029 -> 47,714 | 373 | |
| | | point, own flag | 2,212 | NO @ 0.62 | 37 | +0.85% | +0.67% | 50,029 -> 48,805 | 227 | 50% / 56% |
| taxi hot >85F | yes, CI [1,281, 6,654], n=55 | point | 3,967 | NO @ 0.88 | 30 | **+1.26%** | +1.62% | 50,029 -> 49,735 | -28 | 83% / 94% |
| | | CI lo | 1,281 | NO @ 0.88 | 10 | +0.30% | +0.38% | 50,029 -> 50,179 | -9 | |
| | | CI hi | 6,654 | NO @ 0.88 | 51 | +2.66% | +3.46% | 50,029 -> 49,316 | -47 | |
| bar rain | no, CI [-992, 301], n=148 | point | -345 | YES @ 0.42 | 6 | -0.22% | -0.09% | 4,088 -> 4,084 | -8 | 43% / 48% |
| | | CI lo | -992 | YES @ 0.42 | 17 | -0.34% | +0.06% | 4,088 -> 3,829 | -22 | |
| | | CI hi | +301 | NO @ 0.62 | 5 | +0.29% | +0.18% | 4,088 -> 4,038 | 29 | |
| bar home_win (noise) | no, CI [-4,351, 299], n=49 | point | -2,026 | YES @ 0.56 | 35 | **+0.87%** (+3.19% on game days) | +0.81% | 4,088 -> 3,952 | 1 | 50% / 72% |
| | | CI lo | -4,351 | YES @ 0.56 | 75 | +3.05% (+10.9% on game days) | +3.02% | 4,088 -> 3,885 | 2 | |
| | | CI hi | +299 | NO @ 0.48 | 5 | -0.03% | +0.01% | 4,088 -> 3,988 | 6 | |

Unhedged holdout sd: taxi $12,489, bar $5,148. Expected cost of each hedge (markup + fee) is small: about
$80/day for taxi rain point; the rest of the realised cost is luck (it rained on 46% of holdout days vs 40% in train,
so the NO legs paid less often). Negative cost on taxi hot = a cooler holdout (11% hot days vs 14% priced).

Why it fails (diagnostics printed by the script):
- **The effects did not hold out of sample.** Refitting the same model on holdout only: taxi rain 2,212 -> 303,
  taxi hot 3,967 -> -965 (sign flip), bar home_win -2,026 -> +588 (sign flip), bar rain -345 -> -291 (stable but tiny).
  The hedge pays when the train-era effect says revenue should be low; on holdout that no longer lines up
  (the hedge paid *more* often on above-expected days than below-expected ones, in every hedged row).
- **Even a perfect hedge buys almost nothing.** Upper bound with the exact beta and no pricing error:
  sd falls by at most 0.39% (taxi rain), 0.50% (taxi hot), 0.06% (bar rain), 1.0% (bar home_win). A binary
  event's variance is beta^2 p(1-p), which is ~1% of daily revenue variance here; DOW/season and idiosyncratic noise
  dominate. Holdout R2 is 0.24 (taxi) / 0.05 (bar) for the whole model, not just the event terms.
- Even in-sample (train), the taxi rain and hot hedges raise raw-revenue sd (+0.14%, +0.24%): the regression beta is a
  partial effect net of season/DOW, while the raw day-to-day swing is driven by those other terms.

## Verdict
No exposure is reduced net of cost on this holdout. Taxi rain and hot are "significant" on train, but hedging them
raised holdout sd by 0.8% and 1.3% (CI-hi sizing: 1.9% and 2.7%) and worsened the 5th-percentile day, because the
train effects shrank (rain) or flipped (hot) out of sample, and even a perfect hedge could only have cut sd by
under 0.5%. The bar's rain hedge shows a -0.2% sd change, which is noise-sized and comes from a non-significant
estimate, so no credit. Hedging the bar's insignificant home_win estimate is the clearest "don't hedge noise" case:
sd up 0.9% overall and 3.2% on game days at the point estimate, 3.1% / 10.9% at the CI-lo sizing, and the 5th
percentile drops from $4,088 to $3,952 (point) or $3,885 (CI lo); with the CI-hi sizing the side flips to NO and the
hedge does nothing (-0.03%). The gates (significance, size, support) are necessary but not sufficient: the
hedge also needs the effect to be stable out of sample and large relative to daily noise.

Caveats: one 335-day holdout (one season of each event); revenue for the bar is estimated from foot traffic;
4 exposures x 3 sizings = 12 main configurations plus 4 sensitivity rows; nothing was tuned on holdout.

**Demo-worthy?** Yes, as a sobering slide: "a significant beta is not a working hedge". The bar home_win row
(+3% to +11% sd on game days) is a concrete, honest illustration of why the desk refuses to hedge noise; it argues for
adding an out-of-sample stability check (holdout-refit beta same sign, CI overlap) before quoting a hedge.

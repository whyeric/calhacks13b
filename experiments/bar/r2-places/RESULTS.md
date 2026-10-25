# R2-places: which Dewey place types have real weather sensitivity?

Script: `places.py`, run from backend/ with `.venv/bin/python ../experiments/bar/r2-places/places.py` (about 10 s once cached). Every test is in `results_all.csv`, using opaque ids only (`v001`..`v300`, ranked by size). No names, addresses, raw IDs or daily series are written.

## Question
Does any kind of place (category, ZIP or single venue) in the Dewey Manhattan export lose or gain at least 5% of visits on Kalshi-settleable weather days, with the effect replicating out of sample?

## Data
- **Places:** the Dewey restaurants/bars export, 2024-01-01..2026-09-27, Manhattan ZIPs 10001-10282 (10,962 venues). The export has only three NAICS codes:
  - 722511 (full-service restaurants)
  - 722513 (limited-service restaurants)
  - 722410 (drinking places)

  These map to two TOP_CATEGORY values, and there are no other place types to survey.
- **Stable panel:** 9,869 venues with coverage ≥ 98% and < 5% "flat" weeks (all 7 days equal, which looks imputed). This panel feeds:
  - 6 category aggregates: all Manhattan, 3 NAICS, 2 TOP_CATEGORY;
  - 41 ZIP aggregates (ZIPs with ≥ 20 stable venues);
  - the 300 largest venues (693–4,654 mean daily visits; 139 are 722511, 135 are 722410 and 26 are 722513).
- **Weather:** Central Park from Open-Meteo, daily.
  - `rain` = precip ≥ 0.01 in, the KXRAIN settlement rule itself.
  - `hot` = tmax > 85 °F, the KXHIGHNY strict rule.

## Method
- **Model:** for each series and each period, fitted independently: `visits ~ DOW + season k=1,2 + holiday + linear trend + rain + hot`. This is `build_design` plus a trend term, with Newey-West HAC errors (7 lags) and z = 1.645. The effect is β divided by the period's mean visits.
- **Periods:** train 2024-01..2025-03 (185 rain days, 45 hot days); holdout 2025-04..2026-09 (252 rain days, 93 hot days).
- **Selection:** BH at 10% over all **694 train tests** (347 series × 2 events). A candidate must pass BH, have |effect| ≥ 5% and ≥ 10 event days.
- **FOUND:** additionally, the holdout has the same sign, its 90% CI excludes 0, and it passes BH at 10% across the candidates (one-sided).
- **Fixed in advance:** the spec, thresholds and panel filters were set before any results were seen, and nothing was tuned on the holdout.

## Results

### Summary by level (694 tests)
| Level | Tests | Raw train p<0.10 | Train BH pass | BH + ≥5% | Holdout replicates | FOUND |
|---|---|---|---|---|---|---|
| Category aggregates | 12 | 3 | 0 | 0 | 0 | 0 |
| ZIP aggregates | 82 | 21 | 1 | 0 | 0 | 0 |
| Single venues (top 300) | 600 | 113 | 4 | 4 | 3 | **3** |

### Category aggregates (effect as % of mean visits, 90% CI, BH-adjusted train p)
| Series | Event | Train effect [CI] | Train p_adj | Holdout effect [CI] | Verdict |
|---|---|---|---|---|---|
| Drinking places (722410) | rain | −2.1% [−3.5, −0.6] | 0.33 | −3.2% [−4.4, −2.1] | NOT FOUND: small, fails BH |
| Full-service (722511) | rain | −1.2% [−2.7, +0.4] | 0.67 | −1.6% [−2.5, −0.7] | NOT FOUND |
| Limited-service (722513) | rain | −0.5% [−1.9, +1.0] | 0.84 | −0.6% [−1.5, +0.2] | NOT FOUND |
| All Manhattan | rain | −1.3% [−2.8, +0.2] | 0.61 | −1.8% [−2.7, −1.0] | NOT FOUND |
| Drinking places | hot | +2.5% [−0.9, +6.0] | 0.68 | +0.5% [−1.5, +2.4] | NOT FOUND |
| Full-service | hot | +1.2% [−1.2, +3.5] | 0.80 | +0.9% [−0.1, +1.9] | NOT FOUND |
| Limited-service | hot | +3.6% [+1.1, +6.2] | 0.33 | +1.3% [0.0, +2.5] | NOT FOUND |
| All Manhattan | hot | +1.7% [−0.7, +4.1] | 0.69 | +0.8% [−0.3, +2.0] | NOT FOUND |

(The TOP_CATEGORY aggregates repeat these: "Drinking Places" is 722410, and "Restaurants" is 722511 plus 722513.)

### Train candidates (BH + ≥ 5%), single venues
| Venue | NAICS | Event | Train effect [CI] | Train p_adj | Holdout effect [CI] | Holdout p_adj | Verdict |
|---|---|---|---|---|---|---|---|
| v030 | 722410 bar | rain | −13.2% [−19.4, −6.9] | 0.078 | −9.2% [−15.5, −3.0] | 0.013 | **FOUND** |
| v241 | 722410 bar | rain | −13.1% [−18.0, −8.2] | 0.007 | −7.0% [−11.9, −2.1] | 0.013 | **FOUND** |
| v043 | 722511 restaurant | hot | +7.7% [+4.7, +10.6] | 0.007 | +5.6% [+2.1, +9.1] | 0.013 | **FOUND** |
| v167 | 722410 bar | hot | +11.6% [+6.2, +16.9] | 0.078 | +2.8% [−1.7, +7.4] | 0.151 | NOT FOUND (holdout fails) |

No ZIP aggregate is a candidate. The one ZIP that passed train BH had an effect under 5%.

### Venue-level signal is real but diffuse
- 90 venue tests had a train CI excluding 0 and |effect| ≥ 5%. Of these, 24 replicated on the holdout with the same sign and a significant CI, against about 4–5 expected by chance. Most of them do not survive train BH across 694 tests.
- Median venue rain effect, train / holdout:
  - bars: −2.1% / −3.4%
  - full-service restaurants: −1.2% / −0.8%
  - limited-service restaurants: +0.7% / +0.7%
- Rain is the more stable event: across aggregates the train and holdout effects line up, at −1% to −3% everywhere. Hot effects shrink by half or more on the holdout.

### Hedge backtest (bonus)
On every holdout day, buy |β|×$35 contracts of the side that pays when revenue is hurt. The price is the train frequency of that side + $0.02, plus a fee of 0.07·p·(1−p). SD is measured on revenue net of calendar and season.

| Venue / event | Price | Residual SD, unhedged → hedged | 5th pct day, unhedged → hedged | Net hedge P&L over holdout |
|---|---|---|---|---|
| v030 rain (buy YES) | 0.40 | 27,876 → 27,735 (−0.5%) | −33,891 → −34,002 (worse) | +$92k (the holdout was rainier: 46% vs 40% of days) |
| v241 rain (buy YES) | 0.40 | 9,959 → 9,943 (−0.2%) | −14,400 → −14,500 (worse) | +$37k (same luck) |
| v043 hot (buy NO) | 0.90 | 7,524 → 7,478 (−0.6%) | −13,755 → −13,283 (+3.4%) | −$229k (about $420 a day, ~0.8% of revenue) |

The bonus criterion technically passes, since SD drops in all three. In practice the gain is negligible: a 0.2–0.6% SD reduction. The rain P&L is weather luck, not edge. The hot hedge costs far more than it smooths.

## Verdict
- **FOUND (strictly by the criteria):** 3 single venues.
  - Two large bars, v030 and v241, lose 7–13% of visits on rain days, on both train and holdout.
  - One full-service restaurant, v043, gains 6–8% on days over 85 °F.
- **Basis:** the rain flag is the Central Park ≥ 0.01 in settlement rule itself. Hot is the Open-Meteo Central Park tmax against the strike; as in round 1, the reanalysis tmax is not the NWS CLI report.
- **NOT FOUND:** every category and ZIP aggregate. Drinking places as a class have the clearest real effect: −2.1% (train) and −3.2% (holdout) on rain days, with both CIs excluding 0. That is under the 5% bar and fails BH across 694 tests.
- **Recommendation for the desk:**
  - Target **drinking places (NAICS 722410)** for rain. As a class they reliably lose about 2–3% of visits on KXRAIN-yes days, and some individual bars lose 7–13%, replicated out of sample.
  - The desk can only find those bars by fitting each venue on its own history, then gating on a holdout refit.
  - Even for the venues that pass, a daily rain hedge cuts revenue SD by under 1%. Weekday, season and noise dominate. The honest pitch is "we found the bars where rain bites, and the hedge is small insurance, not income smoothing."
- **Demo idea:** show v030 or v241 next to the desk's gate. The train fit passes, the holdout refit confirms (−9% / −7%), and the hedge quote is shown with its tiny SD reduction. Contrast it with v167, which passed train and failed holdout and was declined.

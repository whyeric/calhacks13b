# Round 1: the "bar across from MSG" (see ../README.md for all rounds)

Branch `experiments/bar`, run 2026-10-24 on `main` at bfe9b00. Eight independent experiments, one folder each, each with a script and a `RESULTS.md`. Venue ids are opaque; no names, addresses or daily series are stored.

**Starting point:** the "Bar across from MSG" (`p_afa556030e60`, revenue = Dewey visits × $35, estimated) had no hedgeable exposure:
- home_win: −$2,026, CI [−4,351, 299]
- rain: −$345, CI [−992, 301]

Taxi had rain at +$2,212 and hot at +$3,967, both significant.

## Results

| Experiment | Question | Answer |
|---|---|---|
| [history](history/RESULTS.md) | Do 9 more months (from 2024-01, incl. 2024 playoffs) help? | No. With all 1,001 days, home_win shrinks to −$752 [−1,936, 431]; nothing significant. |
| [venues](venues/RESULTS.md) | Does any of 358 venues near MSG gain on wins? | No. 36 raw hits vs 35.8 expected by chance; 0 survive BH/Bonferroni; the top venue fails on holdout. |
| [timing](timing/RESULTS.md) | Does post-game traffic land on the next date? | No. The arena bump is on the game date; the bar's next-day terms are negative and so is a placebo. |
| [stakes](stakes/RESULTS.md) | Only playoffs, weekends, close or away games? | No. Every class is negative and crosses 0; the one hit (playoff_game) fails on holdout. |
| [rain](rain/RESULTS.md) | A better rain definition for the bar? | No. 12 definitions, all null for the bar. ≥ 1 mm fixes the 43.7% wet-day rate (→ 33.6%) and keeps basis R² 0.72. |
| [model](model/RESULTS.md) | Is a weak model hiding the effect? | No. 9 specs, the bar is null in all of them (residual CV ≈ 50%). **Taxi rain falls to +$128 with month dummies.** |
| [arena](arena/RESULTS.md) | Do wins move MSG foot traffic at all? | Games do (+2.4k Knicks, +5.5k Rangers visits); wins don't, for either team. |
| [hedgesim](hedgesim/RESULTS.md) | Does hedging make income steadier out of sample? | **No, not even for taxi.** The holdout refit gives taxi rain +$303 and taxi hot −$965. Events explain ~1% of daily variance. |

**Extra check (lead):** weekly instead of daily, on the taxi holdout. Hedged weekly SD is **+1.9% (rain) and +2.3% (hot)** above unhedged. Raw holdout means: rain days $1,057 *below* dry days, hot days $3,014 below other days, which is the opposite of the train betas.

## Conclusions

1. **The bar has no measurable game or weather exposure** in this data, across 8 independent approaches. That's a robust null, not a power problem.
2. **Taxi's train-year effects don't replicate in the holdout year.** Passing the gates (size, 90% CI, support) is necessary but not sufficient.
3. **Daily event hedges move little variance.** Even with perfect betas, the SD reduction is ≤ 0.5%, because day of week, season and noise dominate.

## Recommendations (for #36 / M3)

- **New decline rule, "unstable":** refit on the most recent holdout window and decline if the sign flips or the CI no longer excludes 0. This would have declined every hedge here.
- **Error bars:** switch SEs to Newey-West (`cov_type="HAC"`, `maxlags=7`); estimates are unchanged.
- **Rain flag:** move the business-side flag to ≥ 1 mm (33.6% of days, basis R² 0.72). Don't hedge on evening or heavy-rain flags, which the contract can't pay on.
- **Settlement:** fix `settle_hot` to `tmax > strike`.
- **Pitch:** lead with honesty. "We measured, and the desk declined" is the demo's strongest true story. The Jeffrey (June 2026) shows real demand for SMB event hedging. Our data shows most event risk is too small or too unstable to hedge, and the desk says so instead of selling a hedge.

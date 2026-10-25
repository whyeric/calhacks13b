# R4-natural: natural hedges between NYC transport businesses

**Question.** Are there pairs of NYC businesses whose revenue moves in opposite directions on the same Kalshi-settleable weather event? If so, a business that owns both, or a portfolio holding both, would be hedged without Kalshi. The candidate is rain: transit and bike demand fall while Uber/Lyft demand rises.

**Data.** All public, cached in scratchpad `r2-cache/`.
- **MTA:** daily Subway and Bus ridership, data.ny.gov `sayj-mze2`. Revenue is approximated as riders × $2.90.
- **TLC:** citywide daily trips and $ for yellow taxis (total_amount) and HVFHV Uber/Lyft (base fare + tips), from r2-taxi's `fetch_tlc.py`. Coverage is all 1,461 days of 2022–2025.
- **Citi Bike Jersey City:** daily trips, 2023–2025 only. The train period for this series is therefore 2023 alone. Revenue is approximated as trips × $4.
- **Weather:** Central Park NOAA GHCN-D `USW00094728`. This is the settlement station for KXRAIN and KXHIGHNY, so every flag is the settlement flag (basis R² = 1).
- **Events:** rain ≥ 0.01 in (KXRAIN), rain ≥ 5 mm, snow ≥ 0.1 in, cold (tmax < 32°F) and hot (tmax > 90°F, the KXHIGHNY strict-greater rule).

**Method.**
- **Effects:** one fit per series and event, log(y) on const + DOW + **year-month FE** + holiday + a Dec 24–Jan 1 week dummy + the event flag. Errors are HAC with 7 lags, z = 1.645.
- **Train and holdout:** train is 2022–23 and holdout is 2024–25, fitted independently.
- **Multiple comparisons:** BH at 10% over all **35 tests** (7 series × 5 events), applied separately to train and holdout p-values.
- **FOUND rule:** the shared brief's criteria, unchanged.
- **Pairs:** a pair is two FOUND effects of opposite sign on the same event.
- **Out-of-sample portfolio and hedge:** holdout $ residuals come from a calendar-only model, so the weather effect is still in them. All hedges are sized on train.

Run from backend/ with `.venv/bin/python ../experiments/bar/r4-natural/natural.py`. The output files are `effects.csv`, `pairs.csv`, `portfolio.csv` and `hedge.csv`.

## 1. Per-event effects (% of daily level, 90% CI)

| series | event | train n_ev | train % [CI] | q | holdout n_ev | holdout % [CI] | q | verdict |
|---|---|---|---|---|---|---|---|---|
| Subway | rain ≥ 0.01 in | 245 | −3.1 [−4.2, −2.0] | <.001 | 246 | −2.2 [−3.5, −0.9] | .012 | **FOUND** |
| Subway | rain ≥ 5 mm | 143 | −4.8 [−6.2, −3.4] | <.001 | 108 | −4.1 [−5.9, −2.4] | <.001 | **FOUND** |
| Bus | rain ≥ 0.01 in | 245 | −4.3 [−5.7, −3.0] | <.001 | 246 | −3.4 [−4.9, −2.0] | <.001 | **FOUND** |
| Bus | rain ≥ 5 mm | 143 | −6.8 [−8.6, −5.1] | <.001 | 108 | −5.8 [−7.8, −3.8] | <.001 | **FOUND** |
| Bus | snow ≥ 0.1 in | 12 | −12.1 [−21.2, −3.0] | .071 | 22 | −10.0 [−16.3, −3.6] | .023 | **FOUND** |
| Bus | cold < 32°F | 17 | −12.0 [−20.4, −3.6] | .049 | 20 | −6.7 [−10.8, −2.5] | .020 | **FOUND** |
| **HVFHV trips** | rain ≥ 0.01 in | 245 | **+1.9 [+0.9, +2.8]** | .003 | 246 | **+2.6 [+1.6, +3.5]** | <.001 | **FOUND** |
| **HVFHV trips** | rain ≥ 5 mm | 143 | +2.8 [+1.5, +4.0] | .001 | 108 | +3.9 [+2.5, +5.3] | <.001 | **FOUND** |
| HVFHV trips | hot > 90°F | 23 | +3.5 [+2.1, +5.0] | <.001 | 25 | +4.4 [+2.0, +6.8] | .008 | **FOUND** |
| **HVFHV $** | rain ≥ 0.01 in | 245 | **+1.7 [+0.6, +2.8]** | .039 | 246 | **+2.4 [+1.1, +3.7]** | .008 | **FOUND** |
| HVFHV $ | rain ≥ 5 mm | 143 | +2.4 [+1.0, +3.8] | .018 | 108 | +3.1 [+1.4, +4.9] | .008 | **FOUND** |
| Citi Bike JC | rain ≥ 0.01 in | 123 | −24.3 [−30.5, −18.1] | <.001 | 246 | −21.1 [−25.1, −17.1] | <.001 | **FOUND** |
| Citi Bike JC | rain ≥ 5 mm | 73 | −36.6 [−44.9, −28.4] | <.001 | 108 | −35.6 [−42.1, −29.1] | <.001 | **FOUND** |
| Subway | snow, cold, hot | 12–23 | −1 to −7 | .11–.13 | 20–25 | −2 to −6 | .03–.06 | NOT FOUND (train q > .1) |
| Yellow trips / $ | rain ≥ 0.01 in | 245 | −1.0 / −1.5 (CI spans 0) | .52 / .30 | 246 | +1.9 / +1.3 | .06 / .23 | NOT FOUND (**sign flips**) |
| Yellow trips / $ | rain ≥ 5 mm | 143 | −3.5 / −4.1 | .14 / .11 | 108 | +2.8 / +1.6 | .05 / .24 | NOT FOUND (**sign flips**) |
| Yellow | snow, cold, hot | | | ≥ .15 | | | ≥ .06 | NOT FOUND |
| HVFHV | snow, cold; $ on hot | | | ≥ .10 | | | ≥ .08 | NOT FOUND |
| Citi Bike JC | snow, cold | 4 / 1 | | | 22 / 20 | | | NOT FOUND (< 10 train event days) |

**13 of 35 tests are FOUND.** Yellow cabs are not a rain hedge. Their sign flips between periods, the same failure round 1 hit on its single taxi zone. The likely cause is that yellow supply is capped: on rainy days fares are hard to find, but the count of trips taken does not rise.

## 2. Opposite-sign pairs (both legs FOUND, same event)

**12 pairs, all on rain:** {Subway, Bus, Citi Bike JC} × {HVFHV trips, HVFHV $} × {rain ≥ 0.01 in, rain ≥ 5 mm}. The headline pair is **Subway (−3.1% train / −2.2% holdout) vs HVFHV $ (+1.7% / +2.4%) on KXRAIN days**. Both legs replicate with the opposite sign. In dollars on train levels, a rain day costs the subway about −$264k of fare revenue and adds about +$259k to Uber/Lyft gross. These are close to equal.

Hot > 90°F gives no pair: HVFHV trips rise, but subway's −1.2% fails train BH (q = .13).

## 3. Portfolio, out of sample (2024–25 holdout)

CV is the residual SD divided by mean $/day. The weather part is the train joint-weather betas applied to holdout flags.

| A | B | corr of residuals | corr of weather part | CV A | CV B | CV A+B | weather share of A's var | weather var cut (A+B vs A) | total var change (A+B vs A) |
|---|---|---|---|---|---|---|---|---|---|
| Subway | HVFHV | **+0.42** | **−0.92** | 6.0% | 7.9% | 6.3% | 15% | **−96%** | **+11%** (worse) |
| Bus | HVFHV | +0.20 | −0.87 | 6.7% | 7.9% | 7.0% | 29% | −94% | +8% (worse) |
| Yellow | HVFHV | +0.83 | −0.41 | 10.0% | 7.9% | 8.0% | 5% | −70% | −35% (diversification, not weather) |
| Subway | Bus | +0.87 | +0.98 | 6.0% | 6.7% | 6.0% | 15% | +31% | 0% |

The weather-driven parts of subway and Uber/Lyft revenue are almost perfectly anti-correlated (−0.92 out of sample), so a revenue-weighted subway + HVFHV portfolio removes 96% of the weather variance. **The portfolio as a whole is still not steadier.** Weather is only about 15% of subway's day-to-day residual variance. The other 85% comes from non-weather citywide shocks (events, outages, school calendars, tourism) that move both series up together, which makes the total residual correlation +0.42. Adding a $18M/day business to a $10M/day one with positively correlated noise raises the CV.

## 4. Natural hedge vs Kalshi rain contract (holdout, $/day, rain ≥ 0.01 in)

Each hedge is sized on train. The natural hedge owns h = −β_A/β_B units of business B. The Kalshi hedge buys |β_A| contracts on the side that pays when A is hurt, at train frequency + $0.02 + fee.

| A | hedge | SD | 5th-pct day | mean on rain days | mean cost/day |
|---|---|---|---|---|---|
| Subway ($9.8M/day) | none | 590k | −971k | −112k | 0 |
| | natural: +1.02 × HVFHV | 1,813k | −3,224k | +160k | 0 (but needs ~$18.7M/day of extra business) |
| | **Kalshi YES rain, 264k contracts @ 0.37** | **586k (−0.6%)** | **−936k (+3.7%)** | +54k | −9.3k (0.09% of revenue) |
| Bus ($3.4M/day) | none | 226k | −366k | −63k | 0 |
| | natural: +0.56 × HVFHV | 881k | −1,565k | +85k | 0 |
| | Kalshi YES rain | 222k (−1.5%) | −373k (−1.9%) | +27k | −5.0k |
| HVFHV ($18.4M/day) | none | 1,456k | −2,279k | +266k | 0 |
| | natural: +0.98 × Subway | 1,777k | −3,160k | +156k | 0 |
| | Kalshi NO rain @ 0.70 | 1,445k (−0.7%) | −2,252k (+1.2%) | +85k | −9.3k |

On rain days the natural hedge does what it should: subway's −$112k average rain-day hit becomes +$160k. It overshoots because HVFHV's rain effect was larger in the holdout. Taken whole, though, it multiplies daily SD by about 3, because the hedge leg brings its own large noise, which is positively correlated with A's. The Kalshi contract carries no basis noise. It gives a small reduction in SD for subway and HVFHV and improves the 5th-percentile day by 1–4%, at a cost of about 0.1% of revenue. For bus the 5th-percentile day gets slightly worse.

## Verdict

- **Opposite-sign effect, subway/bus/Citi Bike vs Uber/Lyft on rain: FOUND.** All 12 pairs pass every criterion (train and holdout CIs, BH over 35 tests), and the basis is the KXRAIN settlement flag itself. Uber/Lyft gains about +2% on rain days while transit loses 2–4% and bike loses about 21–36%.
- **Natural hedge as a variance reducer: NOT FOUND.** The weather components cancel (corr −0.92, 96% of weather variance removed), but weather is too small a share of each business's variance. Non-weather co-movement (+0.42) dominates, so owning both makes daily income less steady (+11% variance for subway + HVFHV, and about 3× SD at the rain-matched hedge ratio).
- **Kalshi vs natural:** Kalshi's rain contract wins on SD and the 5th-percentile day for subway and HVFHV, because it is pure event exposure with no basis noise. The gain is small (−0.6% SD, +3.7% p5 for subway), consistent with round 1's finding that events explain little of daily variance.

**Demo idea:** take one rain day and show the subway losing about $264k while Uber/Lyft gains about $259k. That is a clean natural hedge on the event. Then show the full-year chart, where the two series mostly rise and fall together, which is why the pure rain contract is the better tool.

**Caveats.**
- MTA "revenue" is riders × flat fare, and Citi Bike "revenue" is trips × $4. Both are proxies.
- HVFHV $ is passenger gross, not the platform take.
- Citi Bike train is 2023 only, and it sits outside the portfolio panel.
- Holdout residuals use a holdout-fitted calendar model (year-month FE cannot be extrapolated), so the "alone" SD is in-sample with respect to the calendar terms. All weather betas and hedge sizes come from train only.
- 35 tests in total. Nothing was tuned on the holdout.

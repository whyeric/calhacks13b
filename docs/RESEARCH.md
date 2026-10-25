# Research appendix: which event risks are real?

Before we let the desk sell anyone a hedge, we tried to break the premise. Across eight rounds and
about 40 experiments, we asked one question: **does a settleable event move a small business's
revenue, and does that hold up on data the model never saw?** Most of the "obvious" risks didn't.

Every experiment lives in its own folder on the **`experiments/bar` branch**. Each one has a
script and a `RESULTS.md` with the full tables. To read one, run
`git show experiments/bar:experiments/bar/<folder>/RESULTS.md`. Round 1 also has a summary in
`experiments/bar/SUMMARY.md`; this page covers every round.

> **Honesty notes.** Effects are 90% CIs unless a row says otherwise. Any dollar figure for the
> bar rests on assumed inputs: Dewey foot traffic times a $35 average check, sometimes with a
> 300-covers-a-night scenario bar. The foot traffic is real; the dollars are estimated. Two folders
> exist only in the working tree and are **not committed** to `experiments/bar`:
> `r3-bikemonthly/` (a script, never run, no results) and `r7-boxoffice/` (a design with no
> results). Neither one supports any claim on this page.

---

## 1. Method

**The bar a hedge has to clear.** An effect counts as **FOUND** only if all of these hold:

1. **Train fit.** The 90% CI excludes 0, with at least 10 event days.
2. **Multiple testing.** It survives Benjamini–Hochberg at q ≤ 0.10, taken over the experiment's
   whole pre-declared family. Families ran from 12 tests to 1,454. We also wrote down how many
   hits chance alone would give. For example, `venues/` had 36 raw hits on game wins against 35.8
   expected by chance, and 0 survived BH.
3. **Holdout replication.** A second, independent fit on later data, never tuned, must give the
   same sign with a CI that still excludes 0. The split depends on the series: 365/335 days in
   round 1, 2022–23 vs 2024–25 for MTA and TLC, and pre- vs post-COVID shutdown years for DC.
4. **Settleable basis.** The event flag must be one a live Kalshi contract settles on.
5. A hedge backtest (does hedged income actually get steadier?) counts as a bonus, not a gate.

**Placebos.** We used these whenever the design allowed:
- permutations within year-month (`r2-aggregate/`, `r5-bars/`, `r6-broadway/`, `r6-wrigley/`, `r7-tsa/`);
- lead and day-before placebos (`timing/`, `r6-gas/`, `r6-crosscity/`);
- wrong-city and far-zone placebos (`r6-austin/`, `r6-tvpower/`);
- residential-basket placebos (`r7-fidi/`, `r8-dcshutdown/`);
- "last year's same week" as a seasonality stand-in (`r7-tsa/`).

From round 6 on, each experiment wrote down its mechanism and predictions before fitting.

**NOAA settlement.** Round 1 used Open-Meteo reanalysis weather. Kalshi's NYC rain and temperature
contracts settle on the NWS report for Central Park, so from round 2 on we used NOAA GHCN station
USW00094728. That makes the feature flag *the* settlement flag (basis R² = 1).
`r3-noaa/` measured the gap:
- Open-Meteo and NOAA agree on only 85–90% of days.
- Open-Meteo calls 40–47% of days wet; NOAA calls 31–38%.
- On holdout, the extra "wet" days Open-Meteo adds behave like dry days.
- Pricing the contract off Open-Meteo would misprice p̂ by about 9 points.

Other settlement stations reproduced their settled markets exactly: Austin, Houston, Dallas and San
Antonio for `KXHIGH*` (`r4-ercot/`, 100% of 390 markets per city), and public TSA data for
`KXTSAW` (`r7-tsa/`, 189 of 189).

**The HAC caveat.** `model/` recommended Newey–West (HAC, 7 lags) because taxi residuals are
autocorrelated (AC1 0.49). There, HAC CIs came out within about 10% of HC3. Later rounds found
that HAC is often **too narrow**, so read borderline HAC results with suspicion:
- `r2-aggregate/`: the placebo p95 |t| was 2.56, which "suggests HAC understates the SE somewhat".
- `r7-deferral/`: 10 of 32 daily placebos were hits, so the CIs are about 1.5× too narrow.
- `r8-dcshutdown/`: about half of 51 fake-date placebos came out "significant", so that study
  switched to randomization inference.
- `r7-displacement/`: HAC on flags with fewer than 10 days collapses to about 0, so classical SEs
  were used instead.
- `r2-horizon/`: with 12 monthly observations HAC understates the error, so HC3 with t(df) was used.

**Seasonality is the other trap.** `r3-noaa/` traced a disagreement between `r2-pooling/` and
`r2-aggregate/` to the seasonality terms alone. With Fourier harmonics, 0 of 12 rain tests were
FOUND; with year-month fixed effects, 11 of 12 were. A linear trend extrapolates terribly
(holdout R² −0.81 for the bar, −1.68 for taxi, in `model/`). Use year-month (or month) fixed
effects before trusting any weather beta.

---

## 2. FOUND: effects that replicate

Train → holdout, each an independent fit.

| Event → series | Effect, train → holdout | Settles on | Hedge result | Folder |
|---|---|---|---|---|
| **NYC playoff home game → foot traffic within 0.5 km of MSG** (277-store Dewey basket) | **+5.7% [+4.0, +7.4] → +5.7% [+3.4, +8.1]**, q < .001. That is +3.4 points above a regular home night in both periods, and positive in all 4 team-seasons. | Kalshi playoff advancement: series winner, conference and length contracts | Small money. At the assumed $35 check and 300 covers, u ≈ **$604 per playoff home game [$438, $772]**, and a deep run is worth about $7k (≈2% of a month). Monte Carlo says SD falls 42–72% for $53–95 in fees a season. **The realised 5-run backtest did not help:** SD went from $1,011 to $1,037, with hedge P&L −$4,903 because NY won 10 of 14 rounds. | `experiments/bar/r5-nycplayoffs/` |
| Playoff advancement contracts → home-game count | Basis is exact. Pricing: Brier 0.207 over 79 quotes, 1¢ spreads. | 50 series, ~4,000 markets | Rolling series-winner hedge over 84 team-seasons: SD **2.37 → 0.86 home games** (87% of variance removed), at a cost of 0.10 home games a season. NHL length books are thin. | `experiments/bar/r5-markets/` |
| Playoff home night → MSG-area taxi/FHV driver gross, 21–01h | **+39.8% → +36.0%** (+25% above a regular home night) | same | 7-season backtest SD −67% ($1,540 → $512). About $666 per game for a 10-car fleet. | `experiments/bar/r5-mobility/` |
| Warriors playoff home → Chase Center area (SF) | +0.351 → +0.622 log points, n 11/11; the Oakland-era placebo is null | same | Real 5-season backtest SD only −3%, and the 2022 hedge backfired. Simulated −24% to −40%. | `experiments/bar/r5-sfplayoffs/` |
| Cubs playoff home → Divvy trips ≤450 m of Wrigley | **+126% → +107%**; every placebo passes | `KXMLBPLAYOFFHOST` | Simulated SD −76% | `experiments/bar/r6-wrigley/` |
| **Federal shutdown → DC federal-cluster Capital Bikeshare** | DiD fed − residential: −37.6 (2013) / **−14.6 [−22.5, −5.3]**, p = .022 (2018–19 train) / **−25.1 [−34.1, −15.8]**, p = .012 (2025 holdout); BH q .039 / .026. Inference by randomization, since HAC was far too narrow. | Kalshi shutdown occurrence and duration | For a $4,000/weekday lunch spot, a duration strip bought Sep 10 turned a −$20.2k shutdown into **−$2.9k**. A rolling binary program *lost* money. The DHS-only lapse of 2026 settled YES with about 0 downtown effect, so basis risk is real. | `experiments/bar/r8-dcshutdown/` |
| **Texas heat (>95 °F at the settlement station) → fixed-rate power bill** | DFW: **+$32.2 [+29.1, +35.3] → +$31.5 [+27.4, +35.6]** on a $190/day bill. Austin +$27.4 → +$25.9; Houston +$20.1 → +$19.1. Significant in 8 of 8 years; 64 of 64 tests FOUND. | `KXHIGHTDAL` / `KXHIGHAUS` / `KXHIGHTHOU` | 32 YES contracts: within-month SD −5.6%, p95 −11%, $0.82/day. The hot dummy explains about 15% of bill variance, which points to a strike ladder. The wholesale-price premium has collapsed since 2023. | `experiments/bar/r4-ercot/` |
| **Rain → bike share** (Citi Bike Jersey City/Hoboken; NYC DOT counters) | JC **−550 → −476 trips/day (≈ −20%)**; DOT −6,906 → −7,237 (≈ −21%) | `KXRAIN` | Residual SD −9% to −12% (DOT −13%). At an assumed $4/trip, the JC system loses about −$2,202/day (train) and −$1,906/day (holdout). | `experiments/bar/r2-citibike/`, `experiments/bar/r4-natural/` |
| **Rain → transit ridership** | Subway **−3.0% → −2.3%**; bus −4.2% → −4.2%; LIRR −4.4% → −2.7%; Metro-North −5.0% → −3.0%. Evening entries at 34 St–Penn: −5.3% → −3.5%. | `KXRAIN` | SD −0.4% to −3.7% | `experiments/bar/r2-mta/`, `experiments/bar/r4-mtahourly/` |
| **Rain → foot traffic** (aggregates, year-month fixed effects) | MSG ZIP cluster **−2.03% → −2.26%** (q .009 / .001); ≤0.5 km of MSG −2.62% → −2.95%; dining −1.91% → −1.86% same day, and −2.68% → −2.54% over 3 days (no rebound) | `KXRAIN` | SD −1.6% to −2.4%. Real but small. The single demo bar is null. A same-day hedge under-hedges, so size it at 1.0–1.4× beta. | `experiments/bar/r2-aggregate/`, `experiments/bar/r3-noaa/`, `experiments/bar/r7-deferral/` |
| **Rain → for-hire vehicles (Uber/Lyft), citywide** | trips **+2.2% → +2.4%** (+16,036 [9,613, 22,458]/day holdout, q .009); HVFHV $ +1.7% → **+2.4% [+1.1, +3.7]** | `KXRAIN` | SD −0.5% to −0.8%. As a natural hedge against the subway, it makes total variance **+11% (worse)**. | `experiments/bar/r2-taxi/`, `experiments/bar/r4-natural/` |
| Snow → Broadway grosses | −2.2% → −2.5% per ≥1 in snow day, q .076 | `KXNYCSNOWM` (monthly) | The monthly contract doesn't help: SD $6.56M → $6.58M | `experiments/bar/r6-broadway/` |

Scheduled effects are large but **not hedgeable**, because the date is known in advance. Two
examples: MSG game nights at Penn station run +28.8% → +31.9% (`r4-mtahourly/`), and SF meter
revenue on home games runs about +0.65 log points (`r4-sfparking/`). These belong in the forecast,
not in a hedge.

---

## 3. NOT FOUND: risks that didn't hold up

| Hypothesis | What happened | Folder |
|---|---|---|
| **Knicks/Rangers win vs loss → bar near MSG** | Bar home_win −$2,026 [−4,351, 299] on train, then **+$588** on the holdout refit. With 1,001 days of history: −$752 [−1,936, 431]. Every one of 9 model specs crosses 0. | `experiments/bar/model/`, `experiments/bar/history/`, `experiments/bar/hedgesim/` |
| Wins → MSG arena traffic, 358 nearby venues, the pooled panel | Games show up in foot traffic; wins don't. 0 of 358 venues survive BH (36 hits vs 35.8 expected), and the train–holdout correlation across venues is −0.07. | `experiments/bar/arena/`, `experiments/bar/venues/`, `experiments/bar/r2-pooling/` |
| Only playoff, weekend or close games; next-day timing | The playoff_game hit (−$2,202) went to **−$36** on holdout. win_day_after is significant, but so is the day-*before* placebo. | `experiments/bar/stakes/`, `experiments/bar/timing/` |
| Wins → Penn station-hour entries | MSG win +0.9% → +1.0%; 0 of 9 win tests FOUND. "A win changes who is happy, not how many people leave." | `experiments/bar/r4-mtahourly/` |
| **Taxi (zone 186) weather, the exposure the live desk uses** | Rain: +$2,212 → **+$303** on holdout, +$128 with month dummies, +$2,489 → +$774 on NOAA. Hot: +$3,967 → **−$965** (sign flip); on NOAA +$5,490 → −$157. Citywide yellow-cab rain also flips (−1.0% → +1.6%). A perfect hedge would cut SD by ≤0.5%; the actual hedge made holdout income *less* steady (+0.76% rain, +1.26% hot). | `experiments/bar/hedgesim/`, `experiments/bar/model/`, `experiments/bar/r3-noaa/`, `experiments/bar/r2-taxi/` |
| A better rain definition for the bar (12 definitions) | All 12 null (smallest p 0.38); evening and heavy-rain flags fail the basis rule | `experiments/bar/rain/` |
| Weekly/monthly weather totals | Taxi weekly rainy days flips +8,516 → −10,520. A `KXRAINNYCM` hedge made the worst month worse (−$227k → −$331k). | `experiments/bar/r2-horizon/` |
| 31 new predictors | 0 of 92 FOUND; taxi snow day missed at q = 0.1002 | `experiments/bar/r2-predictors/` |
| **Cross-city weather** (storms at hubs → Penn/MSG) | 3 rows pass on paper but fail falsification. The rest of NYC falls by the same amount, and placebo cities hit just as often. | `experiments/bar/r6-crosscity/` |
| **Gas prices → bike share / rideshare** | 0 of 32; a 4-weeks-ahead lead placebo "predicts" as well as current gas. (Fuel cost itself is hedgeable directly with `KXAAAGASM`.) | `experiments/bar/r6-gas/` |
| **Game outcomes → TV-hour power load** (PJM) | 0 of 20; the largest estimate is ~0.04% of daily energy cost | `experiments/bar/r6-tvpower/` |
| **Market moves → Financial District bars** | 0 of 39 pass BH; train hits appear in the residential placebo too, then flip | `experiments/bar/r7-fidi/` |
| **TSA throughput → Midtown tourism** | Passes formally, but last year's same week predicts as well, and the YoY surprise is null. As a hedge, SD −0.3% and p5 worse. | `experiments/bar/r7-tsa/` |
| **Austin** heat / UT football / ACL → B-cycle | 0 of 18; heat has the wrong sign, and the wrong-city placebo isn't clean | `experiments/bar/r6-austin/` |
| **Broadway on playoff nights** | −0.47% → −0.39%, CI spans 0; Times Square +0.02% → −0.04% | `experiments/bar/r6-broadway/` |
| Big-TV nights → bars | −1.3% → −0.2%; the one formal pass has a −4.5% placebo | `experiments/bar/r7-displacement/` |
| Iowa liquor vs college football and rain | 0 of 18; rain flips sign | `experiments/bar/r4-iowa/` |
| SF weather → parking | Rain doesn't replicate, and there's no daily SF rain contract | `experiments/bar/r4-sfparking/` |
| Natural hedge (subway + rideshare) | The weather parts are −0.92 correlated, but the totals are +0.42; combined variance +11% | `experiments/bar/r4-natural/` |
| Box office → nearby foot traffic | **No result.** The design exists, but the run never wrote outputs, and the folder isn't committed. | `experiments/bar/r7-boxoffice/` (working tree only) |
| Monthly rain → monthly bike demand | **No result.** It's a script only, not committed. | `experiments/bar/r3-bikemonthly/` (working tree only) |

---

## 4. Lessons for the product

1. **Declining is the product.** The decline rules caught the noise, and the desk says so instead
   of selling something. "We measured, and the desk declined" is the strongest true thing we can
   demo.
2. **Add an "unstable" rule.** Refit on the most recent holdout window, and decline if the sign
   flips or the CI no longer excludes 0. Run on round 1, it would have declined every hedge
   (`SUMMARY.md`). It would also flag the taxi rain exposure the live desk currently measures
   (+$2,080 on train today; the round-1 holdout refit gave +$303 [−1,823, 2,430]).
3. **Use the settlement station for features too** (NOAA Central Park, not reanalysis), and use
   year-month fixed effects before trusting any weather beta. Treat HAC CIs as optimistic; prefer
   placebo or randomization checks for short or block-shaped events.
4. **Hedge dates and elimination, not results.** Game *results* don't move nearby demand; game
   *dates* do, and playoff home dates do even more. The organic exposure for a bar near MSG is the
   *count of playoff home games*, which advancement and series contracts settle on exactly
   (`r5-markets/`). The Jeffrey's June 2026 Finals hedge is the other kind: a self-created
   exposure ("free tab if the Knicks win"), which a game-winner contract does hedge exactly.
5. **Scheduled effects go in the forecast, not the hedge.** A regular home game is known weeks
   ahead.
6. **One business rarely notices a daily weather hedge.** A perfect daily hedge cuts a single
   business's SD by about 0.5% at most. Rain is a portfolio- or neighborhood-level product. The
   places where a hedge clearly helps are concentrated, settleable shocks: a shutdown duration
   strip, heat for a fixed-rate power bill, playoff home-game count.
7. **Size against the full episode.** Rain losses don't bounce back the next day, so size at
   1.0–1.4× the same-day beta, with no "deferral" haircut (`r7-deferral/`).
8. **Backtests priced at historical frequency are an upper bound.** By the morning of the event,
   Kalshi prices the day's forecast (for example, a >95 °F contract near $0.90 on a hot morning).

---

## 5. The protocol on a bike shop's revenue (the "Research my risks" demo)

The app's **Research my risks** flow is a **scripted demo**. It shows what this protocol finds when
it runs on one business's revenue. We ran the protocol offline on `hudson_bike_co_daily_revenue.csv`
and hardcoded the results into the frontend. That file is a fictional NYC bike-rental shop with
synthetic revenue, keyed to the real NOAA Central Park weather days. The guide is
[UPLOAD_AND_RESEARCH.md](UPLOAD_AND_RESEARCH.md).

**The rules, and the lesson behind each:**

| Rule | Lesson it encodes |
|---|---|
| Year-month fixed effects + DOW + holiday, never Fourier or trend | §1 "Seasonality is the other trap": with Fourier, 0 of 12 rain tests were FOUND; with year-month FE, 11 of 12 |
| Weather flags from NOAA Central Park (USW00094728) | §1 NOAA settlement: reanalysis disagrees with the settlement station on 10–15% of days |
| Train 2024, holdout 2025–26, fitted independently, no tuning | §1 rule 3 |
| HC3 errors, not HAC | §1 HAC caveat (too narrow in `r2-aggregate/`, `r7-deferral/` and `r8-dcshutdown/`) |
| BH at 10% across every hypothesis in the run | §1 rule 2 (`venues/`: 36 raw hits vs 35.8 by chance, 0 after BH) |
| Placebo: the same flag shifted +7 days must be insignificant | §1 placebos (`timing/`'s day-before placebo was as significant as the effect) |
| Control `home_game` when testing a game result | §3: games move traffic, results don't |
| ≥ 10 event days in train | §1 rule 1 |

**Results on the sample.** The file has three planted effects, about −20% on rain days, −28% below
40 °F and +10% above 80 °F, and no game effect.

| Hypothesis | 2024 (train) | 2025–26 (holdout) | Verdict |
|---|---|---|---|
| Rain | −18.4% (−$1,955.68/day, 90% CI −$2,171.00 to −$1,734.86, 124 days) | −20.4% (−$2,485.41/day) | FOUND; placebo p 0.38; `KXRAINNYC` |
| Cold < 40 °F | −27.0% | −26.4% | FOUND |
| Warm > 80 °F | +10.9% | +15.5% | FOUND (upside) |
| Hot > 90 °F, Knicks home game, Knicks win | not distinguishable from zero | | NOT FOUND |

The protocol recovered all three planted effects and rejected the three it should have. Because
the revenue is synthetic, this is a check that the method works, not a finding about bike shops.

**What the demo shows but doesn't run.** The mechanism pre-registration and protocol steps are a
staged animation, and the results above are hardcoded. The intended live version is described in
UPLOAD_AND_RESEARCH.md §4 and isn't implemented:
- Claude would choose the hypotheses and write each mechanism *before* the test runs;
- the harness would own the specification, the split, the thresholds and the BH family;
- every number would be validated under I2.

Compared with the hand research, the demo protocol also leaves out randomization inference and
spatial placebos, and it covers NYC only.

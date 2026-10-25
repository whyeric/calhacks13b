# R7 displacement: big-TV nights and going out in Manhattan

## Mechanism (written before fitting)
A big televised event that is not in Manhattan (Yankees/Mets postseason, Giants/Jets primetime, the Super Bowl, March Madness, election night, USA at the World Cup, the MetLife final) → more people watch at home → fewer evening trips into Manhattan (subway entries, FHV drop-offs in nightlife zones) → fewer visits to bars and full-service restaurants. Prediction: negative day effects that grow with the stakes. The week-before placebo should be zero.

## Short answer: NOT FOUND
The r5-bars finding (Manhattan bars −3.5% on Knicks/Rangers **away** playoff nights) does **not** generalize. Across 7 event families and 6 outcomes, **no** displacement effect passes train + holdout + BH. Pooled over every big-TV day, bars move −1.3% [−3.1, +0.4] in train and −0.2% [−2.2, +1.9] in holdout. Effects do not grow with stakes (round or audience) once a placebo is applied. A single term passes the formal FOUND rules: the March Madness stage slope for 87 upper-Manhattan bars. Its one-week-earlier placebo is just as negative, so it is a calendar artifact. Yankees/Mets postseason runs create **no measurable seasonal exposure** for Manhattan bars (+0.8% per night [−3.4, +5.0]), so there is nothing for a KXMLBSERIES hedge to hedge.

## Data
- **Dewey:** daily visits, 2024-01-01..2026-09-27, using the r2-aggregate balanced panel (stores present in all weeks, <5% flat weeks). Baskets, sums only: Manhattan drinking places 722410 (976 stores), full-service restaurants 722511 (7,819), bars ≤5 km from Yankee Stadium (87; upper Manhattan) and bars >5 km (889). Citi Field and MetLife are farther than 5 km from almost all of Manhattan, so for them every basket is "away".
- **MTA:** subway entries at Manhattan stations, 18:00–23:59, per day (SoQL aggregate; wujg-7c2s for 2024, 5wq4-mkjj for 2025–26).
- **TLC:** HVFHV (Uber/Lyft) trips with pickup 18:00–23:59 and drop-off in 9 Manhattan nightlife zones (East Village, LES, West/Greenwich Village, Union Sq, East Chelsea, Flatiron, Clinton East), per day, 2024-01..2025-12 (NYC Open Data SoQL; the CloudFront parquet returns 403 and 2026 isn't on Open Data yet).
- **Events (ESPN, `events.csv`):**

| family | train days (≤2025-09-28) | holdout days |
|---|---|---|
| Yankees postseason (2024 ALDS→WS; 2025 WC+ALDS) | 14 | 7 |
| Mets postseason (2024 WC→NLCS; missed 2025) | 13 | 0 |
| Giants/Jets primetime (kickoff ≥19:00 ET) | 9 | 6 |
| Super Bowl Sunday | 2 | 1 |
| NCAA men's tournament days | 24 | 12 |
| Election night (2024 presidential; 2025 NYC mayoral as the only holdout analog) | 1 | 1 |
| USA World Cup 2026 matches / MetLife final | 0 | 5 / 1 |

- **Controls:** GHCN Central Park rain flag, holidays, Halloween, and Knicks/Rangers playoff home/away nights (r5-bars `games.csv`).

## Method
log(y) ~ DOW + year-month FE + holiday + Halloween + rain + Knicks/Rangers playoff controls + one day flag per family. All families go in one model, so overlapping days split additively. Errors are HAC(7). **Any flag on fewer than 10 days gets the classical OLS SE**, because a HAC/HC sandwich around a near-saturated dummy collapses to ~0: one-day flags such as election night first came out at p ≈ 0.000, which was spurious. Train (2024-01-01..2025-09-28) and holdout (2025-09-29..2026-09-27) are fitted independently. The train split matches r5-bars, moved 2 days so the Yankees' 2025 Wild Card series isn't cut in half.
- **Stakes:** a within-family slope on the MLB round (WC=1…WS=4) and on the March Madness stage (R1/R2=1, S16/E8=2, F4/final=3), plus a pooled big-TV flag with a slope on audience tier. The tiers are approximate US audience bands, my assumption: 1 = <8M, 2 = 8–30M, 3 = >40M.
- **BH** runs at 10% over all **84** train tests: 6 outcomes × (6 family flags + 2 stakes slopes + 2 pooled + 4 MLB home/away flags). Placebo fits (155 rows) and robustness fits (35 rows) are not counted.
- **Placebo:** the same weekday one week before each event day, dropping dates that are themselves events or Knicks/Rangers playoff nights. For the stakes slopes, the stage codes are moved a week earlier.

## 1. Is there a drop on big-TV nights? (% change in daily visits/trips, 90% CI)

| outcome | term | train (n) | holdout (n) | BH q | verdict |
|---|---|---|---|---|---|
| bars, all Manhattan | **pooled big-TV day** | −1.3 [−3.1, +0.4] (54) | −0.2 [−2.2, +1.9] (33) | 0.73 | not found |
| full-service, all | pooled big-TV day | −1.2 [−2.7, +0.3] (54) | −0.7 [−2.4, +0.9] (33) | 0.73 | not found |
| MTA Manhattan 18–24h | pooled big-TV day | +0.2 [−2.8, +3.2] (54) | +1.1 [−3.4, +5.6] (33) | 0.95 | not found |
| FHV to nightlife 18–24h | pooled big-TV day | +0.6 [−2.5, +3.7] (54) | +2.0 [−7.0, +11.0] (12) | 0.95 | not found |
| bars, all | Yankees postseason | +0.8 [−3.4, +5.0] (14) | +1.7 [−3.1, +6.5] (7) | 0.95 | not found |
| bars, all | Mets postseason | +0.6 [−4.0, +5.2] (13) | — (missed 2025) | 0.95 | not found |
| bars, all | Giants/Jets primetime | −1.0 [−5.0, +3.0] (9) | +0.4 [−4.4, +5.3] (6) | 0.95 | not found (n<10) |
| bars, all | March Madness day | −0.8 [−3.1, +1.5] (24) | **+4.8** [+0.7, +8.8] (12) | 0.95 | not found (holdout sign flips) |
| bars, all | Super Bowl | −3.8 [−11.3, +3.7] (2) | −14.6 [−25.7, −3.4] (1) | 0.79 | not found (n=3; placebo also −13%) |
| bars, all | election night | −7.8 [−18.4, +2.7] (1) | −4.9 [−16.0, +6.2] (1, mayoral) | 0.69 | not found (n=1 each) |
| full-service, all | election night | −10.4 [−17.2, −3.5] (1) | −5.7 [−14.3, +2.9] (1) | 0.15 | not found |
| bars, all | USA World Cup match | — | −0.7 [−5.9, +4.4] (5) | — | holdout only |
| bars, all | World Cup final (MetLife) | — | +4.9 [−6.2, +16.0] (1) | — | holdout only |
| MTA 18–24h | Yankees postseason | **+6.3** [+3.6, +9.0] (14) | **−7.9** [−17.8, +2.0] (7) | 0.003 | not found (sign flips) |
| MTA 18–24h | Giants/Jets primetime | +7.5 [+2.6, +12.3] (9) | +3.6 [−6.4, +13.7] (6) | 0.18 | not found |
| MTA 18–24h | World Cup final | — | +29.5 [+6.5, +52.6] (1) | — | holdout only; fans travelling to MetLife via Penn |
| FHV 18–24h | Yankees postseason | +4.8 [+1.3, +8.2] (14) | −9.4 [−27.1, +8.3] (7) | 0.22 | not found |

Every row is in `verdict.csv` and `results.csv`; the bars ≤5 km / >5 km from Yankee Stadium baskets track all-Manhattan bars closely. **Home vs away MLB games** (n = 5–8 each, so none can pass): bars Yankees home −2.5 / away +3.4 (train), Mets home +0.7 / away −0.5. Nothing like the Knicks-away −3.5% appears. The +6% MTA evening bump on 2024 Yankees nights shows up for both home and away games, then reverses in 2025. That's noise, or 2024-specific (the WS run fell in late October, which is a busy month anyway).

**Placebo** (`placebo.csv`): pooled week-before days give bars −1.1% [−3.6, +1.3] in train and −1.6% [−3.5, +0.3] in holdout, which is about as large as the real pooled effect. The week-before-Super-Bowl Sunday is **more** negative than Super Bowl Sunday itself in train (−13.2% vs −3.8%). Caveat: that Sunday is always Grammys night, so this placebo is itself a TV night. Either way, the Super Bowl "drop" can't be told apart from early-February Sunday noise with n = 3.

## Does it scale with the stakes?
No.

| outcome | slope | train | BH q | holdout | week-earlier placebo (train) |
|---|---|---|---|---|---|
| bars ≤5 km of Yankee Stadium | March Madness stage | −3.7 [−4.9, −2.5] | 0.0001 | −3.2 [−6.5, −0.0] | **−4.5 [−5.9, −3.2]** |
| bars, all | March Madness stage | −0.4 [−3.5, +2.7] | 0.95 | −5.8 [−8.0, −3.7] | −3.9 [−5.8, −2.1] |
| bars ≤5 km | MLB round | +2.9 [+1.3, +4.6] | 0.08 | +2.0 [−8.3, +12.4] | +4.9 [+2.2, +7.7] |
| MTA 18–24h | MLB round | +4.1 [+2.3, +5.9] | 0.003 | +4.3 [−14.0, +22.7] | −0.8 [−2.9, +1.4] |
| bars, all | pooled audience tier | +0.8 [−2.7, +4.3] | 0.95 | −5.4 [−9.2, −1.6] | — |

- **The only term that formally passes FOUND (1 of 84)** is the March Madness stage slope for the 87 upper-Manhattan bars. It does not survive the falsification test: moving the stage codes one week earlier, to days with no tournament games, gives the same negative slope (−4.5%). It is the late-March → early-April calendar (spring breaks, Easter; adding an Easter dummy barely changes it, −3.3% in holdout) interacting with year-month FE, not TV. **Verdict: artifact.**
- The MLB round slope on MTA evening entries (+4%/round, train q = 0.003) doesn't replicate. In holdout, 2025 had only WC and DS games and n = 7, so the CI is ±18 pp. Later rounds also have later start times; controlling for an evening start and home game leaves it unchanged in train.
- The audience-tier slope is ≈0 in train and negative only in holdout, where the tier-3 days are just the 2026 Super Bowl and the World Cup final.

## 2. Seasonal exposure from a Yankees/Mets run (Kalshi KXMLBSERIES)
Per-night effects are from train. R = Apr–Jun non-event visits per store × $35 (assumed check, as in earlier rounds).

| basket | family | % per night [90% CI] | $ per night [90% CI] | 2024 run (nights) | 2024 run $ |
|---|---|---|---|---|---|
| bar, citywide (R ≈ $13.7k/day) | Yankees | +0.8 [−3.4, +5.0] | +$107 [−470, +684] | 14 | +$1.5k |
| bar, citywide | Mets | +0.6 [−4.0, +5.2] | +$82 [−550, +714] | 13 | +$1.1k |
| full-service (R ≈ $6.1k/day) | Yankees | −0.7 [−3.0, +1.5] | −$44 [−182, +94] | 14 | −$0.6k |
| full-service | Mets | +1.6 [−0.8, +4.1] | +$100 [−51, +250] | 13 | +$1.3k |

Every CI spans zero, and the signs disagree across baskets and teams. **There is no measurable seasonal exposure.**

**Hedge (mechanics only, `hedge_sim.csv`).** The rule follows r5-bars: before series k, buy the side of "NYY wins series k" that offsets the expected value of series k+1's nights. Contracts are KXMLBSERIES-26BOSNYYWC-NYY at 0.61 and KXMLBSERIES-26NYYTBALDS-NYY at 0.54 (median of the first three traded daily closes; r5-markets' cached 2025 NYY candles carry no prices). CS/WS are **assumed 0.50**. Fee is 0.07·p(1−p). Over 20k simulated Yankees postseasons using the +0.78%/night point estimate, SD drops from $614 to $283 and the 5th percentile rises from +$213 to +$474. That reduction is purely mechanical: the payout is a deterministic function of the advancement that adds the nights. Because the per-night effect is indistinguishable from 0 (and could be −3% or +5%), **the hedge has no demonstrated basis and shouldn't be demoed.** Over a whole run the stake is ≈ 0.1 day of revenue either way. r5-markets has no RESULTS.md yet; I only used its cached Kalshi candles and catalogue.

## Verdict per candidate
| candidate | verdict | why |
|---|---|---|
| Yankees postseason → bars/restaurants | NOT FOUND | train and holdout both ≈0 |
| Mets postseason → bars/restaurants | NOT FOUND | train ≈0; no 2025 postseason (no holdout) |
| Giants/Jets primetime | NOT FOUND | n = 9 in train, ≈0 |
| Super Bowl Sunday | NOT FOUND | n = 3; the week-before placebo is just as negative |
| March Madness days | NOT FOUND | train ≈0, holdout +4.8% (wrong sign) |
| Election night | NOT FOUND (untestable) | n = 1 per period; −8 to −10% in 2024 but not significant with an honest SE |
| World Cup USA / final | NOT TESTABLE | 2026 only (no train); USA matches ≈0 |
| Pooled big-TV displacement | NOT FOUND | −1.3% train / −0.2% holdout; placebo the same size |
| Stakes scaling (round, tier) | NOT FOUND | the one formal pass is a calendar artifact (fails placebo) |
| MLB-run seasonal exposure + KXMLBSERIES hedge | NOT FOUND | exposure CI spans 0; the hedge is mechanical only |

**Reading.** The Knicks/Rangers away-night drop looks specific to that series, not a general "big-TV night" law. Possible reasons, untested here: NBA/NHL playoff tips fall at 19:00–20:30 on weeknights in April–June, when going out is near its peak, and the r5 sample is 4 consecutive deep runs of two MSG teams with heavy local followings. Most events here are weekend, afternoon, national, or one-offs. This test has weaker power than r5-bars, though: the biggest events (Super Bowl, election) are n ≤ 3, and their −5 to −15% point estimates can't be told apart from same-season Sunday/weekday noise.

## Limitations
- Single-day families (Super Bowl, election, World Cup final) can't meet n ≥ 10. Their classical SEs assume homoskedastic errors.
- FHV holdout covers only 2025-09-29..2025-12-31 (12 event days).
- Daily Dewey totals mix lunch and evening, and many MLB/NCAA games were afternoon starts.
- Audience tiers are rough bands I assigned, not measured ratings.
- Kalshi prices: 2025 NYY candles were empty in the cache, and the CS/WS prices are assumptions.

Files: `fetch.py`, `run.py`, `events.csv`, `results.csv`, `verdict.csv`, `placebo.csv`, `exposure.csv`, `hedge_sim.csv`, `output.txt`. Caches are in `r2-cache/r7displacement_*`. Only basket sums are written: no venue names, ids or per-venue series.

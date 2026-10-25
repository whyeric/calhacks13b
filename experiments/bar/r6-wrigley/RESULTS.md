# R6 wrigley: Cubs playoff runs → crowds at Wrigley → Divvy trips (and displacement elsewhere)

## Mechanism (written before fitting)
1. Kalshi settles on advancement: series winner, pennant, "hosts N+ playoff games".
2. Advancement decides how many unscheduled home playoff games there are (MLB 2015–17: WC 1 game, DS 2-2-1, CS/WS 2-3-2).
3. Each home game puts about 41k fans plus a bigger crowd of non-ticket fans into the bars around Wrigley Field (Clark/Addison/Sheffield). The same applies to Blackhawks/Bulls games at the United Center.
4. Some of that crowd arrives and leaves by Divvy, so trips at stations near the venue rise. Bike trips stand in for foot traffic past Wrigleyville bars.
5. **Displacement hypothesis:** the crowd comes from somewhere, so Loop and lakefront stations should LOSE trips on those nights.
6. Celebration days (2015 Blackhawks parade, 2016 Cubs WS Game 7 night, the Nov 4 2016 parade) are one-off spikes.

Falsification: the same weekday 4–6 weeks later (November, off-season), the day before each game, a within-month permutation, UC games at Wrigley stations and vice versa, and every band measured relative to the rest of the city.

## Data
- **Divvy 2014–2017, all trips** (`archive (2).zip` → `data_raw.csv`, 13.8M trips incl. 3.8M casual "Customer" trips). Aggregated with duckdb to station×hour starts and ends, plus casual counts, in `r2-cache/r6wrigley_{starts,ends,stations}.parquet`. The extracts were deleted afterwards. Caveat: the "cleaned" `data.csv` is **subscribers only** (1,277 customers out of 9.5M rows), so it misses most of the crowd; use the raw file. I dropped 13 partial-export days (citywide total < 20% of the centred 15-day median).
- **Bands** (station lat/lon, haversine): W1 ≤450 m of Wrigley (2 stations: Sheffield & Addison, Clark & Waveland; 117 trips/day); W2 0.45–1 km (11); W3 1–2 km (29); U1 ≤700 m of the United Center (2; 28/day); U2 0.7–1.5 km (13); LOOP ≤1 km of State & Madison (35); LAKE = lakefront-named stations (15); REST = everything else (479; 11k/day).
- **Games:** ESPN schedules for CHC, CHW, CHI-NHL, CHI-NBA (seasontype 2/3). Cubs playoff home games: 2015 4, 2016 8, 2017 5 (the rained-out 10-10-2017 listing removed). UC playoff home dates: 2014 13, 2015 17, 2016 3, 2017 5.
- **Weather:** NOAA GHCN Chicago Midway USW00014819 (rain ≥0.01 in, tmax and tmax²).
- **Kalshi:** markets and candles cached by r5-markets (`r5markets_markets.json`, `r5markets_candles.json`).

## Method
log(band trips/day) ~ event dummies {cubs_reg_home, cubs_po_home, cubs_po_away, uc_reg, uc_po} + Sox home + rain + tmax + tmax² + holiday + special days + **year-month FE + DOW×month-of-year FE**, HAC(7), z = 1.645. Cubs terms: train 2014–16 (12 playoff home games) → holdout 2017 (5), each fitted independently. UC terms: train 2014–15 → holdout 2016–17. BH at 10% over the **40 train tests** (8 bands × 5 terms). Further checks are not in the BH count: 40 holdout fits, 24 relative-to-city fits, 12 casual/subscriber fits, 18 per-season fits, 14 placebo fits, 3 permutation tests and 32 special-day coefficients. About 180 estimates in total. The DOW×month FE matters: with plain DOW FE, the November same-weekday placebo came out +19% at W2 and +21% at the Loop, because October/November weekends differ from summer weekends.

## 1. Results (% change in daily trips)

| band | event | train % [90% CI] (n) | BH p | holdout % [90% CI] (n) | vs rest of city, train / holdout | verdict |
|---|---|---|---|---|---|---|
| **W1 ≤450 m Wrigley** | **Cubs playoff home** | **+126 [+75, +191] (12)** | <0.001 | **+107 [+70, +152] (5)** | +97 [+58, +146] / +108 [+82, +138] | **FOUND** |
| W1 | Cubs regular home | +64 [+55, +74] (245) | <0.001 | +91 [+75, +109] (82) | +58 / +79 | FOUND (scheduled; not a hedgeable risk) |
| W1 | Cubs playoff **away** (watch parties) | +20 [+6, +36] (13) | 0.056 | −5 [−14, +5] (4) | | not found |
| W1 | UC regular-season game | +14 [+5, +25] | 0.034 | +16 [+9, +23] | +7 / +10 | FOUND, but see caveat: a falsification flag |
| W2 0.45–1 km | Cubs playoff home | +35 [+24, +47] (12) | <0.001 | +3 [−8, +15] (5) | +18 / +4 [−2, +10] | **not found** (no holdout replication) |
| W2 | Cubs regular home | +9.5 [+5, +14] | 0.001 | +11 [+5, +17] | | FOUND (scheduled) |
| W3 1–2 km | Cubs playoff home | +25 [+17, +34] | <0.001 | −1 [−13, +13] | | not found |
| **U1 ≤700 m UC** | **Hawks/Bulls playoff home** | **+84 [+60, +111] (30)** | <0.001 | **+56 [+17, +107] (8)** | +81 [+61, +104] / +29 [+5, +59] | **FOUND** |
| U1 | UC regular-season | +61 [+44, +80] | <0.001 | +53 [+41, +65] | | FOUND (scheduled) |
| U2 0.7–1.5 km | UC playoff home | +15 [+6, +24] | 0.018 | +26 [+11, +42] | +13 / +2 [−2, +6] | passes the rules, **fails placebo** (below) |
| LOOP | Cubs playoff home | +21 [+7, +38] | 0.036 | +7 [−11, +29] | +6 [−1, +13] / +8 [−1, +18] | not found |
| LAKE | Cubs playoff home | +16 [−1, +35] | 0.20 | −15 [−33, +8] | +1 / −14 [−29, +3] | not found |
| REST city | Cubs playoff home | +15 [+7, +23] | 0.012 | −1 [−13, +14] | | not found |

The other 26 band×term pairs are in `verdict.csv`, `uplift.csv` and `uplift_relative.csv`.

**Replication by season** (each season fitted alone), W1 Cubs playoff home: 2015 +178% [+132, +233] (n=4); 2016 +74% [+21, +149] (n=8); 2017 +107% [+70, +152] (n=5). All three exclude 0. The matching regular-season home effects are +57%, +76% and +91%. W2 replicates in 2015 (+28%) and 2016 (+41%) but not 2017 (+3%).

**Playoff vs regular-season home** (Wald test, full 2014–17 fit): W1 +26 log pts [+9, +44]; W2 +15 [+7, +24]. A playoff game draws more than an ordinary home game, on top of the October baseline. UC: playoff minus regular is +11 lp [−2, +23] at U1, not significant.

**Who rides:** at W1, casual (Customer) trips rise +238% (train) and +126% (holdout) on playoff home days. Subscribers rise +101% and +115%. At W1+W2 the average playoff home date has +487 extra trips over a base of 768 (+63%), +171 of them casual. September regular-season home dates average +234.

**Hourly shape** (W1+W2, average excess / base): the excess builds from noon (+27/35) to 17–18h (+57/84, +61/77), dips during the game (19–20h: +25, +11), then post-game departures arrive at 22–23h (+49/19, +44/15, roughly 3× base). Rain matters: 10-11-2017, the rescheduled rain-out, is the only playoff date with negative excess.

## 2. Displacement: Loop and lakefront do NOT lose trips
The "crowd is pulled from the Loop/lakefront" hypothesis is **rejected**. Relative to the rest of the city, Loop stations are +6% [−1, +13] (train) and +8% [−1, +18] (holdout) on Cubs playoff home days. Lakefront is +1% / −14% [−29, +3]. Neither direction is significant in both periods. In absolute terms the Loop is up in train (+21%, BH p=0.036), but that doesn't replicate and matches the citywide +15%. UC playoff days show the same pattern (Loop/REST +3%, +1%). The extra trips near Wrigley look **additive**, not displaced. That makes sense: the counterfactual for most fans is staying home or driving, not a lakefront ride.

## 3. Placebos / falsification

| test | band | estimate [90% CI] | p |
|---|---|---|---|
| Cubs playoff home dates +4/+6 weeks (Nov, same DOW; n=20) | W1 | +7% [−6, +22] | 0.39 |
| same | W2 / LOOP / LAKE | +9% / +5% / +11% | 0.26 / 0.63 / 0.40 |
| day before Cubs playoff home (non-game; n=8) | W1 / W2 / LOOP | +16% / −5% / +4% | 0.25 / 0.49 / 0.73 |
| permutation: Cubs po home dates shuffled within year-month (200 draws) | W1 | real t = 7.4 vs perm \|t\| p95 = 4.2 | perm p = 0.005 |
| same | LOOP | real t = 3.1 vs p95 2.9 | 0.035 (marginal) |
| UC playoff dates +13 weeks (Jul–Sep, same DOW; n=21) | U1 / U2 | +8% / **+10% [+2, +18]** | 0.25 / **0.04** |
| day before UC playoff home (n=20) | U1 / U2 / LOOP | +10% / **+9%** / +9% | 0.36 / **0.07** / 0.18 |
| permutation, UC po | U1 | t = 7.9 vs p95 2.8 | 0.005 |
| Cubs playoff home at UC stations (wrong venue) | U1 | −2% [−20, +20] | 0.91 |

The W1 and U1 effects pass every placebo. **U2's +15–26% is the same size as its placebos (+9–10%)**, so I don't count it. The **W1 response to UC regular-season games (+14–16%) is a falsification warning**: Wrigley stations sit 7.5 km from the UC. Part of it is citywide (relative to REST it is +7–10%). The rest is unexplained (possibly Hawks/Bulls watch crowds in Wrigleyville bars, possibly leftover date-level confounding). I treat ~15% as the noise floor at W1. The Cubs playoff effect is about 7× that.

## 4. Special days (n = 1 each, descriptive only)
- 2016 Cubs parade and rally (Nov 4; route from Wrigley to Grant Park): W1 +180%, W2 +106%, lakefront +133%, REST +43%.
- WS Game 7 night (Nov 2, away in Cleveland): W2 +18%, lakefront −42%. Day after: W1 +47%, W2 +68%.
- 2015 Blackhawks parade (Jun 18): lakefront +45%, U2 +28%, W3 +30%.

## 5. $ at stake per round (Wrigleyville bars, foot-traffic proxy)
Pooled 2015–17 W1 uplift per playoff home game is **+121% (90% lower bound +85%)**. Translating that into bar dollars rests on assumptions that are not estimated here: **(a)** bar foot traffic moves 1:1 with W1 bike trips; **(b)** an average bar takes $6,000 on a normal October day; **(c)** about 60 bars and restaurants lie within 450 m. On those assumptions, **+$7.2k per bar per playoff home game** (lower bound +$5.1k), or **$434k for the cluster**. Elasticity 1 is probably conservative for bars: the bars are what draws the crowd, and the docks are often full. For the Divvy operator: +171 casual trips × ~$4 = **~$700/game**, which is negligible.

Exact enumeration of the 2015–17 format with P(home win) = 0.54 for even teams (`exposure.csv`):

| entry scenario | E[home games] | SD | per-bar E | per-bar SD |
|---|---|---|---|---|
| division winner, top-2 seed (2016-like) | 4.67 | 2.64 | $33.8k | $19.1k |
| division winner, 3rd seed (2017-like) | 3.91 | 2.61 | $28.3k | $18.9k |
| wild-card host | 3.07 | 2.61 | $22.2k | $18.9k |
| wild-card visitor (2015-like) | 1.76 | 2.52 | $12.7k | $18.2k |

At stake on each round for a top seed: winning the DS is worth 4.45 more expected home games (**$32k/bar, $1.9M cluster**). Winning the CS is worth 2.94 (**$21k/bar, $1.3M cluster**). Winning the WS adds no home games, so there is no Wrigleyville exposure to the title itself, only the parade (n=1). Actual home-game counts: 2015 = 4, 2016 = 8, 2017 = 5, i.e. $29k, $58k and $36k per bar.

## 6. Basis: Kalshi
- **`KXMLBPLAYOFFHOST-<yy>CHC-<k>`, "Chicago C hosts k+ playoff games"** (k = 2, 4, 6, 8). This settles **directly on the quantity that drives revenue** (the home-game count), so basis risk for the count is zero. The remaining basis is uplift per game (the 90% CI is ±40% of the point estimate) and weather on game nights. Listing-day mid prices (2026-09-16): 2+ 0.735, 4+ 0.365, 6+ 0.155, 8+ 0.095. All resolved NO; the Cubs lost the 2026 WC 0-2 at San Diego. Volume was thin (mostly quotes).
- Also available: `KXMLBSERIES` (series winner, e.g. 25SDCHC-CHC first 0.52, 25CHCMIL-CHC 0.54, 26CHCSDWC-CHC 0.48), `KXMLBNL`, `KXMLB`, `KXMLBPLAYOFFS`. For the Blackhawks: `KXNHLPLAYOFF`, `KXNHLSERIES`, `KXNHLWEST`, `KXNHL`. Kalshi had no sports markets in 2015–17, so the historical backtest uses model prices.
- **Hedge** (top-seed distribution, 20k simulated seasons; buy at fair + $0.02 + 0.07·p·(1−p)). A business that loses money when H is small buys **NO on each "hosts k+" rung, $2U per rung** (U = $7.2k):

| | mean | SD | 5th pct |
|---|---|---|---|
| unhedged | $33.7k | $19.1k | $14.5k |
| NO ladder k = 2, 4, 6, 8 (what Kalshi lists) | $32.0k | **$4.5k (−76%)** | **$28.2k** |
| NO ladder every k (not listed) | $31.6k | $0 | $31.6k |

Using the actual seasons as the outcome draw: 2015 $28.9k → $28.2k hedged; 2016 $57.9k → $28.2k; 2017 $36.2k → $35.5k. The hedge costs about $1.7k/season (5%) and gives up the 2016 upside. As usual, small n: these are 3 seasons with a modelled price.

## Verdict
- **FOUND: Cubs playoff home game → +100–125% Divvy trips within 450 m of Wrigley.** It survives BH (p < 0.001), holds in a separate 2017 holdout (+107%), holds in each season fitted alone, holds relative to the rest of the city, and passes the off-season same-weekday, day-before and permutation placebos. The effect is larger than for regular-season home games (+26 lp). It settles one-for-one through `KXMLBPLAYOFFHOST`. This is the cleanest playoff→local-demand link in the R5/R6 rounds, but it lives at 2 stations (117 trips/day), and the dollar translation to bars rests on assumptions (a)–(c).
- **FOUND: Hawks/Bulls playoff home → +56–84% within 700 m of the United Center** (2 stations, 28/day; placebos pass).
- **NOT FOUND:** 0.45–2 km rings (train only), Cubs away-playoff watch-party nights (+20% train, −5% holdout), Loop/lakefront **displacement** (none; if anything the effect is additive), and U2 (fails placebo).
- **Caveat:** W1 also reacts +15% to UC regular-season games, which has no causal story. Read W1 effects below ~15% as noise.

## Demo idea
"Wrigleyville bar playoff hedge": a slider for the bar's normal October day revenue. Show the H distribution, $ at stake per round, and the 4-rung NO ladder on KXMLBPLAYOFFHOST sized at 2U per rung. Then overlay the 2016 hourly Divvy excess at Sheffield & Addison (pre-game build-up, game-time dip, post-game spike) as evidence that the crowd shows up.

## Files
`fetch.py` (ESPN, NOAA), `wrigley.py` (analysis), `output.txt`, `verdict.csv`, `uplift.csv`, `uplift_relative.csv`, `placebo.csv`, `exposure.csv`. Aggregation: `fetch.py <path to extracted data_raw.csv>` (duckdb, station × hour with a casual count), then delete the extract. No raw trips are stored in the repo.

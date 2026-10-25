# R2 taxi at scale: do Central Park weather events move citywide TLC demand?

Scripts (run from `backend/`):
- `.venv/bin/python ../experiments/bar/r2-taxi/fetch_tlc.py`: daily aggregates into the scratchpad `r2-cache/tlc/`. This takes about 40 min the first time, mostly the 2025 FHV months.
- `.venv/bin/python ../experiments/bar/r2-taxi/r2_taxi.py`: all tables below.

## Question
Round 1 used one taxi zone over 700 days. Its rain and hot effects did not replicate. With 4 years of citywide yellow-cab and Uber/Lyft (HVFHV) data, does rain → more demand show up and replicate? Is it hedgeable with a contract that settles on Kalshi's flag?

## Data
- **TLC trip records, 2022-01..2025-12, 1,461 days.** These are NYC Open Data's per-year Yellow and High-Volume FHV trip tables, aggregated per day on the server with SoQL. Raw trips were never downloaded.
  - I first tried streaming the CloudFront parquet bucket with duckdb httpfs. It returned HTTP 403 after about 20 months of range reads, so that route was dropped.
- **Six series:**
  - `yellow_trips` and `yellow_usd` (total_amount)
  - `fhv_trips` and `fhv_usd` (base_passenger_fare + tips)
  - zone 186 pickups: `z186_yellow_usd`, and `z186_all_usd` (yellow + FHV)
- **Mean train day:** 107k yellow trips / $2.68M; 609k FHV trips / $15.4M.
- **Data gaps:** the Open Data yellow tables are missing most rows on 4 days (2022-09-18, 2023-09-22..24: about 5k trips against about 100k). The rule "yellow < 25% of its 29-day rolling median" sets those days to missing. It was fixed before any fit and catches nothing else. With the rule off, the same 9 rows are FOUND.
- **Weather:** NOAA GHCN-Daily for Central Park, USW00094728. This is the station the KXRAIN and KXHIGHNY contracts settle on, so the `rain >= 0.01 in` and `tmax > strike` flags are the settlement flags themselves (basis r = 1). tmax is rounded to whole °F, as the NWS reports it.

## Method
- **Model:** one OLS per series × event, one event at a time. Controls come from `build_design`: DOW dummies, season harmonics k=1,2 and a holiday flag (US federal + Dec 24/31 + the day after Thanksgiving). I added a linear trend, because FHV grows about 10%/yr.
- **Errors:** HAC (Newey-West, 7 lags), z = 1.645.
- **Train and holdout:** train is 2022-2023 (730 days). The holdout is 2024-2025 (731 days), refit on its own. Nothing was tuned on the holdout.
- **Multiple comparisons:** 6 series × 6 events = **36 tests**. BH at 10% is applied to the 36 train p-values; 12 survive. The lead later asked for snow ≥ 1 in, which makes 42 tests: 16 survive BH on train and the same 9 are FOUND.
- **Hedge backtest:** for each FOUND row, buy the side that pays when revenue is low (NO if β > 0). Price = train frequency of that side + $0.02, plus a fee of 0.07·p·(1−p), with |β| contracts. Scored on the 731 holdout days, using both raw revenue and "resid" revenue (revenue minus the train model's calendar baseline).

## Basis of the non-standard events vs the KXRAIN settlement flag (Pearson r, 2022-25)
| event | r with KXRAIN | frequency |
|---|---|---|
| rain ≥ 0.01 in (= KXRAIN) | 1.000 | 0.336 |
| rain ≥ 1 mm | 0.876 | 0.280 |
| rain ≥ 5 mm | 0.640 | 0.172 |
| hot tmax > 85F (KXHIGHNY strike) | settles directly | 0.109 |
| hot tmax > 90F (KXHIGHNY strike) | settles directly | 0.033 |
| snow ≥ 0.1 in (daily; Kalshi only lists monthly snow) | 0.217 | 0.023 |

## Results (β in trips or $/day; % = β / period mean; CI90)
All 36 rows are printed by the script. The table below has the FOUND rows plus the rain and snow rows for the main series.

| series | event | train n | train β [CI90] | % | holdout n | holdout β [CI90] | % | BH q | verdict |
|---|---|---|---|---|---|---|---|---|---|
| fhv_trips | rain ≥ 0.01 in (KXRAIN) | 245 | +13,106 [6,686, 19,526] | +2.2% | 246 | +16,036 [9,613, 22,458] | +2.4% | 0.009 | **FOUND** |
| fhv_trips | rain ≥ 1 mm | 208 | +15,489 [8,606, 22,371] | +2.5% | 201 | +16,369 [9,245, 23,492] | +2.5% | 0.005 | **FOUND** |
| fhv_trips | rain ≥ 5 mm | 143 | +17,210 [9,413, 25,007] | +2.8% | 108 | +24,625 [13,732, 35,519] | +3.7% | 0.005 | **FOUND** |
| fhv_usd | rain ≥ 0.01 in (KXRAIN) | 245 | +$308k [94k, 523k] | +2.0% | 246 | +$494k [245k, 744k] | +2.7% | 0.072 | **FOUND** |
| fhv_usd | rain ≥ 1 mm | 208 | +$363k [147k, 578k] | +2.4% | 201 | +$476k [212k, 739k] | +2.6% | 0.038 | **FOUND** |
| fhv_usd | rain ≥ 5 mm | 143 | +$419k [154k, 683k] | +2.7% | 108 | +$695k [308k, 1,083k] | +3.8% | 0.047 | **FOUND** |
| fhv_trips | hot > 90F | 23 | +20,644 [9,471, 31,817] | +3.4% | 25 | +32,392 [13,798, 50,985] | +4.9% | 0.021 | FOUND (not hedgeable, see below) |
| yellow_trips | hot > 90F | 23 | +4,093 [1,079, 7,107] | +3.8% | 25 | +6,728 [307, 13,149] | +5.5% | 0.088 | FOUND (not hedgeable) |
| z186_yellow_usd | hot > 90F | 23 | +$3,142 [808, 5,477] | +4.0% | 25 | +$11,049 [6,995, 15,103] | +11.2% | 0.088 | FOUND (not hedgeable) |
| yellow_usd | rain ≥ 0.01 in | 243 | −$25.5k [−60.8k, 9.8k] | −1.0% | 246 | +$55.4k [2.4k, 108.3k] | +1.6% | 0.35 | not found (sign flips) |
| yellow_usd | rain ≥ 5 mm | 141 | −$70.6k [−113.1k, −28.1k] | −2.6% | 108 | +$74.2k [−4.1k, 152.5k] | +2.2% | 0.038 | not found (sign flips) |
| yellow_trips | rain ≥ 5 mm | 141 | −2,384 [−3,994, −775] | −2.2% | 108 | +3,183 [456, 5,910] | +2.6% | 0.067 | not found (sign flips) |
| z186_yellow_usd | rain ≥ 0.01 in | 243 | −$660 [−1,760, 440] | −0.8% | 246 | +$1,969 [308, 3,630] | +2.0% | 0.43 | not found |
| z186_all_usd | rain ≥ 1 mm | 206 | +$4,967 [540, 9,393] | +2.3% | 201 | +$6,870 [1,662, 12,078] | +2.7% | 0.16 | not found (fails BH) |
| z186_yellow_usd | snow ≥ 0.1 in | 12 | −$5,211 [−9,512, −910] | −6.7% | 22 | −$6,700 [−11,589, −1,811] | −6.8% | 0.12 | not found (fails BH) |

**Count:** 36 tests, 12 pass BH on train and 9 are FOUND: 6 FHV rain rows and 3 hot > 90F rows. No snow row survives BH. hot > 85F never passes on train.

## Hedge backtest (holdout 2024-25, 731 days)
| series / event | β | side @ price | cost/day | SD raw | SD resid | p5 raw | p5 resid |
|---|---|---|---|---|---|---|---|
| fhv_usd / KXRAIN ≥ 0.01 in | $308k | NO @ 0.68 | $11.1k | 2.560M → 2.546M (**−0.53%**) | 2.039M → 2.023M (**−0.76%**) | −$103k (worse) | −$30k (worse) |
| fhv_usd / rain ≥ 1 mm | $363k | NO @ 0.74 | $8.6k | −0.45% | −0.73% | −$62k | +$10k |
| fhv_usd / rain ≥ 5 mm | $419k | NO @ 0.82 | −$7.5k | −0.57% | −0.77% | +$14k | +$69k |
| fhv_trips / KXRAIN (trips as units) | 13.1k | NO @ 0.68 | 472 | −0.82% | −1.32% | −251 | +294 |
| any series / hot > 90F | | NO @ 0.99 | ≈ β·0.02 | ±0.2% | ≈0 | ≈0 | ≈0 |

- The rain hedge reduces SD on the holdout every time, by about 0.5-0.8%, for a small cost (about 0.07% of mean daily fares at the KXRAIN strike).
- On the settled KXRAIN flag it does not improve the 5th-percentile day. The worst days come from things other than rain (holidays, storms, snow), and on those days the NO leg often loses.
- hot > 90F has train frequency 3%, so NO costs $0.99 and the hedge pays almost nothing. It is real but not usefully hedgeable.

## Snow follow-up (lead's request: SNOW ≥ 0.1 in and ≥ 1 in, GHCN USW00094728)
Snow days at the station:

| year | ≥ 0.1 in | ≥ 1 in | season total (in) |
|---|---|---|---|
| 2022 | 8 | 4 | 17.7 |
| 2023 | 4 | 0 | 2.3 |
| 2024 | 8 | 5 | 10.3 |
| 2025 | 14 | 7 | 17.3 |

Train has 12 days ≥ 0.1 in and only **4 days ≥ 1 in**, so every ≥ 1 in row fails the ≥ 10 event-day rule. That is because 2023 was an almost snowless winter.

| series | event | train n | train β [CI90] | % | holdout n | holdout β [CI90] | % | BH q (42 tests) | verdict |
|---|---|---|---|---|---|---|---|---|---|
| yellow_trips | ≥ 0.1 in | 12 | −9,333 [−18,474, −192] | −8.7% | 22 | −2,362 [−11,715, 6,991] | −1.9% | 0.16 | not found |
| yellow_usd | ≥ 0.1 in | 12 | −$164k [−324k, −5k] | −6.1% | 22 | −$185k [−413k, 43k] | −5.4% | 0.16 | not found |
| fhv_trips | ≥ 0.1 in | 12 | −19,406 [−67,964, 29,152] | −3.2% | 22 | −13,783 [−49,885, 22,319] | −2.1% | 0.56 | not found |
| fhv_usd | ≥ 0.1 in | 12 | −$480k [−1,328k, 369k] | −3.1% | 22 | −$812k [−1,951k, 327k] | −4.4% | 0.44 | not found |
| z186_yellow_usd | ≥ 0.1 in | 12 | −$5,211 [−9,512, −910] | −6.7% | 22 | −$6,700 [−11,589, −1,811] | −6.8% | 0.11 | not found (BH only) |
| z186_all_usd | ≥ 0.1 in | 12 | −$16.2k [−29.4k, −3.0k] | −7.4% | 22 | −$14.3k [−30.3k, 1.7k] | −5.7% | 0.11 | not found |
| yellow_trips | ≥ 1 in | 4 | −27,778 [−45,036, −10,521] | −25.9% | 12 | −6,587 [−22,133, 8,960] | −5.4% | 0.038 | not found (n < 10) |
| yellow_usd | ≥ 1 in | 4 | −$428k [−765k, −92k] | −15.9% | 12 | −$252k [−624k, 120k] | −7.4% | 0.096 | not found (n < 10) |
| fhv_trips | ≥ 1 in | 4 | −101,578 [−195,912, −7,244] | −16.7% | 12 | −29,644 [−89,088, 29,800] | −4.5% | 0.15 | not found (n < 10) |
| fhv_usd | ≥ 1 in | 4 | −$1.79M [−3.50M, −0.08M] | −11.6% | 12 | −$0.95M [−2.87M, 0.96M] | −5.2% | 0.16 | not found (n < 10) |
| z186_yellow_usd | ≥ 1 in | 4 | −$14.2k [−21.0k, −7.4k] | −18.2% | 12 | −$5,257 [−12,281, 1,767] | −5.3% | 0.008 | not found (n < 10) |
| z186_all_usd | ≥ 1 in | 4 | −$42.1k [−64.6k, −19.6k] | −19.4% | 12 | −$12.2k [−36.7k, 12.2k] | −4.9% | 0.017 | not found (n < 10) |

- **Zone 186, yellow, ≥ 0.1 in** reproduces the other agent's result: about −$5-7k/day in both periods, with both CIs excluding 0. It misses BH at q = 0.11 here, against the 10% cutoff.
- **Citywide yellow and FHV:** the sign is negative everywhere, but no holdout CI excludes 0. So citywide is not stronger than zone 186.
- **Descriptive pooled 2022-25 fit** (not a FOUND test; it uses the holdout). 34 days ≥ 0.1 in, 16 days ≥ 1 in:
  - yellow_usd −6.6% [−$359k, −$43k], p = 0.037
  - yellow_trips −2.2% (n.s.)
  - fhv_usd −3.9% (n.s.)
  - fhv_trips −2.3% (n.s.)
  - z186_yellow_usd −8.2% [−$11.2k, −$3.2k], p = 0.003
  - On snow, yellow revenue falls more than yellow trips.
- **Kalshi basis:** The NYC snow markets in the shared cache are monthly totals (KXNYCSNOWM); I found no daily snow contract. A daily snow flag has r = 0.22 with KXRAIN. The basis is therefore weak unless a daily snow market exists.
- **Snow verdict: NOT FOUND.** The direction is consistent (snow → fewer yellow fares, strongest at MSG), but 4 years still give too few snow days. The binding constraint is the thin 2022-23 train winter, not the series' noise.

## Verdict
- **FOUND: citywide Uber/Lyft (HVFHV) demand vs KXRAIN.**
  - On rain days, FHV trips rise about 2.2-2.4% and fares about 2.0-2.7%. The effect replicates out of sample, its CI excludes 0 in both periods, and it survives BH.
  - It is measured on the exact settlement flag (basis r = 1), and the effect grows with rain amount (0.01 in < 1 mm < 5 mm), which is what the literature's mechanism predicts.
  - The hedge bonus is met on SD (−0.5% to −0.8%) but not on p5 at the KXRAIN strike.
- **FOUND but not hedgeable: hot > 90F** on FHV trips, yellow trips and zone-186 yellow fares. There are only 23-25 event days per period, and NO costs 0.99.
- **NOT FOUND: yellow cabs and rain.** The sign flips between periods (−1% in 2022-23, +1.6% in 2024-25). A plausible reason is that yellow supply is fixed, so in rain the cabs fill up rather than the trip count rising, and the fleet and congestion pricing changed in 2025. This is why round 1's single yellow zone could not replicate.
- **NOT FOUND: zone 186** (the MSG area) for anything except the unhedgeable hot > 90F row. Rain on all modes points the same way in both periods, but it fails BH.
- **Size caveat (same as round 1):** rain moves FHV revenue about 2%, while day-to-day residual SD is about 13% of the mean. A perfect rain hedge removes less than 1% of variance, so the result is real but small.

## Demo idea
"An Uber/Lyft-style fleet in NYC earns about $15M/day. On KXRAIN = YES days it earns about $0.3-0.5M more. This was measured on 2022-23 and confirmed on 2024-25." Then show the two CI bars side by side (train vs holdout, both above 0), and the holdout SD with and without a NO-on-KXRAIN position sized at |β|.
- For a single driver, scale by 1/(number of active drivers): a driver doing about $400/day gets about +$8-10 on rain days.
- That makes it a clean worked example of a real exposure that is also economically tiny. The honest pitch is "the hedge is correctly sized and cheap, but rain isn't your main risk".

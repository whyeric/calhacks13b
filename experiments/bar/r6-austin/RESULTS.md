# R6 austin: heat → night → Sixth/Rainey, UT football, festivals (Austin B-cycle 2014–2017)

## Pre-registration (written before any fit)

**Data.** Austin B-cycle trips (`archive (3).zip`, 649k trips, 2013-12-21..2017-07-31), aggregated to station-group × service day (a service day runs 03:00–02:59 so late-night trips count with the evening they belong to). Weather: NOAA GHCN-D USW00013904 (Austin Bergstrom, the KXHIGHAUS settlement station). Train = 2014-01-01..2015-12-31, holdout = 2016-01-01..2017-07-31.

**Station groups (fixed by location before fitting).**
- `SR`, Sixth Street / Rainey bar and music district: Trinity & 6th, Brazos & 6th, 6th & Congress, Red River & 8th, San Jacinto & 8th, Waller & 6th, Medina & E 6th, Rainey @ Cummings, Davis @ Rainey, Rainey @ River.
- `CAMPUS`, within 1.3 km of DKR stadium (30.2837, −97.7323): UT West Mall, Guadalupe & 21st, 17th & Guadalupe, Bullock Museum, Capitol / San Jacinto garages, Brazos & 18th, etc. (computed by distance in the script).
- `ZILKER`, the ACL site: Zilker Park, Zilker Park West (ACL only), Barton Springs Pool, Barton Springs @ Kinney, Sterzing, MoPac ped bridge, Toomey Rd.
- `ALL`, the whole system.

**Model.** OLS, y = log(1 + trips), on the event, DOW, federal holiday, year-month FE, rain (PRCP ≥ 0.01 in), SXSW, ACL and UT home-game dummies (each used as a control when it is not the event). HAC errors (7 lags), z = 1.645. Train and holdout fit independently.

### Chain 1: heat × bar districts
Mechanism: a > 100 °F day (KXHIGHAUS "above 100" YES) makes daytime riding unpleasant → people shift trips to after sunset → night trips concentrate on the bar/music district (Sixth / Rainey) → a bar there gains, i.e. a heat contract could be a *positive* exposure for Sixth Street bars. Each link is tested:
- H1 ALL trips (expected −), H2 ALL day-time trips 06–18h (−), H3 ALL night trips 19–02h (+), H4 night share log(night) − log(all) (+), H5 SR night arrivals (trips ending at SR, 19–02h) (+), H6 SR share of night arrivals (+).
Event: tmax ≥ 101 °F (Kalshi strike 100, integer °F). Secondary strike: tmax ≥ 98 °F (more event days). 6 outcomes × 2 strikes = 12 tests.
Placebos: (a) lead, tomorrow is hot but today is not; (b) permutation, hot labels shuffled within year-month (500 draws); (c) wrong-city, Central Park tmax ≥ 90 °F with Austin heat controlled.

### Chain 2: UT Longhorns football
Mechanism: DKR home game → ~100k people near campus → CAMPUS station trips rise on game day; after the game fans go downtown → SR night arrivals rise; a win → more celebrating → more SR night arrivals than a loss. Bowl qualification → extra games.
- F1 CAMPUS trips on home-game days (+), F2 SR night arrivals on home-game days (+), F3 SR night arrivals on away-game days (watch parties, +), F4 SR night arrivals, win vs loss among home games (+). 4 tests.
- Bowl games are never played at DKR (Texas Bowl Houston, Alamo San Antonio, etc.), so bowl qualification adds zero local home games. Chain broken a priori; only 2014 had a bowl in this window (n = 1). Not tested.
- Placebo: each home game is replaced with the non-game fall Saturday in the same season closest in tmax, re-fitting F1/F2 without the real game days; plus the day after (Sunday).
- Season data: 2014, 2015 (train, 12 home games) and 2016 (holdout, 6 home games). 2017 season is after the data ends.

### Chain 3: festivals as controls, heat × ACL
Mechanism: ACL weekend → huge ZILKER traffic; a hot ACL day → fewer attendees ride to Zilker. A1: among ACL days, ZILKER arrivals per +10 °F tmax (−). A2: ACL hot day (tmax ≥ 90 °F) dummy (−). 2 tests. ACL days in data: 2014, 2015 (train, 12 days) and 2016 (holdout, 6 days).

**Total family: 12 + 4 + 2 = 18 tests**, BH at 10% on train p and holdout p separately. FOUND needs all exp2_common criteria plus a clean placebo.

---

## Results (after fitting)

**Verdict: NOT FOUND on every chain. 0 of 18 tests pass.** The headline "heat helps Sixth Street" chain is falsified: its sign is wrong.

**Panel.** 1,249 service days, 2014-01-01..2017-07-31. April 2016 and December 2016 are missing from the source; year-month FE absorb this. Event days:
- Heat: tmax ≥ 101 °F on 17 train days and 13 holdout days. 12 of the 13 holdout days fall in the single summer of 2017.
- Football: 12 train home games and 6 holdout home games.
- ACL: 18 days in total, with tmax between 78 and 95 °F and only 2 days ≥ 90 °F.

Effects are in % (from log points), with 90% CIs. BH runs over 18 tests, separately on train p and holdout p. Full table: `output.txt` and `results.csv`.

| chain | test | train β % [90% CI] (n ev) | q tr | holdout β % [90% CI] (n ev) | q ho | verdict |
|---|---|---|---|---|---|---|
| heat | H1 all trips, ≥101 | −8.5 [−21.6, +6.9] (17) | 0.76 | −17.1 [−26.6, −6.4] (13) | 0.03 | NOT FOUND |
| heat | H3 night trips 19–02h, ≥101 | −10.7 [−23.4, +4.0] (17) | 0.76 | −23.3 [−35.2, −9.1] (13) | 0.03 | NOT FOUND |
| heat | H4 night share, ≥101 | −2.5 [−13.1, +9.4] (17) | 0.86 | −7.5 [−15.4, +1.2] (13) | 0.31 | NOT FOUND (sign wrong) |
| heat | H5 SR night arrivals, ≥101 | −9.1 [−25.4, +10.7] (17) | 0.76 | −23.1 [−32.7, −12.1] (13) | 0.01 | NOT FOUND (sign wrong) |
| heat | H6 SR share of night, ≥101 | +1.9 [−12.9, +19.1] (17) | 0.95 | +0.2 [−9.7, +11.2] (13) | 1.00 | NOT FOUND |
| heat | H5 SR night arrivals, ≥98 | −11.2 [−23.1, +2.6] (60) | 0.76 | −11.4 [−19.8, −2.1] (64) | 0.10 | NOT FOUND |
| football | F1 CAMPUS trips, home game | +50.4 [+3.8, +117.9] (12) | 0.71 | +97.3 [+41.9, +174.3] (6) | 0.01 | NOT FOUND (train fails BH) |
| football | F2 SR night arrivals, home game | +3.0 [−30.2, +51.9] (12) | 0.95 | +52.5 [−8.5, +154.3] (6) | 0.31 | NOT FOUND |
| football | F3 SR night arrivals, away game | +13.4 [−10.3, +43.4] (12) | 0.76 | −16.6 [−34.8, +6.7] (6) | 0.37 | NOT FOUND (sign flips) |
| football | F4 SR night arrivals, home win vs loss | +20.0 [−42.8, +151.9] (6 W) | 0.86 | +183 [+45, +455] (4 W) | 0.03 | NOT FOUND |
| acl | A1 ZILKER arrivals on ACL days, per +10 °F | +11.1 [−14.4, +44.3] (12) | 0.76 | +8.4 [+3.8, +13.2] (6) | 0.01 | NOT FOUND (sign opposite to hypothesis) |
| acl | A2 ZILKER on ACL days, tmax ≥ 90 | +19.6 [+0.9, +41.7] (2) | 0.71 | n/a (0 hot ACL days) | n/a | untestable |

The other six heat rows (H2 day trips at ≥ 101, plus H1–H4 and H6 at ≥ 98) are all nulls on train; see `output.txt`.

### Chain 1, heat × bar districts: falsified
- **The chain breaks at link 2.** Heat does not move riding into the night. The night share is −2.5% on train and −7.5% on holdout, not positive. The Sixth / Rainey share of night trips is flat (+2% and +0%).
- **The overall effect is a plain negative.** On a > 100 °F day, every segment falls, Sixth / Rainey night arrivals included. In Jul–Aug, the raw means on hot vs other days are 381 vs 471 trips per day overall and 15.2 vs 19.9 SR night arrivals.
- **Even the negative fails the bar.** The pooled permutation test, with heat labels shuffled within year-month, gives −17% SR night arrivals at p_perm = 0.043 and −13% all trips at p_perm = 0.050. But the train-period CIs include 0, and the holdout heat days are almost all from summer 2017.
- **The wrong-city placebo is not clean.** Central Park ≥ 90 °F "predicts" holdout Austin all trips at −8.5% [−14.1, −2.5] and the night share at −11% [−17, −4]. Within-month heat comparisons in this panel pick up something beyond Austin's own weather, so the holdout heat betas should not be trusted either.
- **Lead placebo** (tomorrow hot, today not): the night share is +23% on train with n = 7 and +2% on holdout. This is noise of the same size as the "effects".
- **Takeaway:** a heat contract is not a positive exposure for Sixth Street. At most it is a weak, ordinary negative one, and it is not established.

### Chain 2, UT football
- **F1, game-day crowds:** the effect at campus stations looks real in magnitude, at +50% and +97%. The matched-tmax non-game-Saturday placebo is smaller and its CI includes 0 (+3% and +23%), and the Sunday after a game is negative. But the train CI barely clears 0 and fails BH (q = 0.71). It is also not a hedgeable risk: home dates are published months ahead.
- **F4, win vs loss:** this is the only part a Kalshi game contract could settle on, and it is null on train (n = 6 wins vs 6 losses). The holdout +183% rests on 4 wins vs 2 losses. Both 2016 losses were late-November games, one the day after Thanksgiving when students are gone, so this is schedule composition, not a win effect. The matched-Saturday placebo also gives holdout SR night +31% [+4, +65], which shows how noisy SR is at n = 6.
- **F3:** away-game watch parties flip sign between periods.
- **Bowls:** the chain is broken by construction. Bowls are never at DKR, so qualifying adds zero local game days. The window has a single bowl (2014 Texas Bowl, Houston). Not tested.
- **Basis:** KXNCAAFGAME exists today and settles on the game winner (sources NCAA and ESPN). The settled history in the API starts 2026-09-26 and includes Texas games, e.g. KXNCAAFGAME-26OCT10TEXOKLA. No Kalshi market of any kind existed in 2014–2017, since Kalshi launched in 2021. A past-price backtest is impossible, and the win-vs-loss exposure it would hedge is null here.

### Chain 3, festivals and heat × ACL
- ACL is a huge, known-in-advance effect on Zilker: 378 vs 48 arrivals per day in the same months. It was used as a control.
- **Heat × ACL is untestable at the Kalshi-relevant level.** The hottest ACL day in 2014–2016 was 95 °F, and only 2 days reached ≥ 90 °F. Across the range observed, hotter ACL days had *more* Zilker arrivals (+8–11% per +10 °F), the opposite of the hypothesis. This holds with the rain dummy and year FE in the model. Cool ACL days may be wet or overcast in ways a daily rain flag misses, but with n = 12 and 6 days this is not FOUND.

### Basis notes
- KXHIGHAUS lists T98 and T100 strikes (e.g. KXHIGHAUS-26SEP30-T100, -26OCT13-T98).
- "Above 100" = tmax ≥ 101, which is exactly my primary event.
- My secondary ≥ 98 corresponds to an "above 97" strike, one degree off the listed T98. It is a robustness strike only, fixed before fitting and not re-tuned.
- GHCN USW00013904 matched settled KXHIGHAUS 100% in r4-ercot.

### Hedge backtest
Not run: nothing passed the FOUND criteria.

### Count
18 pre-registered tests, plus 14 placebo fits and 3 permutation tests (reported, not in the BH family). Script: `austin.py`, about 18 s. The raw extract was deleted from r2-cache after the run. Only GHCN, the UT schedule cache (`r6austin_*`) and these aggregates remain.

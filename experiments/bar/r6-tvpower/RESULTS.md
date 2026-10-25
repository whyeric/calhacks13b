# R6 tvpower: do big-game outcomes move hourly electricity load?

## Mechanism (written before any fit)

A local team's game OUTCOME → how many people stay home watching, and for how long → hourly residential/commercial
load in that city's PJM zone → MWh (and so $) a utility or fixed-price retailer must buy in those hours.

Concretely, each outcome feature has a pre-stated sign hypothesis-free test (two-sided), and maps to a contract:

| feature | chain | Kalshi contract that settles on it |
|---|---|---|
| `po_in` | team advances → an extra playoff game is played → viewers at home during game hours | KXNHLSERIES / KXNBASERIES / KXMLBSERIES, KXNHLSERIESGAMES / KXNBASERIESGAMES / KXMLBSERIESGAMES, KXNHL / KXNBA / KXMLB(WS) |
| `po_post` | same, the 2 h after a playoff game | same |
| `ot` | game goes to OT / extra innings → viewing extends past regulation | KXNHLOT / KXNHLOVERTIME, KXNFLOT, KXNBAOT / KXNBAOVERTIME, KXMLBEXTRAS, KXNHL2OT |
| `close_late` | close margin → people keep watching the last hour instead of turning off | KXNFLWINMARGIN, KXNBAWINMARGIN, *SPREAD |
| `win_post` | win vs loss → post-game behaviour (celebrate out vs stay in) | KXNFLGAME / KXNHLGAME / KXNBAGAME / KXMLBGAME |
| `reg_in_<lg>` | reference: a regular-season game simply happening (schedule known in advance, not risk) | — |

Prior: the US "TV pickup" literature (e.g. Super Bowl) finds load DROPS during big games (people stop cooking, laundry,
going out to lit venues is ≈ neutral) with small rebounds at breaks; UK finds spikes at half-time (kettles). Hourly data
cannot resolve half-time spikes (they last minutes), so only hour-level shifts are testable here.

**Pre-fixed design.** Zones: PJME (Philadelphia), DUQ (Pittsburgh), COMED (Chicago). Split per zone by years: PJME
train 2002–2009 / holdout 2010–2018; DUQ 2005–2011 / 2012–2018; COMED 2011–2014 / 2015–2018; pooled = union.
Model: 100·log(MW) on game features (hourly overlap shares), hourly temperature spline × 4 hour-of-day groups, daily mean
temperature spline, holiday × hour, absorbed zone × hour × DOW × year-month FE; SE clustered by date; z = 1.645.
Family: 9 features × 4 (3 zones + pooled) = 36 train tests, BH 10%.
Placebos: (a) the same features applied to a far zone (Philadelphia games → AEP/Columbus, Pittsburgh → DOM/Richmond,
Chicago → PJME); (b) the outcome features shifted −24 h, fitted alongside the real ones.

---

## Answer

**NOT FOUND, for every outcome feature.** Advancement, overtime, close margin and win vs loss do not move hourly PJM
zone load in a way that replicates. None of the 20 outcome tests passes the train BH screen and also replicates on
holdout. The one outcome feature that clears BH on train (DUQ playoff hours, −0.9 to −1.2%) collapses on holdout. It
also shows up just as strongly in the day-before placebo and in a far-away zone, so it comes from the playoff calendar,
not the game. Three regular-season "a game is on" rows pass the formal rules. They are not hedgeable risk, because
schedules are known months ahead, and half of each effect also appears in a zone with no local team. The dollars are
trivial either way: even the largest point estimate (−$11k per playoff game in PJME, CI includes 0) is about 0.04% of
that zone's ~$30M daily energy cost. A single evening's idiosyncratic load noise (SD about 3% over 4 h) is worth more
than 10× any game effect.

## Data

- **Load:** PJM hourly MW from `~/Downloads/archive (4).zip`, extracted to the scratchpad (`r6tvpower_pjm/`) and deleted
  after the run. Stamps are hour-ending EPT, which I shifted to hour-beginning. PJME 2002-12..2018-08, DUQ
  2005-12..2018-08, COMED 2011-01..2018-08. Placebo zones: AEP (Ohio/WV etc.) and DOM (Virginia).
- **Games:** ESPN team schedules (regular season + postseason), 2002..2018: Eagles, Phillies, Flyers, 76ers / Steelers,
  Penguins, Pirates / Bears, Cubs, White Sox, Blackhawks, Bulls. That is 19,179 games (759 playoff). The fields used
  are the start time, final period count (→ OT / extra innings), score margin and winner. ESPN gives no end time, so
  each game's wall-clock length is set by rule: NFL 3.2 h, MLB 3.0 h, NHL 2.5 h, NBA 2.25 h. Extensions add NFL OT
  0.4 h, MLB 0.33 h per extra inning, NBA 0.25 h per OT, NHL playoff 0.6 h per OT period, and NHL regular-season
  OT/shootout 0.3 h. `games.csv` holds the public schedule.
- **Temperature:** Open-Meteo ERA5 hourly °F for Philadelphia, Pittsburgh, Chicago, Columbus and Richmond, in ET. It is
  used only as a control, not as an event, so the GHCN-vs-Open-Meteo rain issue does not apply.

## Method

The model is as pre-registered above, with one change: DUQ has no NBA team, so the family has 35 tests. Every
feature is an hourly overlap share (0..1), so β is the % change in load for one full game-hour.

- **In-game:** `po_in` and `reg_in_<lg>` cover start → regulation end.
- **OT:** `ot` covers regulation end → actual end. Its β is the effect of OT relative to those clock hours without OT.
- **Close margin:** `close_late` is the last regulation hour of games decided by ≤ 7 (NFL), ≤ 5 (NBA) or ≤ 1 (NHL,
  MLB), or that went to OT.
- **Post-game:** `po_post` is the 2 h after a playoff game's regulation end, and `win_post` the 2 h after a win.

Each zone's train and holdout periods are fitted independently. The script `tvpower.py` takes about 1 min and writes
`output.txt`, `results.csv` and `placebo_farzone.csv`. `fetch.py` pulls the public data.

## Results (all 35 train tests; % load per game-hour, 90% CI; d = event days)

| zone | feature | train β [90% CI] (d) | BH q | holdout β [90% CI] (d) | verdict |
|---|---|---|---|---|---|
| PJME | po_in | −0.04 [−0.47, +0.38] (143) | 0.93 | −0.31 [−1.00, +0.39] (106) | NOT FOUND |
| PJME | po_post | −0.25 [−0.68, +0.18] (159) | 0.54 | −0.50 [−1.25, +0.25] (135) | NOT FOUND |
| PJME | ot | −0.65 [−1.32, +0.02] (335) | 0.22 | −0.06 [−0.75, +0.62] (372) | NOT FOUND |
| PJME | close_late | +0.05 [−0.20, +0.31] (948) | 0.87 | −0.15 [−0.41, +0.11] (1031) | NOT FOUND |
| PJME | win_post | +0.22 [+0.05, +0.39] (1551) | 0.12 | +0.05 [−0.15, +0.24] (1571) | NOT FOUND |
| DUQ | po_in | −0.85 [−1.48, −0.22] (82) | 0.095 | −0.18 [−0.78, +0.42] (116) | NOT FOUND (holdout null; placebos below) |
| DUQ | po_post | −1.15 [−1.77, −0.53] (96) | 0.019 | −0.40 [−1.01, +0.22] (159) | NOT FOUND (holdout null; placebos below) |
| DUQ | ot | +0.77 [−0.02, +1.55] (259) | 0.22 | −0.12 [−1.12, +0.88] (242) | NOT FOUND |
| DUQ | close_late | +0.04 [−0.28, +0.36] (653) | 0.93 | +0.26 [−0.08, +0.60] (665) | NOT FOUND |
| DUQ | win_post | +0.19 [−0.07, +0.44] (1030) | 0.41 | +0.03 [−0.22, +0.27] (1147) | NOT FOUND |
| COMED | po_in | −0.23 [−0.99, +0.54] (98) | 0.87 | +0.25 [−0.59, +1.08] (86) | NOT FOUND |
| COMED | po_post | +0.18 [−0.50, +0.86] (140) | 0.87 | +0.65 [−0.12, +1.41] (118) | NOT FOUND |
| COMED | ot | −0.09 [−1.34, +1.16] (247) | 0.93 | −0.51 [−1.64, +0.62] (210) | NOT FOUND |
| COMED | close_late | +0.03 [−0.37, +0.43] (630) | 0.93 | +0.63 [+0.18, +1.07] (567) | NOT FOUND (train null) |
| COMED | win_post | −0.37 [−0.64, −0.10] (1060) | 0.095 | +0.18 [−0.12, +0.48] (930) | NOT FOUND (sign flips) |
| pooled | po_in | −0.31 [−0.66, +0.03] (298) | 0.26 | −0.12 [−0.53, +0.30] (282) | NOT FOUND |
| pooled | po_post | −0.33 [−0.67, −0.00] (371) | 0.22 | −0.16 [−0.59, +0.27] (373) | NOT FOUND |
| pooled | ot | −0.02 [−0.57, +0.54] (795) | 0.96 | −0.19 [−0.74, +0.35] (728) | NOT FOUND |
| pooled | close_late | +0.04 [−0.15, +0.23] (1984) | 0.87 | +0.19 [−0.00, +0.39] (1709) | NOT FOUND |
| pooled | win_post | +0.03 [−0.11, +0.16] (3072) | 0.87 | +0.08 [−0.06, +0.22] (2349) | NOT FOUND |
| COMED | reg_in_mlb | −0.38 [−0.59, −0.17] (686) | 0.019 | −0.27 [−0.53, −0.00] (633) | passes rules; not risk, fails placebo |
| pooled | reg_in_mlb | −0.21 [−0.32, −0.09] (2195) | 0.024 | −0.21 [−0.34, −0.07] (1489) | passes rules; not risk, fails placebo |
| pooled | reg_in_nhl | +0.38 [+0.21, +0.56] (1163) | 0.013 | +0.36 [+0.18, +0.54] (995) | passes rules; not risk, half in placebo |

The other 12 `reg_in_*` rows (NFL everywhere; NHL and NBA per zone; MLB for PJME and DUQ) do not replicate. All are
listed in `output.txt`.

## Placebos

- **Day-before (outcome features shifted −24 h, fitted with the real ones, full period).** The playoff "effect" is
  just as strong on the day BEFORE each playoff game. In PJME, `po_in` is −0.50 [−0.83, −0.17] the day before vs −0.23
  real, and `po_post` −0.61 the day before vs −0.40 real. In DUQ, `po_in` is −0.56 before vs −0.51 real, and
  `po_post` −0.80 before vs −0.82 real. The playoff calendar (late-April–June evenings, every other day) carries the
  dip, not the game. Adding a day-of-month × hour slope, to absorb sunset drift within the month, changes nothing.
- **Far zone.** Chicago playoff games "lower" PJME load by −0.62 [−1.02, −0.22] in-game and −1.06 post, while COMED's
  own estimate is −0.01. Pittsburgh playoff games "lower" DOM by −0.90 post. Same conclusion.
- **Regular-season rows.** The MLB in-game −0.2% shows up at −0.13 to −0.23% in DOM and PJME against another city's
  games. The NHL +0.38% shows up at +0.19 to +0.26% in AEP and PJME. About half of each effect, or more, is not local.
- **Super Bowl evening (18–22 h ET), every zone.** The three Steelers Super Bowls show DUQ −3.3, −4.7 and −5.1%.
  Other Super Bowls show −0.9% (se 0.95). The SD of any evening's residual is 3.2%. That is suggestive for n = 3, but
  the post-hoc check below kills it.
- **Exploratory, post hoc, not in the BH family.** Across all 19 Steelers playoff games, the 4 h in-game residual is
  DUQ −0.73% (se 0.80), against DOM −0.01 and PJME +0.24. own−far is −0.97 (se 0.61), and 12 of 19 games are negative.
  The Super Bowl and AFC-title dips are the tail of a noisy distribution, not a separate effect. Eagles: −0.23 (se 0.71).
- **Big-game residuals.** Single games swing ±5–16%: Blackhawks 2015 WCF G1 +16.5%, 2013 SCF G5 −11%, Cubs 2016 WS
  G1–G5 +3–7%. The sign is not consistent with outcome or round. It is mostly weather and model noise at the hourly
  level, worth hundreds of MW in COMED.

## Basis (Kalshi)

Every outcome feature maps one-to-one onto a live Kalshi series, with deterministic rules confirmed from `/markets`:

- **OT:** KXNHLOT ("at least 1 overtime period is played"), KXNFLOT, KXNBAOT and KXMLBEXTRAS.
- **Advancement:** KXNHLSERIES / KXNBASERIES / KXMLBSERIES series winners and KXNHLSERIESGAMES / KXNBASERIESGAMES /
  KXMLBSERIESGAMES total games.
- **Margin and winner:** KXNFLWINMARGIN / KXNBAWINMARGIN, and KXNHLGAME / KXNFLGAME / KXMLBGAME / KXNBAGAME.

So the basis is perfect. The exposure is what is missing. PJM load data ends in 2018, before Kalshi sports markets
existed, so no price backtest was possible. One was not needed, because nothing passed.

## Is the $ meaningful? No.

The table is holdout β × the zone's mean MW in those hours × hours × $40/MWh. All holdout CIs include 0 except COMED
close_late, whose train estimate is null.

| zone | per playoff game (in-game + 2 h post) | per OT | per close finish |
|---|---|---|---|
| PJME (~31 GW) | −$10k / −$11k | −$0.4k | −$2k |
| DUQ (~1.6 GW) | −$0.3k / −$0.5k | −$0.04k | +$0.2k |
| COMED (~11 GW) | +$3k / +$5k | −$1.3k | +$3k |

A playoff run of about 10 extra games moves a PJME-sized utility's energy cost by about $0.2M at the point estimate,
sign uncertain. That is about 0.7% of one day's ~$30M energy cost, so no utility or retailer would hedge it. The only
way this could matter is through PRICE spikes, which this data cannot show (no LMPs). Load shifts of < 1% in evening
shoulder hours are far too small to move PJM's bid stack.

## Tests run

35 main tests (BH family) + 27 far-zone placebo rows + 15 day-before rows + 15 robustness rows + 5 Super Bowl rows + 3
exploratory rows. Nothing was tuned on the holdout. The pre-registration (top of this file) was written before any fit.
The only change after it was dropping DUQ × NBA, because Pittsburgh has no NBA team.

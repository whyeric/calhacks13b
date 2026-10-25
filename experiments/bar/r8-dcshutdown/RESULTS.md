# R8 dcshutdown: federal government shutdown (Kalshi shutdown markets) → downtown DC lunch/after-work demand

## Mechanism (written before fitting)

Chain: a federal funding lapse → ~800k federal employees nationally furloughed or working unpaid, with
federal workers ≈ 20% of DC-area jobs and heavily concentrated in a few downtown clusters → furloughed
staff stop commuting to Federal Triangle, L'Enfant Plaza / SW federal center, Navy Yard and Farragut / K St
→ fewer weekday commute trips and fewer weekday lunch and after-work purchases near those clusters.
Smithsonian museums and the National Zoo also close, so tourist trips on the Mall should fall too.
A Kalshi shutdown contract ("shutdown happens by date", "shutdown lasts > N days") settles on the event
itself, so a downtown DC lunch spot would hedge by buying YES.

Predictions (pre-specified):
1. Weekday Capital Bikeshare trips starting or ending at federal-cluster stations fall during shutdown
   days relative to the same weeks in non-shutdown years, and relative to residential stations (DiD < 0).
2. Residential stations (U St / Columbia Heights / Capitol Hill residential) show a much smaller effect (placebo 1).
3. Fake shutdowns at the same calendar dates in non-shutdown years show ~0 (placebo 2).
4. Weekend effects at federal clusters are smaller than weekday effects (placebo 3).
5. The 2018–19 and 2025 shutdowns replicate independently (same sign, 90% CI excludes 0).

Pre-specified design: unit = station-group × day (trip starts plus ends, "touches"), summed over stations open the
whole season (Sep–Feb). Groups are fixed by distance to hand-placed centroids before fitting:
**fed** = Federal Triangle + L'Enfant / SW federal center + DOL (6–12 stations); **res** = U St / Logan / Columbia
Heights / Adams Morgan / Petworth / Capitol Hill / Lincoln Park (11–25); **mall** = Mall and memorial stations (4–9);
**kst** = Farragut / McPherson (private-sector offices, 11–15). Navy Yard and Foggy Bottom are kept separate
(**navy**, **fbot**) because they are also residential or GWU campus.
Spec A = DOW + year-month FE. Spec B (primary) = DOW + ISO-week FE + season FE. Both add federal holidays,
Dec 24–Jan 1, extra OPM closure days, the day after Thanksgiving and DCA weather (USW00013743: precip, rain ≥0.1 in,
snow, snow depth, tmax, tmax²). There is a dummy for every shutdown, plus a 14-day lead and a 7-day lag around each
long one. **Independent replication:** the 2018–19 shutdown is fit on pre-COVID seasons 2012–2019 (train), and the
2025 shutdown on post-COVID seasons 2021–2025 (holdout). The samples share no days. 2013 is a third event in the
pre sample.

## Data

- **Capital Bikeshare** trip history, 69 monthly or yearly zips, 2012-01..2026-06 (Sep–Feb of every season except
  2020, plus spring 2023–26). Public S3, no access block. Extracted one at a time, aggregated to station-day-band
  (r2-cache/r8dc_station_day.parquet, 5.8M rows), and each extract deleted. Pre-2020 station numbers are mapped to
  coordinates via GBFS `short_name`.
- **NOAA GHCN** DCA USW00013743.
- **Kalshi:** 372 shutdown-related markets (live plus the /historical archive), each with daily candles:
  GOVSHUT (2021–24 deadlines), KXGOVSHUT, KXGOVTSHUTDOWN, KXSHUTDOWNBY(-DATE), GOVSHUTLENGTH /
  KXGOVSHUTLENGTH / KXGOVTSHUTLENGTH (duration ladders), KXGOVTFUND and others.
- **WMATA:** skipped. The ridership portal is a Tableau dashboard with no automatable station-day export.
- **DC sales/meals tax:** not done quantitatively. OCFO cash-collection reports are monthly PDFs of *total* sales
  tax, filed a month in arrears, which is too coarse for 2–3 events. For context only: in Jan 2019 the CFO
  estimated the shutdown was costing DC about $12M a week in tax revenue, mostly from restaurants, hotels, retail
  and parking (reported by DCist, 2019-01-23).

## Inference note (important)

HAC errors are far too narrow for a 3–6 week block. Fake shutdowns at the same calendar dates in control years come
out "significant" at p<0.1 in about half of 51 placebo fits (placebo_fake_dates.csv). So the primary inference is
**randomization inference (RI):** slide a fake window of the real length across every control season (a start every
7 days, no overlap with a real lapse), refit spec B, and use that placebo distribution as the null. That gives 158
windows for 2013, 135 for 2018–19 and 80 for 2025. RI 90% CI = β − [q95, q05] of the placebo βs; RI p = share of
|placebo| ≥ |β|. BH is applied across the 21 non-placebo weekday RI tests (the HAC versions are in results.csv, with
BH over 72).

## Results (spec B, weekdays unless noted; % effect on trips, RI 90% CI)

| outcome | 2013 (16 d, full) | **2018–19 train** (35 d, partial) | **2025 holdout** (43 d, full) | BH q (18 / 25) |
|---|---|---|---|---|
| **fed − res (DiD)** | −37.6 [−43.8, −26.8] | **−14.6 [−22.5, −5.3]**, p=.022 | **−25.1 [−34.1, −15.8]**, p=.012 | .039 / .026 |
| **fed level** | −30.2 [−39.6, −13.1] | **−15.1 [−23.3, −3.5]**, p=.029 | **−19.7 [−35.5, −9.3]**, p=.074 | .044 / .097 |
| fed − res, lunch 10–14h | −40.7 [−49.2, −28.2] | −17.1 [−27.2, −2.9] | −20.1 [−30.3, −6.3] | .044 / .026 |
| fed level, lunch | −24.2 [−37.1, −5.7] | −21.7 [−33.3, −6.7] | −6.3 [−26.9, +9.2] (ns) | .028 / .635 |
| fed − res, AM 6–9h | −34.5 | −29.1 [−35.6, −22.2] | −29.6 [−39.8, −20.3] | .026 / .026 |
| fed − res, PM 15–19h | −38.5 | −9.6 [−19.1, +0.5] (ns) | −29.1 [−38.5, −19.4] | .145 / .026 |
| K St (private offices) | +12.3 (ns) | +2.0 (ns) | +7.5 (ns) | — |
| *placebo 1:* res level | +18.0 [+4.3, +33.6] | −1.4 [−10.8, +11.3] | +7.2 [−3.7, +16.6] | — |
| Mall level | −29.0 | −16.1 (ns) | −0.4 (ns) | — |
| *placebo 3:* fed − res, weekends | −40.5 | +1.7 (ns) | −9.2 (ns) | — |
| *placebo 3:* fed level, weekends | −46.9 | −0.8 (ns) | −8.8 (ns) | — |

Event weekdays: 12 / 25 / 31. Placebo-null SD of β: 6–11% for the main outcomes.

**FOUND criteria (fed − res and fed level):** (1) train 2018–19 RI CI excludes 0 with 25 event weekdays ✓;
(2) independent post-COVID holdout 2025, same sign, RI CI excludes 0 ✓; (3) BH survives at 10% (21 RI tests;
q ≤ 0.044 for DiD, 0.097 for the 2025 level) ✓; (4) basis: the event *is* the settlement (OPM notice at 10:00 ET),
so on full lapses the event flag agrees with the contract 100% ✓, with a caveat below; (5) the hedge backtest
improves the outcome ✓ (below). 2013 replicates too, and is the biggest effect (full lapse, 16 days).

**Placebos and falsification:**
- *Fake dates:* the real β sits outside the RI null (above).
- *Pre-trend:* the 14-day leads on DiD are +1.1% (2018) and −4.0% (2025), both ns. 2013 shows −6.5%, inside the
  RI null.
- *Residential:* no loss (−1.4%, +7.2%, ns). In 2013 residential stations *gained* 18%: furloughed workers riding
  near home. So part of the DiD is substitution, and the **level** is the number that matters for a downtown lunch
  spot.
- *Weekends:* 2018–19 and 2025 show 0 to −9% (ns), against −15 to −25% on weekdays, which passes. 2013 fails this
  one (weekend −41 to −47%). In 2013 the Park Service barricaded the Mall and memorials, so a tourist channel hit
  the fed stations next to the Mall (the Mall stations fell 29%).
- *Dose:* the K St private-office district shows nothing in any shutdown. The 2018–19 partial lapse (~25% of
  funding; HHS, Education and Labor stayed open) gives about half the 2025 full-lapse DiD (−15% vs −25%).

**Fragile spec:** spec A (year-month FE) is unreliable here, because a 43-day lapse absorbs whole month FEs. It
gives 2025 fed level −9% (ns) and residential +40%; for 2018–19 it gives DiD +4.7% (ns) and residential −28%.
Treat spec B as the result. This is the "careful" case the brief flagged.

### Basis risk: partial lapses settle YES too
Kalshi KXGOVTSHUTDOWN / KXGOVTSHUTLENGTH count "at least partially shut down". The **DHS-only lapse of
2026-02-14..04-30** (76 days, ICE / TSA / CBP / FEMA; most staff excepted, and HQ is at St Elizabeths, outside every
cluster) settled those contracts YES. Downtown showed: DiD −3.7% [−10.7, +1.9], fed level −5.9% [−18.2, +4.9]
(RI over 33 windows in 2023–25 springs, results_dhs.csv). That is ~0. A business holding "shutdown on Feb 14" YES
got paid without a loss, which was a windfall here, but it means the contract is not a clean proxy. The KXGOVSHUT
(OPM-notice) and KXGOVTSHUTDOWN contracts do not distinguish a DHS-only lapse from a full one.

## Hedge (hedge.py)

**Sizing:** downtown lunch spot, $4,000 per weekday (~$1M/yr). It loses the mean of the two independent fed-level
estimates, **17.4% per shutdown weekday ≈ $698** (≈ $498 per calendar day). Pass-through from bikeshare touches to
restaurant revenue is assumed to be 1; it is untested, because there are no DC Dewey venues. The 2025 loss
(29 working weekdays) ≈ **$20.2k**.

**2025 backtest at real Kalshi asks + fee 0.07·p(1−p):**

| bought | hedge | cost | payoff | net outcome (unhedged −$20.2k) |
|---|---|---|---|---|
| Sep 10 | binary 10.5k × "shutdown" (sized to a 21-day lapse) @0.59 | $6.4k | $10.5k | −$16.1k |
| Sep 10 | **duration strip** 0/3/5/10/35D @0.59/0.38/0.30/0.19/0.10 ($498 per day, capped at 45 d) | $5.1k | $22.4k | **−$2.9k** |
| Sep 22 | strip | $8.5k | $22.4k | −$6.3k |
| Sep 30 | binary @0.78 | $8.3k | $10.5k | −$18.1k |
| Sep 30 | strip @0.83/0.69/0.59/0.34/0.21 | $9.0k | $22.4k | −$6.8k |
| Oct 1 (day 1) | strip 3/5/10/35D @0.84/0.70/0.45/0.19 | $11.0k | $28.4k | −$2.8k |
| Oct 11 (day 11) | strip 11–40D @0.93…0.30 | $13.3k | $24.4k | −$9.1k |

The loss is linear in duration, so the **duration strip** ("lasts > N days" at each strike, one contract per day ×
$ per day) is the right instrument; the binary under-covers a long lapse.

**Every deadline since 2021, at real prices** (one contract per funding fight, 13–14 fights, N = 10.5k binary
contracts; deadline_prices.csv): bought 7 days before, cost $33.6k, payoff $31.4k (2025, Jan 2026, and the DHS
windfall). The net outcome was −$23.9k against −$21.6k unhedged. Bought 2 days before: −$32.0k. **The rolling binary
program lost money.** The Sept 2023 near-miss cost $0.76–0.89 a contract, and the market priced the last-minute
saves well. In this sample, protection only paid because of 2025 plus the DHS windfall.

**Simulation** (hedge_sim.csv; 200k draws of one deadline; P(shutdown) ∈ {0.1, 0.3, 0.5, 0.8}; lognormal duration
with median 7 / 21 / 40 days; 5% quarterly revenue noise; priced at fair + $0.02 + fee): the strip cuts quarterly
revenue SD by **1–6% when the median lapse is 7 days, 8–23% at 21 days and 15–32% at 40 days**. It raises the 5th
percentile by up to $13k and costs $630–1,050 per deadline in expected value. The binary cuts SD by 1–20%.

**When to buy:** Kalshi prices track public negotiations closely. "Shutdown in 2025" was 0.37 on Aug 1, 0.49 on
Sep 2, 0.53 on Sep 10, 0.61 on Sep 16 (House CR week), 0.71 on Sep 22 and 0.82 on Sep 30. So **the occurrence leg
has to be bought by early September**, before the House and Senate CR votes. The **duration leg stays cheap into the
shutdown**: ">35 days" was 0.10 on Sep 10, 0.21 on Sep 30, 0.19 on Oct 1 and 0.17 on Oct 8, then repriced to 0.50 on
Oct 15 and 0.72 on Oct 22. Length information only arrives once the lapse has started, so a business can buy the
duration ladder in the first ~week of a shutdown at near pre-deadline prices. Right now (Oct 24 2026),
KXGOVTSHUTDOWN-26DEC12 is ~0.34.

## Verdict

**FOUND (the exposure).** Federal shutdowns cut weekday Capital Bikeshare activity at federal-cluster stations by
**15% (2018–19 partial) and 20% (2025 full)** in level, and by 15% / 25% relative to residential stations. Both
replicate on independent pre- and post-COVID samples under randomization inference and survive BH. The placebos
behave: residential, K St and weekends show no loss for 2018/2025, and the effect is larger for a full lapse than a
partial one. It is the first FOUND in this project where the event *is* the Kalshi settlement.
Caveats: (i) n = 3 events; (ii) bikeshare is a proxy for downtown presence, and restaurant pass-through is assumed;
(iii) the 2025 lunch-hour *level* is ns (−6%), and the lunch effect shows up only relative to residential;
(iv) 2013 fails the weekend placebo (Mall closure); (v) partial lapses (DHS 2026) settle contracts YES with no
downtown effect.
**Hedge:** a duration strip bought before the deadline turned a −$20k 2025 loss into −$3k to −$7k. But a rolling
"buy before every deadline" binary program lost money over 2021–26. The hedge is worth it in fights where the
market price is below the business's own odds, and the duration leg is the better buy.

Tests run: 108 HAC shutdown coefficients across 18 outcome × day-type combos × 2 specs × 2 samples (BH family 72),
33 RI tests (BH family 21), 51 same-date fake placebos, 4 DHS-lapse fits, the 2025 backtest (14 variants), a
13–14-deadline program and a 36-cell simulation.

Reproduce (from backend/): `fetch_kalshi.py`, then `build.py` (needs the zips in r2-cache/r8dc_cabi/; the
S3 URL pattern is in the brief), then `run.py`, then `hedge.py`. Outputs: results.csv, results_ri.csv, results_dhs.csv,
placebo_fake_dates.csv, hedge_2025.csv, prices_2025.csv, deadline_prices.csv, hedge_sim.csv.

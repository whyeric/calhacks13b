# Pitch: 2-minute demo script and Devpost draft

This page is for the presenters and for whoever submits the Devpost entry. The submission itself
is a human task (issue #42, C8-H9 to H15), so this file holds draft text only. Run the demo on
`make demo`, which serves offline from the committed cache (`DEMO_OFFLINE=1`). Every number below
comes from that build, from [RESEARCH.md](RESEARCH.md), or from a cited source. Re-read the
numbers on screen before each rehearsal, because the cache can be re-warmed.

## Public naming

- Our private-data business is always **"a bar across from MSG"**. Never use its name, address or
  a screenshot of raw Dewey rows (C8-H10).
- **The Jeffrey** is a *different* NYC bar whose Kalshi hedge was public news. We cite it as
  context. It is not our data.

## The story in one breath

Small businesses already want this: in June 2026, a NYC bar hedged a Knicks promotion on Kalshi.
But most "obvious" event risk is noise. Hedge Desk measures the risk, checks that it replicates on
data it never saw, and **declines** when it doesn't. For a bar near MSG, the risk that holds up is
**playoff home games**, which Kalshi's playoff-advancement contracts settle on exactly. And when
the books come back, reconciliation catches the one deposit that's short. And here's what the
same protocol finds on a bike shop's revenue: rain, cold and warm days are real, and Knicks games
aren't.

---

## 2-minute script

Each beat follows spec §14, with the narrative above. Use the stopwatch windows (C8-H1 to H5). In
the first minute say "insurance for a single Saturday", never "hedge ratio" or "basis risk" (C8-H6).

**Before you start:** have `~/Downloads/hudson_bike_co_daily_revenue.csv` ready (it's also in
`frontend/public/samples/`). The research report is **computed live** by `POST /research` on
whatever file you upload. The hedge card behind "Send to the desk" has a scripted market and 33¢
price, labeled on the card, but is **sized from the live report**. `POST /research/quote` prices the
same row live on the cached Kalshi and Polymarket books (API only for now). The uploaded business
isn't saved.

### 0:00–0:10 · The hook: owners already want this

> "This June, a New York bar bought about $5,000 of Kalshi contracts so a free-tab Knicks promotion
> couldn't sink it.¹ Owners want insurance for a single night. The hard part is knowing which
> nights are actually risky."

*Screen:* the dashboard, taxi fleet selected ("real" label in the header).

### 0:10–0:35 · The moment it says no

*Click **Run desk** on taxi.* The rain exposure is ≈ +$2,080 a day with its 90% bar; game results
land under **"measured, not hedged: not significant"**. The rain card comes back **declined**, with
`no_market` and `unstable` on screen.

> "A real taxi zone outside Madison Square Garden. Rain looked like +$2,080 a day last year.
> Refit on recent months, it's +$228, and the interval crosses zero, so the desk says no. Insurance
> against noise is a bet."

### 0:35–1:15 · A bike shop's revenue: what the protocol finds (the judge moment)

*Click **Upload your revenue*** and choose `hudson_bike_co_daily_revenue.csv`. The app reads the
file and shows 1,004 days, 2024 to September 2026.

> "Here's what our research protocol finds on a bike shop's revenue. Hudson Bike Co. is a
> fictional shop, with synthetic sales on real Central Park weather."

*Click **Upload and research**.* The research runs live on the file in about a second, then the
report appears with each risk's mechanism written above its numbers.

> "The mechanism is written down before anything is tested: rain keeps riders home. Then every
> idea gets the same protocol: fit on 2024, check on 2025 and 2026 separately, correct for how
> many things we tried, and test a fake rain a week later that must find nothing."

*The report (computed live on the file).* Rain is **FOUND**: −18.2% (−$1,923.43 a day) on 2024,
and −20.4% on the unseen 2025–26 data, with the placebo quiet (p 0.29). Cold days (−26.5% / −26.4%) and warm days
(+10.9% / +15.5%, an upside) are FOUND too. Hot days over 90 °F, Knicks home games and Knicks wins
are not distinguishable from zero.

> "Rain costs this shop about $1,923 a day, and it held on data the model never saw. Knicks
> games? Nothing, so we won't sell insurance on them."

*Click **Send to the desk** on rain.* The card is sized from the report: contracts = the measured
daily rain loss ÷ $1, rounded down, so it never buys more than the exposure (I1), and the premium
is contracts × the card's 33¢ plus Kalshi's fee. On the sample that is **1,923 YES for $664.36**.
The market and price are scripted and labeled. The live quote (`POST /research/quote`, API) finds
1,923 YES on `KXRAIN-26OCT25-NYC` for $20.57 on the cached books; if asked why so cheap, the
market prices tomorrow's dry forecast, and rule 3 never counts that as a bargain.

> "That's insurance for a rainy day, sized to the measured loss and no more. The owner decides."

### 1:15–1:40 · The receipt

*Switch to the ledger tab, then click **Reconcile**.*

> "Every approval is booked to a real double-entry ledger. At settlement, the desk lines up three
> records: its own books, Kalshi's payouts and the bank. It finds one deposit $0.89 short. That's
> exactly the Kalshi fee, so it asks the owner instead of guessing."

### 1:40–2:00 · Proof, and what's real

*Open **Model check**:* a planted $500 effect is recovered, and the 90% CI contains it in 96% of
50 seeds.

> "We ran this same protocol by hand across 40 experiments. Game *results* never replicated. For a
> bar across from MSG, what holds is playoff home games: +5.7%, both times, and Kalshi's series
> contracts settle on exactly that. Hedge Desk: measure, replicate, and say no when the honest
> answer is no."

**If something breaks:**
- **API down:** each region degrades with a Retry button (C7-H12).
- **The wrong file is picked:** the report still runs live on it; for the planned beat, choose
  `hudson_bike_co_daily_revenue.csv` again. A file outside 2024-01 to 2026-09 or under 540 days
  gets a plain error instead of a report.
- **Asked "is it running live?":** the report is: "Upload any NYC daily revenue CSV and it runs
  the protocol on it now." The hedge card after Send is a labeled example; pricing it from the
  report is next.
- **Backtest panel shows "not ready":** `make seed` stores it. Otherwise say the model-check line
  and move on.

¹ Semafor, ["Hedging a $15,000 New York Knicks bar tab on Kalshi"](https://semafor.com/article/06/02/2026/hedging-a-15000-new-york-knicks-bar-tab-on-kalshi) (2026-06-02); Covers, ["NYC Bar Uses Kalshi Hedge to Promise Free Tabs if Knicks Win Game 1"](https://www.covers.com/industry/nyc-bar-uses-kalshi-hedge-to-promise-free-tabs-if-knicks-win-game-1-june-2-2026). Kalshi itself approached the owner and promoted the trade, so call it a sign of demand, not proof of a market.

**What was cut to fit two minutes:** the bar's Settings budget flip (a pending playoff leg turns
proposed) and the separate bar switch. The research beat replaces both as the judge moment, and
the playoff finding survives as one line in the close. If a judge asks, the bar flow still works
(it needs the Dewey files; see the known gaps).

### Known gaps to rehearse around (as of this branch)

- **The upload → research report and the quote are live**; the quote reads the committed Kalshi
  and Polymarket caches (pinned demo clock), so its prices are the 2026-10-24/25 snapshots. It's a
  quote, not a proposal: no approve button for an uploaded business.
- On the committed cache, the real taxi desk gives one **declined** rain hedge (`no_market` +
  `unstable`).
- With the Dewey files, the bar's real run is the playoff season hedge: one leg **proposed**
  within budget (title, $78.51) and two **pending** over budget. Without them the bar shows
  "analysis unavailable" and its labeled sample week.
- Hudson Bike Co. is **fictional**, with synthetic revenue and planted effects, on real weather.
  Say "a fictional bike shop" on stage, never "a real bike shop".
- The backtest is stored by `make seed`. Taxi's real backtest is honest and flat (hedged SD about
  equal to unhedged, reduction −0.1%), so lead with the model check, not the backtest strip.

---

## Real, estimated, simulated

Use this in the Devpost and say it out loud if asked (C8-H9):

- **Real:**
  - taxi fares: NYC TLC trip records, zone 186, Penn Station/Madison Sq West;
  - weather;
  - Knicks and Rangers schedules and results;
  - Kalshi markets, prices and order books (public API, cached for offline judging);
  - the restaurant's foot traffic: Dewey / Advan daily visits, used as aggregates only.
- **Estimated:** the bar's **dollars**. They are visits × an **assumed $35 average check**, and
  are labeled "estimated" and "assumed" in the UI.
- **Synthetic, on real weather:** Hudson Bike Co. (`hudson_bike_co_daily_revenue.csv`) is a
  fictional shop. Its revenue is generated with planted effects, keyed to real NOAA Central Park
  weather days.
- **Live:** the upload → research report: `POST /research` runs the protocol on the uploaded
  file (nothing stored).
- **Live quote:** the hedge card behind "Send to the desk" (`POST /research/quote`), priced on
  the cached Kalshi and Polymarket books; not saved, so not approvable.
- **Simulated:** the hedge settlements and the bank statement. The settlements are simulated from
  *real* settled Kalshi results. The bank statement has one deliberately planted short deposit.
  **No real trades are placed.**
- **Research claims:** these come from the experiment folders in [RESEARCH.md](RESEARCH.md). Any
  dollar figure for a bar there also rests on assumed covers and an assumed check.

---

## Track pitches (spec §17)

**Hyphenate (primary).** "The treasury analyst who finds and hedges a business's event risk, and
the bookkeeper who records, reconciles and closes it." Seats line for the form: *Treasury analyst
+ hedge bookkeeper for a small business, under the owner's approval and the controller's
co-sign.* Show, on screen:
- limits and approvals: a pending card that only the owner can approve (I4), and, above the
  $200 materiality line, only after the controller co-signs. The controller can't approve, the
  owner can't co-sign or move materiality, the desk can do neither; every refusal is logged;
- "defend a decision when questioned": **Challenge this decision** opens the receipt (every
  check against its threshold, the exposure, the sources, the full trail);
- time: the desk remembers. Two rejected rain hedges in a row and the next proposal opens with
  "You rejected the last two rain hedges (last reason: …)";
- the close: the controller locks the books through a date; the $0.89 short deposit blocks it
  until it's acknowledged and carried as an exception;
- two venues: the desk scans Kalshi and Polymarket, and skips Polymarket's NYC temperature
  markets because they settle at LaGuardia, not the Central Park station it measured;
- the append-only decision log, with the checks behind every decision;
- the Beancount ledger;
- sources that disagree: rule 4's basis check between our weather and the settlement station;
- two planted errors with answer keys: the $500 in the model check and the $0.89 short deposit.
- the planted-error benchmark on the Books tab: a simulated world of 26 hedges with 17 planted
  errors across three sources, venue, ledger and bank (fee netted, duplicate deposit incl. one
  split across two rows, transposed digits, reversed sign, missing deposit past the window,
  wrong ledger payout, venue paid less than we booked, venue fee differs from ours, short
  deposit, unexplained bank rows) and 7 traps that look wrong but aren't (split deposit, late
  deposit, unreferenced deposit two days late, two expired hedges, and two deposits in transit
  that must be reported as timing, not error). Each mismatch names the source of record (venue
  for what was paid, bank for cash, ledger for what we booked) and why.
  The real reconciler catches **17 of 17 with the right cause and 0 false flags**. Say "on
  simulated data with an answer key"; the old exact-date matcher would have false-flagged a trap,
  and a test proves the key can fail.

**Microsoft: Built for the Real World.**
- *Customer:* a taxi fleet and a bar near MSG.
- *Usefulness:* measured, with a model check and holdout replication; the backtest strip once it's
  wired.
- *Responsible design:* it never over-insures, with contracts ≤ measured exposure ÷ $1 shown on
  every card (I1). It declines, with reasons, when the risk isn't real.
- *Path to production:* owners connect their point-of-sale or bank feed in place of our public
  proxies.

**Anthropic: Claude for Public Benefit.**
- *Community:* small-business owners whose income rides on weather and game days.
- Claude chooses markets and explains decisions. It **never produces a number**: every figure is
  validated against tool results before it's logged, and the "why?" chat answers from those same
  checks.
- An owner without an analyst gets the protocol an analyst would use, shown on a bike shop's
  revenue: replication, multiple-testing correction and a placebo, run live on whatever daily
  revenue file the owner uploads (nothing is stored).
- If Claude is slow or down, a deterministic fallback runs, marked `agent: fallback`.

**General:** Overall; Most Technically Complex. Check the Devpost form's limit on sponsor tracks
(C8-H15).

---

## Devpost draft

**Tagline:** The treasury seat a small business can't afford: it measures event risk, insures
only what's real, and says no when it isn't.

**Inspiration.** In June 2026, a New York bar bought Kalshi contracts so that a "free tab if the
Knicks win" promotion couldn't sink it. Small businesses clearly want insurance for a single night.
But which nights are actually risky? A rainy Saturday? A Knicks loss? We wanted a desk that answers
with data, and declines when the data says no.

**What it does.** Hedge Desk reads a business's daily revenue and measures, in dollars and with
confidence intervals, how much each event moves it. The events are rain, heat, game days and game
results. It looks for a live Kalshi contract that settles on that event, sizes protection so it
never exceeds the measured exposure, and runs six decline rules: no market, illiquid, overpriced,
loose basis, too expensive, over budget. Then it proposes the hedge to the owner, who decides.
Approved hedges are booked to a Beancount ledger and reconciled three ways at settlement: our
books, Kalshi's payouts and the bank. Every proposal, decline, approval and booking goes into an
append-only decision log, with the numbers that justified it.

**Research on an owner's own revenue.** The protocol we used for our own research runs on any
business's daily revenue. The demo shows it on Hudson Bike Co., a fictional bike shop with
synthetic sales on real Central Park weather. The mechanism is written down before any test runs.
The protocol is the same for every hypothesis:
- year-month fixed effects;
- a 2024 train fit and an independent 2025–26 holdout fit;
- Benjamini–Hochberg across the run;
- a placebo that shifts the event a week;
- weather from NOAA's Central Park station, the same station Kalshi's NYC contracts settle on.

On the bike shop, rain is FOUND: −18.2% (−$1,923.43 a day) on 2024 and −20.4% on the unseen data,
with the placebo quiet. Cold and warm days are FOUND too, and Knicks games and wins aren't. The
rain risk becomes a `KXRAIN` (NYC) hedge sized to the measured loss: contracts = the daily rain
loss ÷ $1, premium = contracts × price + Kalshi's fee (1,923 YES at 33¢, $664.36, on the sample).
The report is computed live by `POST /research` on the uploaded file. The card's market and price
are still a labeled example; pricing it through the live quote in the UI (and Claude choosing the
hypotheses) is next.

We demo two businesses around Madison Square Garden: a taxi fleet (real NYC trip records) and a
bar across from MSG (real foot traffic, estimated dollars), plus the live research protocol on an
uploaded file, shown on a fictional, labeled bike shop.

**How we built it.**
- *Backend:* Python 3.12 and FastAPI. DuckDB, pandas and statsmodels fit the exposures, with a
  planted-effect model check. A Kalshi client has an offline cache, so the whole demo runs with
  no network.
- *Agent:* the Anthropic SDK in a tool-use loop. A validator rejects any summary containing a
  number that didn't come from a tool. A deterministic fallback takes over when Claude isn't
  available.
- *Research:* `POST /research` runs the protocol (statsmodels, HC3, BH, placebo) on an uploaded
  CSV in about a second, and `POST /research/quote` prices a FOUND downside on Kalshi and
  Polymarket with the desk's own sizing and decline rules.
- *Books:* Beancount and SQLite.
- *Frontend:* Next.js, Tailwind, Recharts and SWR.
- *Research:* eight rounds of experiments, about 40 studies, with train/holdout replication,
  Benjamini–Hochberg correction, placebos, and the actual NOAA settlement station. RESEARCH.md §5 shows
  the same protocol on the bike shop.

**Challenges.** The honest answer kept being "no". The taxi rain effect is significant on a
year of data, then shrinks to almost nothing on the next. Game results never moved foot traffic,
across 358 venues. We had to build a product whose best moment is a decline. We also learned
that weather reanalysis disagrees with the Central Park station record about one day in eight,
which is enough to misprice a contract.

**Accomplishments.**
- A research protocol that, on a bike shop's revenue, recovers the three planted weather effects
  and rejects the game hypotheses.
- A desk that turns down its own hedge and shows its receipts.
- Every on-screen figure is traceable to a tool call.
- Reconciliation that catches a $0.89 short deposit and names the cause.
- A research appendix that publishes the nulls along with the hits.

**What we learned.** Hedge game *dates* and *elimination*, not game *results*: playoff home
nights lift foot traffic near MSG by about 5.7%, and that replicated. Daily weather insurance
moves a single business's variance by well under 1%. Concentrated, settleable shocks are where
event contracts can really help. Our examples are a government shutdown (for a lunch spot near
federal offices), heat (for a fixed-rate power bill) and playoff home-game counts.

**What's next.**
- A live upload and research API: any owner's CSV, with Claude pre-registering the hypotheses and
  the harness deciding what's real.
- Research beyond NYC: more settlement stations and teams.
- Owners connecting their point-of-sale or bank feeds instead of uploading a CSV.
- Randomization-inference placebos in the harness, as in our hand research.
- Playoff advancement hedges in the desk itself.

**Real vs. estimated:** paste the "Real, estimated, simulated" section above.

**Built with:** python, fastapi, duckdb, pandas, statsmodels, anthropic, claude, beancount,
sqlite, next.js, react, tailwind, recharts, kalshi-api, nyc-tlc, dewey-advan, noaa.

**Data attribution:** foot-traffic data from Advan via Dewey, used under its academic license as
aggregates only. NYC TLC trip records. NOAA GHCN and Open-Meteo weather. Kalshi public market
data.

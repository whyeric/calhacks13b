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
the books come back, reconciliation catches the one deposit that's short. And it works on *your*
business: upload your daily revenue, and Claude pre-registers what should matter while a fixed
harness decides what actually does.

---

## 2-minute script

Each beat follows spec §14, with the narrative above. Use the stopwatch windows (C8-H1 to H5). In
the first minute say "insurance for a single Saturday", never "hedge ratio" or "basis risk" (C8-H6).
Placeholders marked *fill in after integration* depend on the upload and research features. Read
the real values off a rehearsal run on `make demo` and paste them in; never improvise them on stage.

**Before you start:** have `sample_revenue_nyc_bike_shop.csv` downloaded (from the upload drawer
or `GET /samples/sample_revenue_nyc_bike_shop.csv`), and start from a db with no uploaded
businesses.

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

### 0:35–1:15 · Your business: upload, research, send to the desk (the judge moment)

*Click **Upload your revenue**.* Name "a bike shop", type **shop**, file
`sample_revenue_nyc_bike_shop.csv`. The app switches to it, with an **Uploaded** badge.

> "Now it's your business. Drop in a year and a half or more of daily sales. This one's a synthetic
> bike shop, and it never leaves this laptop."

*Click **Research my risks**.* Talk over the run while it polls; when the report lands, point at the
mechanism column.

> "Claude does the analyst's job. It picks the risks that fit a bike shop and writes down *why*
> before anything is tested. Then a fixed harness tests each one: the first year, the later months
> separately, a correction for trying many things, and a fake rain a week later that must find
> nothing."

*The report lands.* Rain is **FOUND**: train *[fill in after integration: $/day and CI]* → holdout
*[fill in after integration]*, placebo quiet. The other rows show NOT_FOUND with plain reasons
(*[fill in after integration: e.g. which rows show did_not_replicate / failed_bh]*).

> "Rain came back, and it replicated on data it never saw. The others didn't, and it tells you
> why. Claude wrote every sentence here, and the harness produced every number."

*Click **Send to the desk** on the rain row, then **Run desk**.* The desk prices a **KXRAIN** hedge:
*[fill in after integration: proposed/pending, contracts, cost]*, with contracts ≤ measured
exposure ÷ $1 on the card and the payoff table ("Unhedged swing / hedged swing / cost"). The owner
sees **Approve**, and only the owner can press it.

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
- **Upload rejected** (a 422 shows inline): use the sample file exactly as downloaded, with type
  `shop`.
- **Research is slow with Claude** (the run is still `queued`/`running` after about 15 s): keep
  talking over the mechanisms, or rehearse with no key, which runs the deterministic fallback
  (`agent: fallback`) and finishes faster. *Fill in after integration: typical run time with and
  without a key.*
- **Rain isn't FOUND on the sample:** say "and here it would have said no", show the reasons, and
  skip to the receipt. Don't re-run research hoping for a different answer.
- **The desk declines the promoted rain hedge** (`no_market` on the committed cache, see below):
  that's an honest outcome. Say "it found the risk, but there's no rain contract listed this
  week, so it won't sell you one", and move on.
- **Backtest panel shows "not ready":** `make seed` stores it. Otherwise say the model-check line
  and move on.

¹ Semafor, ["Hedging a $15,000 New York Knicks bar tab on Kalshi"](https://semafor.com/article/06/02/2026/hedging-a-15000-new-york-knicks-bar-tab-on-kalshi) (2026-06-02); Covers, ["NYC Bar Uses Kalshi Hedge to Promise Free Tabs if Knicks Win Game 1"](https://www.covers.com/industry/nyc-bar-uses-kalshi-hedge-to-promise-free-tabs-if-knicks-win-game-1-june-2-2026). Kalshi itself approached the owner and promoted the trade, so call it a sign of demand, not proof of a market.

**What was cut to fit two minutes:** the bar's Settings budget flip (a pending playoff leg turns
proposed) and the separate bar switch. The research beat replaces both as the judge moment, and
the playoff finding survives as one line in the close. If a judge asks, the bar flow still works
(it needs the Dewey files; see the known gaps).

### Known gaps to rehearse around (as of this branch)

- **The KXRAIN pricing beat depends on the cache.** `make demo` pins the clock to the cached week
  (`DEMO_AS_OF=2026-10-24T19:00:00Z`, desk week Mon Oct 26), and the committed cache has **no NYC
  rain market for a day inside that week**. That's why taxi's rain declines with `no_market`. A
  promoted bike-shop rain exposure will most likely decline the same way unless the cache is
  re-warmed while a `KXRAIN` market inside the desk week is listed (docs/DEMO.md). *Fill in after
  integration: the actual desk outcome for the promoted rain exposure on the demo cache.* Decide
  before the demo whether to re-warm or to pitch the decline line above.
- On the committed cache, the real taxi desk gives one **declined** rain hedge (`no_market` +
  `unstable`).
- With the Dewey files, the bar's real run is the playoff season hedge: one leg **proposed**
  within budget (title, $78.51) and two **pending** over budget. Without them the bar shows
  "analysis unavailable" and its labeled sample week.
- The bike-shop CSV is **synthetic** with planted effects. Say "a synthetic bike shop" on stage,
  never "a real bike shop".
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
- **Synthetic:** the two sample revenue CSVs (`sample_revenue_nyc_bike_shop.csv`,
  `sample_revenue_msg_sports_bar.csv`), seeded with planted effects. The bike shop on stage is one
  of them.
- **Yours:** an uploaded business's revenue. It's stored in local SQLite only and never sent to
  Kalshi.
- **Simulated:** the hedge settlements and the bank statement. The settlements are simulated from
  *real* settled Kalshi results. The bank statement has one deliberately planted short deposit.
  **No real trades are placed.**
- **Research claims:** these come from the experiment folders in [RESEARCH.md](RESEARCH.md). Any
  dollar figure for a bar there also rests on assumed covers and an assumed check.

---

## Track pitches (spec §17)

**Hyphenate (primary).** "The treasury analyst who finds and hedges a business's event risk, and
the bookkeeper who records and reconciles it." Show, on screen:
- limits and approvals: a pending card that only the owner can approve (I4);
- the append-only decision log, with the checks behind every decision;
- the Beancount ledger;
- sources that disagree: rule 4's basis check between our weather and the settlement station;
- two planted errors with answer keys: the $500 in the model check and the $0.89 short deposit.

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
- Claude does the analyst's work: it pre-registers mechanisms for an owner's own business, chooses
  markets and explains every verdict and decision in plain language. It **never produces a
  number**. Every figure comes from the harness or a tool and is validated before it's logged, and
  the "why?" chat answers from those same checks.
- An owner without an analyst gets the protocol an analyst would use: replication, multiple-testing
  correction and a placebo, on their own data, on their own machine.
- If Claude is slow or down, a deterministic fallback runs, marked `agent: fallback`.

**General:** Overall; Most Technically Complex. Check the Devpost form's limit on sponsor tracks
(C8-H15).

---

## Devpost draft

**Tagline:** An AI analyst for a small business's event risk: Claude proposes the hypotheses, a
fixed harness decides what's real, and the desk insures only that, saying no when it isn't.

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

**The core innovation is an agentic research loop on the owner's own data.** An owner uploads a
daily revenue CSV and clicks **Research my risks**. Claude does the analyst's work: it reads the
business type, picks the events from a catalog of Kalshi-settleable risks that plausibly matter
(rain, heat, cold, snow, home games, wins, playoff nights), and **pre-registers a mechanism for
each before any test runs**. A fixed harness then tests every hypothesis the same way: year-month
fixed effects, a first-year train fit and an independent holdout fit, Benjamini–Hochberg across
the whole run, and a placebo that shifts the event a week, all against the NOAA Central Park
station Kalshi settles on. A risk is FOUND only if it clears every check. Claude then explains each
verdict in plain language, **but it never produces a number**: every effect, interval and p-value
comes from the harness, and a validator rejects any text with a number that didn't. FOUND risks
with a Kalshi contract go to the desk with one click, and the desk prices the hedge under the same
decline rules. The revenue never leaves the owner's machine.

We demo two businesses around Madison Square Garden: a taxi fleet (real NYC trip records) and a
bar across from MSG (real foot traffic, estimated dollars), plus an uploaded bike shop (synthetic
sample data, labeled).

**How we built it.**
- *Backend:* Python 3.12 and FastAPI. DuckDB, pandas and statsmodels fit the exposures, with a
  planted-effect model check. A Kalshi client has an offline cache, so the whole demo runs with
  no network.
- *Agents:* the Anthropic SDK in two tool-use loops. The **desk** agent finds markets and
  explains decisions. The **research** agent calls `list_candidate_events`, `get_business` and
  `run_hypothesis(event_id, mechanism)`. It has to state the mechanism in the call that runs the
  test, and the code, not Claude, applies BH and the final verdicts. A validator rejects any summary
  containing a number that didn't come from a tool. A deterministic fallback takes over when Claude
  isn't available.
- *Uploads:* a forgiving CSV parser (`Date`/`sales`/`$1,234.50`), stored in SQLite only, feeding
  the same feature table as the built-in businesses.
- *Books:* Beancount and SQLite.
- *Frontend:* Next.js, Tailwind, Recharts and SWR.
- *Research:* eight rounds of experiments, about 40 studies, with train/holdout replication,
  Benjamini–Hochberg correction, placebos, and the actual NOAA settlement station. The research
  loop productizes that protocol (RESEARCH.md §5).

**Challenges.** The honest answer kept being "no". The taxi rain effect is significant on a
year of data, then shrinks to almost nothing on the next. Game results never moved foot traffic,
across 358 venues. We had to build a product whose best moment is a decline. Turning our hand protocol into a loop
an agent drives meant fencing Claude off from every degree of freedom we'd used to fool ourselves:
the split, the specification, the thresholds and the option to retry. We also learned
that weather reanalysis disagrees with the station Kalshi settles on about one day in eight,
which is enough to misprice a contract.

**Accomplishments.**
- An agent that does real analyst work on a stranger's data (pre-registration, replication,
  multiple-testing correction, placebo) without ever being the source of a number.
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
- Research beyond NYC: more settlement stations and teams, so an upload outside New York means
  something.
- Owners connecting their point-of-sale or bank feeds instead of uploading a CSV.
- Randomization-inference placebos in the harness, as in our hand research.
- Playoff advancement hedges in the desk itself.

**Real vs. estimated:** paste the "Real, estimated, simulated" section above.

**Built with:** python, fastapi, duckdb, pandas, statsmodels, anthropic, claude, beancount,
sqlite, next.js, react, tailwind, recharts, kalshi-api, nyc-tlc, dewey-advan, noaa.

**Data attribution:** foot-traffic data from Advan via Dewey, used under its academic license as
aggregates only. NYC TLC trip records. NOAA GHCN and Open-Meteo weather. Kalshi public market
data.

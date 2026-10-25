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
the books come back, reconciliation catches the one deposit that's short.

---

## 2-minute script

Each beat follows spec §14, with the narrative above. Use the stopwatch windows (C8-H1 to H5). In
the first minute say "insurance for a single Saturday", never "hedge ratio" or "basis risk" (C8-H6).

### 0:00–0:15 · The hook: owners already want this

> "This June, a bar in New York promised free tabs if the Knicks won Game 1 of the Finals, and
> bought about $5,000 of Kalshi contracts so the promotion couldn't sink it.¹ Owners want
> insurance for a single night. The hard part is knowing which nights are actually risky."

*Screen:* the dashboard, taxi fleet selected ("real" label in the header).

### 0:15–0:45 · Find the risk, measured and not guessed

> "Hedge Desk reads a business's daily revenue. This is a real taxi zone outside Madison Square
> Garden, from city trip records. It measures each event in dollars, with a confidence bar."

*Click **Run desk**.* Exposures appear: rain ≈ +$2,080 a day with its 90% bar. (That's on a fresh
clone. With the Dewey files built, the MSG-event control changes it to ≈ +$2,245, so read the card.) Knicks/Rangers wins
land under **"measured, not hedged: not significant"**.

> "Rain shows up. Who wins the game doesn't. We tested that across 358 venues and 40 experiments,
> and game *results* never replicated."

### 0:45–1:15 · Protect it (and the moment it says no)

*The rain card:* the real Kalshi market, `KXRAIN` NYC. The desk sized it but **declined** it.

> "Here's the moment. The desk wanted about twelve hundred contracts. The book had zero on the side
> we need, so it said no, and it shows you the numbers: filled 0 of [N]. We also refit this rain effect on
> later data, and it shrank to almost nothing. Most obvious event risk is noise, and a desk that
> sells you insurance against noise is selling you a bet."

*Judge moment:* open **Settings** and drag a threshold. The decision flips in under 10 s, and both
evaluations land in the decision log.

> **If the cache was re-warmed and shows a live proposal** (docs/DEMO.md): show its payoff chart
> instead. Revenue is flat in both outcomes, "Unhedged swing / hedged swing / cost" is on screen,
> and the owner clicks Approve. Only the owner can.

### 1:15–1:40 · The one that's real, and the receipt

> "So what *is* real for a bar across from MSG? Playoff home games. Foot traffic within half a
> kilometre is up 5.7% on playoff nights, and that holds on data the model never saw: +5.7%, both
> times. Kalshi's series and advancement contracts settle on exactly that: how many home games you
> get before you're eliminated. That's the hedge, not who wins on Tuesday."

*Switch to the ledger tab, then click **Reconcile**.*

> "Every approval is booked to a real double-entry ledger. At settlement, the desk lines up three
> records: its own books, Kalshi's payouts and the bank. It finds one deposit $0.89 short. That's
> exactly the Kalshi fee, so it asks the owner instead of guessing."

### 1:40–2:00 · Proof

*Open **Model check**:* a planted $500 effect is recovered, and the 90% CI contains it in 96% of
50 seeds.

*Switch the business to the bar* (label: "estimated", average check "assumed"):

> "Same desk, different business: here rain cuts the *other* way. Claude finds the markets and
> explains each decision, but every number on screen comes from a tool, and the log proves it.
> Hedge Desk: measure, replicate, and say no when the honest answer is no."

**If something breaks:**
- **API down:** each region degrades with a Retry button (C7-H12).
- **No restaurant data** on a fresh clone (the Dewey files are gitignored): the bar shows
  "analysis unavailable". Skip the switch and say "same desk, private data, estimated dollars."
- **Backtest panel shows "not ready":** say the model-check line and move on (see Known gaps).

¹ Semafor, ["Hedging a $15,000 New York Knicks bar tab on Kalshi"](https://semafor.com/article/06/02/2026/hedging-a-15000-new-york-knicks-bar-tab-on-kalshi) (2026-06-02); Covers, ["NYC Bar Uses Kalshi Hedge to Promise Free Tabs if Knicks Win Game 1"](https://www.covers.com/industry/nyc-bar-uses-kalshi-hedge-to-promise-free-tabs-if-knicks-win-game-1-june-2-2026). Kalshi itself approached the owner and promoted the trade, so call it a sign of demand, not proof of a market.

### Known gaps to rehearse around (as of this branch)

- The committed cache gives the real desk one hedge, a **declined** taxi rain hedge (illiquid,
  0 contracts filled). Proposed and pending cards appear only in the labeled **sample week**, until
  a re-warm captures a two-sided book (docs/DEMO.md). The target N is 1,192 on a fresh clone and
  1,307 with the Dewey files built.
- The matched rain market is for **Sun Oct 25**, the day before the desk week (Mon Oct 26)
  starts. Don't call it "this week's" market until the matching is fixed or the cache is
  re-warmed.
- `GET /businesses/{id}/backtest` returns `backtest_not_ready`, because nothing stores the
  backtest yet. That blocks beat 5's "backtest headline" and the "worst week before/after" opener
  until it's wired in.
- The desk doesn't model playoff exposures yet. The playoff finding is research
  ([RESEARCH.md](RESEARCH.md) §2), so present it as research, not as a live card.

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
- Claude chooses markets and explains decisions. It **never produces a number**: every figure is
  validated against tool results before it's logged, and the "why?" chat answers from those
  same checks.
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

We demo two businesses around Madison Square Garden: a taxi fleet (real NYC trip records) and a
bar across from MSG (real foot traffic, estimated dollars).

**How we built it.**
- *Backend:* Python 3.12 and FastAPI. DuckDB, pandas and statsmodels fit the exposures, with a
  planted-effect model check. A Kalshi client has an offline cache, so the whole demo runs with
  no network.
- *Agent:* the Anthropic SDK in a tool-use loop. A validator rejects any summary containing a
  number that didn't come from a tool. A deterministic fallback takes over when Claude isn't
  available.
- *Books:* Beancount and SQLite.
- *Frontend:* Next.js, Tailwind, Recharts and SWR.
- *Research:* eight rounds of experiments, about 40 studies, with train/holdout replication,
  Benjamini–Hochberg correction, placebos, and the actual NOAA settlement station.

**Challenges.** The honest answer kept being "no". The taxi rain effect is significant on a
year of data, then shrinks to almost nothing on the next. Game results never moved foot traffic,
across 358 venues. We had to build a product whose best moment is a decline. We also learned
that weather reanalysis disagrees with the station Kalshi settles on about one day in eight,
which is enough to misprice a contract.

**Accomplishments.**
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
- Playoff advancement hedges in the desk itself.
- An "unstable" decline rule that refits on recent data.
- Settlement-station weather for features.
- Owners connecting their real point-of-sale or bank feeds.

**Real vs. estimated:** paste the "Real, estimated, simulated" section above.

**Built with:** python, fastapi, duckdb, pandas, statsmodels, anthropic, claude, beancount,
sqlite, next.js, react, tailwind, recharts, kalshi-api, nyc-tlc, dewey-advan, noaa.

**Data attribution:** foot-traffic data from Advan via Dewey, used under its academic license as
aggregates only. NYC TLC trip records. NOAA GHCN and Open-Meteo weather. Kalshi public market
data.

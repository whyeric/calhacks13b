# Upload your revenue, then research your risks

Hedge Desk ships with two demo businesses. The "upload your revenue → research my risks → send to
the desk" flow runs the research protocol **live** on a business's own daily revenue. The drawer
offers one example file, **Hudson Bike Co.**, a fictional NYC bike-rental shop, but any CSV in the
right shape works.


> **What's live and what isn't.** The report is computed live: the browser sends the CSV to
> `POST /research`, the backend runs the protocol (`backend/app/stats/research.py`) and returns
> the report. **Send to the desk** is live too: `POST /research/quote` prices the FOUND downside on
> Kalshi and Polymarket with the desk's own pipeline. Nothing is stored, so the quote has nothing
> to approve or book.

---

## 1. What's live and what isn't

| Part | Status |
|---|---|
| **The sample file** `hudson_bike_co_daily_revenue.csv` | **Synthetic revenue on real weather.** Hudson Bike Co. is fictional. Its daily revenue is generated, but the weather days it reacts to are the **real NOAA Central Park record** (USW00094728, the same Central Park station Kalshi's NYC weather contracts settle on; since 2026-08-14 Kalshi uses The Weather Company's reading there, so NOAA is a close proxy). The file's `#` header lines say so, and the report repeats them ("From your file: …"). |
| The effects planted in the file | About **−20% on rain days, −28% below 40 °F, and +10% above 80 °F** (from the file header). No game effect is planted. |
| The upload | **Live.** The browser reads the row count and date range, then posts the raw CSV to `POST /research`. The backend reads it in memory and stores nothing. |
| The "Running analysis…" bar | Shown for at least 2.5 seconds while the API works (the run itself takes about a second). |
| **The report** | **Live.** Every number is computed by the protocol on the uploaded file. The summary sentence is templated from the verdicts and carries no numbers. |
| "Send to the desk" and the hedge it shows | **Live quote** (`POST /research/quote`): the desk's candidate search on Kalshi and Polymarket, sizing and all decline rules, on the cached books offline. Not saved, so not approvable; nothing is sent to either venue. |

Because the effects were planted, the sample's report is a **recovery check**: does the protocol
find what we put in, and reject what we didn't? It isn't evidence about real bike shops.

---

## 2. Running it

1. `make demo`, then open <http://localhost:3000>.
2. Click **Upload your revenue** and choose a CSV. The sample is in `frontend/public/samples/`, and
   the drawer can load it directly ("Use the sample file").
3. Click **Upload and research** and read the report (§3).
4. On a FOUND rain row, click **Send to the desk** for a live quote on Kalshi and Polymarket.

It works with no network and no API key, like the rest of `make demo`.

### The file

- Two columns, one row per day: `date,revenue` (ISO dates). Headers named `day`/`ds` and
  `sales`/`amount`/`total`/`y` are also accepted; otherwise the first two columns are used.
  `$` and thousands separators are stripped. Lines starting with `#` are notes.
- The weather record covers **2024-01-01 to 2026-09-30**. Days outside it are left out, and so are
  zero-revenue (closed) days; the report counts both.
- At least **540** usable days are needed: one training year plus enough unseen data.

### Privacy

The file goes only to your desk's own API (in the demo, on the same machine), is read in memory and
is never stored or sent to Kalshi.

---

## 3. The protocol, and what it found on Hudson Bike Co.

### The protocol (`backend/app/stats/research.py`)

These are the same rules as the hand research in [RESEARCH.md](RESEARCH.md):

- **Model:** log revenue on day of week, year-month fixed effects, holidays and the event flag,
  HC3 standard errors. `knicks_home` is also controlled when testing a Knicks win.
- **Weather data:** flags come from NOAA Central Park, the Kalshi settlement station.
- **Train:** the file's first year (2024 for the sample).
- **Holdout:** the rest (2025–26), fitted **independently**, with nothing tuned on it.
- **Corrections:** 90% CIs, and Benjamini–Hochberg at 10% across every hypothesis in the run.
- **Placebo:** the same flag shifted 7 days later, which must come back not significant (p ≥ 0.10).
- **Games:** Knicks hypotheses are fitted only on dates the schedule fixture covers
  (2024-10-22 onward), so earlier games aren't miscounted as non-game days.
- **Dollars:** the % effect (exp(b) − 1) times the period's mean daily revenue.
- **FOUND** means all of these hold:
  - at least 10 event days in train;
  - the train interval excludes 0;
  - it survives BH;
  - the placebo is quiet;
  - the holdout has the same sign, with its own interval excluding 0.

The hypotheses and their mechanisms are fixed in code before any file is fitted (pre-registered).
The code, not a model, applies every verdict.

### Results on the sample (live run)

| Hypothesis | Train (2024) | Holdout (2025–26) | Verdict |
|---|---|---|---|
| **Rain** (≥ 0.01 in) | **−18.2%**: −$1,923.43/day, 90% CI −$2,137.76 to −$1,703.67, 125 rain days | **−20.4%**: −$2,488.09/day | **FOUND**. Placebo p = 0.29. Hedgeable. |
| **Cold** (tmax < 40 °F) | **−26.5%** | **−26.4%** | **FOUND** (no daily contract at a fixed strike) |
| **Warm** (tmax > 80 °F) | **+10.9%** | **+15.5%** | **FOUND**, as an upside |
| Hot (tmax > 90 °F) | not distinguishable from zero | | NOT FOUND |
| Knicks home game | not distinguishable from zero | | NOT FOUND |
| Knicks win | not distinguishable from zero | | NOT FOUND |

The protocol recovered all three planted effects close to their planted sizes (−20%, −28%, +10%)
and rejected the hot and game hypotheses (no game effect was planted). The earlier, hardcoded
report came from a separate offline run of the same protocol and differs slightly (rain −18.4%,
−$1,955.68/day on 124 days); that run's exact inputs weren't kept, so the live numbers above are the
reference now. `backend/tests/stats/test_research.py` pins them.

### "Send to the desk": rain

A FOUND rain downside maps to Kalshi's NYC daily rain series `KXRAIN` (markets
`KXRAIN-<date>-NYC`) and to Polymarket's "Where will it rain" NYC market (both settle at Central
Park), so the row offers **Send to the desk**, which calls `POST /research/quote`
(`backend/app/markets/quote.py`):

1. The protocol re-runs on the same CSV, and the quote's exposure is built from its own train fit
   (effect, 90% CI, p-value, event days) with the holdout refit as the `unstable` check's input.
2. Both venues are scanned for the next 8 days; the deepest book within 5¢ on the side we buy is
   picked, and the card lists every market it scanned.
3. Sizing caps contracts at the measured exposure ÷ $1 (I1), and all six decline rules run.
   Rule 4 treats the basis as a full match (the research flags are Central Park days, the station
   both venues settle on), and rule 3's fair price is the train year's rain-day share.

On the sample with the committed caches (pinned demo clock, Sat 2026-10-24), the quote is
**1,923 YES on `KXRAIN-26OCT25-NYC` for $20.57**, proposed with every check passing. Polymarket's
NYC market for the same day was scanned too (YES ask 74¢, 216 shares within 5¢). The low Kalshi
price is the market's forecast for a dry day, not a bargain, so rule 3 never counts it as one.
It's a quote: approval and booking need a saved business.

### Verdict reasons, in plain language

| Reason | Meaning |
|---|---|
| `thin_support` | Fewer than 10 event days in train. |
| `not_significant` | The train interval includes zero. |
| `failed_bh` | It's significant alone, but not after correcting for how many things were tested. |
| `placebo_fired` | The week-shifted fake also "found" something. |
| `did_not_replicate` | It showed up on train but not on the unseen data. |
| `sign_flipped` | The unseen data points the other way. |

A FOUND row that can't be bought shows "no daily contract to buy" instead of a Send button.

---

## 4. The API

**`POST /research?name=<business name>`** — body: the raw CSV (`Content-Type: text/csv`).
Returns `200` with a `ResearchReport` (`backend/app/models.py`, example in
`backend/fixtures/examples/research_report.json`). Stateless: nothing is stored.

Errors are `422` with the usual `{"error": {"code", "message", "detail"}}` body:

| Code | When |
|---|---|
| `bad_csv` | Empty, not UTF-8, over 5 MB, no date/revenue columns, or too many unparseable rows |
| `duplicate_dates` | A date appears twice (`detail.dates`) |
| `negative_revenue` | A negative revenue (`detail.dates`) |
| `out_of_window` | No date overlaps the weather record |
| `too_short` | Fewer than 540 usable days (`detail.days`) |

**`POST /research/quote?hypothesis=rain&name=<business name>`**: same raw CSV body. Returns
`200` with a `ResearchQuote` (`exposure`, `hedge` with its checks, `budget`, `p_hat`, `window`,
`basis_note`; example in `backend/fixtures/examples/research_quote.json`). `409 not_sendable` for
a row with no daily contract (cold, warm, hot, games), `422 unknown_hypothesis` for an id not in
the report, and the same `422`s as `/research` for a bad file.

**Not built yet:** saving an uploaded business (`POST /businesses/upload`, `DELETE
/businesses/{id}`), promoting a FOUND hypothesis into the business's exposures so the real desk
prices it under its decline rules, and a Claude-written summary (validated against tool results,
I2). The report today has a templated summary and no stored business.

---

## 5. Limitations

- **Settlement source.** Live NYC weather contracts settle on The Weather Company's Central Park reading (since 2026-08-14); the research uses NOAA's record for the same station, a close proxy. `KXRAIN` counts a trace of rain as 0.
- **Temperature strikes.** `KXHIGHNY` lists 6 strikes around each day's forecast, so a fixed strike such as >85°F is listed only about 1 day in 5; a fixed-strike heat or cold hedge often can't be bought exactly.
- **Quotes aren't saved.** The uploaded business isn't stored, so its quote can't be approved or
  booked; the built-in businesses go through the full approval, co-sign and booking flow.
- **Synthetic revenue.** The sample's effects were planted, so finding them shows that the protocol
  works. It says nothing about real bike shops.
- **NYC only, fixed window.** One weather station (Central Park), the Knicks, and the weather
  fixture's 2024-01-01 to 2026-09-30 window.
- **Small samples.** One train year means the rarer flags (hot > 90 °F, game nights) have few
  event days, and their intervals are wide.
- **Correlation, not a guarantee.** Our own taxi rain effect was significant one year and near
  zero the next (see [RESEARCH.md](RESEARCH.md)). A FOUND result replicated once; it is not a
  promise about next year.

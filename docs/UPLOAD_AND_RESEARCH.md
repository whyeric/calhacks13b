# Upload your revenue, then research your risks

Hedge Desk ships with two demo businesses. The "upload your revenue → research my risks → send to
the desk" flow runs the research protocol **live** on a business's own daily revenue. The drawer
offers one example file, **Hudson Bike Co.**, a fictional NYC bike-rental shop, but any CSV in the
right shape works.

> **What's real now.** The report is computed live: the browser posts the CSV to `POST /research`
> ([RESEARCH_CONTRACT.md](RESEARCH_CONTRACT.md)), the backend runs the protocol
> (`backend/app/research.py`) and returns the report already formatted; the frontend shows
> the strings it gets. If the request fails (network or server error), the precomputed Hudson
> report is shown instead, labeled **"Precomputed on the sample file"**. **Send to the desk** is
> still scripted.

---

## 1. What's live and what's scripted

| Part | Status |
|---|---|
| **The sample file** `hudson_bike_co_daily_revenue.csv` | **Synthetic revenue on real weather.** Hudson Bike Co. is fictional. Its daily revenue is generated, but the weather days it reacts to are the **real NOAA Central Park record** (USW00094728, the same Central Park station Kalshi's NYC weather contracts settle on; since 2026-08-14 Kalshi uses The Weather Company's reading there, so NOAA is a close proxy). The file header says so. |
| The effects planted in the file | About **−20% on rain days, −28% below 40 °F, and +10% above 80 °F** (from the file header). No game effect is planted. |
| The upload | **Live.** The browser posts the CSV to `POST /research` (multipart). The backend reads it in memory and stores nothing. |
| Waiting for the report | A spinner while the request is pending (about a second). No staged delay or progress animation. Claude is not called; the mechanisms are fixed in code before fitting. |
| **The report** | **Live.** Every number is computed by the protocol on the uploaded file. The summary sentence is templated from the verdicts and carries no numbers. |
| The fallback | If the request fails for a reason other than a bad file, the precomputed Hudson report (an earlier offline run, below) is shown, labeled "Precomputed on the sample file". A bad file (422) shows its message instead. |
| "Send to the desk" and the hedge it shows | **Scripted**, offered only on FOUND rows that are sendable (rain). The numbers are hardcoded from a desk calculation on the precomputed rain effect. No hedge is proposed through the backend, and nothing is sent to Kalshi. |

Because the effects were planted, the report is a **recovery check**: does the protocol find what
we put in, and reject what we didn't? It isn't evidence about real bike shops.

---

## 2. Running it

1. `make demo`, then open <http://localhost:3000>.
2. Click **Upload your revenue** and choose `hudson_bike_co_daily_revenue.csv`. A copy is in
   `frontend/public/samples/`, and the drawer links it; the presenter's copy is in `~/Downloads/`.
3. Click **Upload and research**; the report appears when the request returns.
4. Read the report (§3). On the rain row, click **Send to the desk** to see the hedge.

The flow works with no network and no API key, like the rest of `make demo`.

### The sample file

- **Fictional:** Hudson Bike Co. is not a real business.
- **Synthetic revenue:** the daily revenue is generated.
- **Real weather:** the weather days are real NOAA Central Park days.
- **Shape:** 1,004 days, **2024-01-01 to 2026-09-30**, with columns `date,revenue`.
- **Header:** two `#` comment lines at the top label the file as synthetic.

Any other file works if it has a `date,revenue` header, one row per day, dates inside the weather
record (2024-01-01 to 2026-09-30) and at least 540 non-zero days. Otherwise the drawer shows the
422 message (`bad_csv`, `duplicate_dates`, `negative_revenue`, `out_of_window`, `too_short`; see
[RESEARCH_CONTRACT.md](RESEARCH_CONTRACT.md)).

### Privacy

The file goes only to your desk's own API (in the demo, on the same machine), is read in memory and
is never stored or sent to Kalshi.

---

## 3. What the protocol found on Hudson Bike Co.

### The protocol (`backend/app/research.py`)

These are the same rules as the hand research in [RESEARCH.md](RESEARCH.md):

- **Model:** log revenue on day of week, year-month fixed effects, US federal holidays and the
  event flag, HC3 standard errors. The Knicks home game is also controlled when testing a win.
- **Weather data:** flags come from NOAA Central Park, the Kalshi settlement station.
- **Train:** 2024.
- **Holdout:** the unseen 2025–26 data, fitted **independently**, with nothing tuned on it.
- **Corrections:** 90% CIs, and Benjamini–Hochberg at 10% across every hypothesis in the run.
- **Placebo:** the same flag shifted 7 days later, which must come back not significant (p ≥ 0.10).
- **Games:** Knicks hypotheses are fitted only on dates the schedule fixture covers (2024-10-22
  onward), so earlier days aren't miscounted as non-game days.
- **Dollars:** the % effect (exp(b) − 1) times the period's mean daily revenue.
- **FOUND** means all of these hold:
  - the train interval excludes 0;
  - it survives BH;
  - the holdout has the same sign, with its own interval excluding 0;
  - the placebo is quiet;
  - there are at least 10 event days.

### Results (live run)

| Hypothesis | Train (2024) | Holdout (2025–26) | Verdict |
|---|---|---|---|
| **Rain** (≥ 0.01 in) | **−18.3%**: −$1,933.03/day, 90% CI −$2,148.98 to −$1,711.56, 125 rain days | **−20.4%**: −$2,487.69/day | **FOUND**. Placebo p = 0.34. Hedgeable via `KXRAIN` (NYC). |
| **Cold** (tmax < 40 °F) | **−26.6%** | **−26.4%** | **FOUND** |
| **Warm** (tmax > 80 °F) | **+10.9%** | **+15.5%** | **FOUND**, as an upside |
| Hot (tmax > 90 °F) | not distinguishable from zero | | NOT FOUND |
| Knicks home game | not distinguishable from zero | | NOT FOUND |
| Knicks win | not distinguishable from zero | | NOT FOUND |

The protocol recovered all three planted effects close to their planted sizes (−20%, −28%, +10%).
It rejected the hot and game hypotheses, and no game effect was planted. That is the behavior the
recovery check is looking for.

The verdicts match the earlier, precomputed report (still in `frontend/lib/demoScript.ts` as the
fallback) exactly; some numbers differ. That run's exact inputs weren't kept. The NOAA fixture has
125 rain days in 2024 where it counted 124, and the Knicks training fits differ most (live +6.3%
home game and +4.7% win vs +3.0% and +1.1%), because the live run fits them only from the
schedule's first date; both stay NOT FOUND on 10–14 game days. The live numbers are the reference
now; `backend/tests/api/test_research.py` pins the verdicts.

### "Send to the desk": rain

The rain row is FOUND and sendable, and maps to Kalshi's NYC daily rain series `KXRAIN` (markets `KXRAIN-<date>-NYC`; the older `KXRAINNYC` series was retired after 2026-07-15), so it can be sent to the desk. The scripted
hedge is:

| | |
|---|---|
| Contracts | **1,955 YES @ 33¢** |
| Premium | **$675.41** (including a $30.26 fee) |
| Expected cost | **≈ $64.86** (premium minus expected payout) |

The scripted hedge was sized on the **precomputed** rain effect: 1,955 contracts ≤ −$1,955.68/day ÷
$1 (I1). The live report measures −$1,933.03/day, so the scripted card no longer matches the live
exposure; pricing the live effect through the desk is the next step (below). As everywhere else, only the owner can approve, and no order is ever placed.

### Verdict reasons, in plain language

| Reason | Meaning |
|---|---|
| `thin_support` | Fewer than 10 event days in train. |
| `not_significant` | The train interval includes zero. |
| `did_not_replicate` | It showed up on train but not on the unseen data. |
| `sign_flipped` | The unseen data points the other way. |
| `failed_bh` | It's significant alone, but not after correcting for how many things were tested. |
| `placebo_fired` | The week-shifted fake also "found" something. |
| `no_contract` | It may be real, but no Kalshi contract settles on it. |

---

## 4. The API, and what's still planned

**Built:** `POST /research` (multipart `file`, optional `name`, `kind`) returns a
`ResearchResponse` synchronously, or a 422 (`bad_csv`, `duplicate_dates`, `negative_revenue`,
`out_of_window`, `too_short`). Full contract: [RESEARCH_CONTRACT.md](RESEARCH_CONTRACT.md).

**Not built yet:**

- Saving an uploaded business (`POST /businesses/upload`, `DELETE /businesses/{id}`).
- `POST /businesses/{id}/research/{hypothesis_id}/promote`, which would add a FOUND hypothesis to
  the business's exposures so the real desk prices it under its six decline rules (replacing the
  scripted "Send to the desk").

**The agent**
- Claude would choose which catalog events fit the business and write each mechanism *before*
  calling `run_hypothesis`.
- The code, not Claude, would apply BH and the final verdicts.
- Claude would write the summary, with every number validated against tool results (I2).
- Without a key, a deterministic fallback would run instead.

---

## 5. Limitations

- **Settlement source.** Live NYC weather contracts settle on The Weather Company's Central Park reading (since 2026-08-14); the research used NOAA's record for the same station, a close proxy. `KXRAIN` counts a trace of rain as 0.
- **Temperature strikes.** `KXHIGHNY` lists 6 strikes around each day's forecast, so a fixed strike such as >85°F is listed only about 1 day in 5; a fixed-strike heat or cold hedge often can't be bought exactly.

- **Send to the desk is scripted.** The hedge card is Hudson's, sized on the precomputed effect.
- **NYC only, fixed window.** One weather station, the Knicks, and the 2024-01-01 to 2026-09-30
  weather fixture; files outside that window are rejected.
- **Synthetic revenue.** The effects were planted, so finding them shows that the protocol works.
  It says nothing about real bike shops.
- **Small samples.** One train year means the rarer flags (hot > 90 °F, Knicks games and wins) have few
  event days, and their intervals are wide.
- **Correlation, not a guarantee.** Our own taxi rain effect was significant one year and near
  zero the next (see [RESEARCH.md](RESEARCH.md)). A FOUND result replicated once; it is not a
  promise about next year.

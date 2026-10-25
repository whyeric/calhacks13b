# Upload your revenue, then research your risks

Hedge Desk ships with two demo businesses. The "upload your revenue → research my risks → send to
the desk" flow shows what the research protocol does on a business's own data, using one example
business: **Hudson Bike Co.**, a fictional NYC bike-rental shop.

> **Read this first: the demo flow is scripted.** No upload or research routes exist in the
> backend. The flow is a staged frontend animation followed by a hardcoded report. Every number
> in that report came from **really running our research protocol offline on the sample file**,
> and the report shows those outputs; nothing is computed live in the browser. A real upload and
> research API is future work (see [§4](#4-planned-real-upload--research-api-not-implemented)).

---

## 1. What's scripted and what's real

| Part | Status |
|---|---|
| **The sample file** `hudson_bike_co_daily_revenue.csv` | **Synthetic revenue on real weather.** Hudson Bike Co. is fictional. Its daily revenue is generated, but the weather days it reacts to are the **real NOAA Central Park record** (USW00094728, the same Central Park station Kalshi's NYC weather contracts settle on; since 2026-08-14 Kalshi uses The Weather Company's reading there, so NOAA is a close proxy). The file header says so. |
| The effects planted in the file | About **−20% on rain days, −28% below 40 °F, and +10% above 80 °F** (from the file header). No game effect is planted. |
| The upload step | **Partly real.** The browser reads the file and shows its real row count and date range. Nothing is stored or sent anywhere. |
| "Claude pre-registers mechanisms" and the protocol steps | **A staged animation.** It shows the steps the protocol runs, in order. Claude is not called during the demo. |
| **The report's numbers** | **Real outputs of our protocol**, computed offline on this file and hardcoded into the frontend. |
| "Send to the desk" and the hedge it shows | **Scripted**, with the numbers hardcoded from a desk calculation. No hedge is proposed through the backend, and nothing is sent to Kalshi. |

Because the effects were planted, the report is a **recovery check**: does the protocol find what
we put in, and reject what we didn't? It isn't evidence about real bike shops.

---

## 2. Running the scripted flow

1. `make demo`, then open <http://localhost:3000>.
2. Click **Upload your revenue** and choose `hudson_bike_co_daily_revenue.csv`. A copy is in
   `frontend/public/samples/`, and the drawer links it; the presenter's copy is in `~/Downloads/`.
3. Click **Research my risks** and let the animation run: the mechanisms are written first, then
   the protocol steps.
4. Read the report (§3). On the rain row, click **Send to the desk** to see the hedge.

The flow works with no network and no API key, like the rest of `make demo`.

### The sample file

- **Fictional:** Hudson Bike Co. is not a real business.
- **Synthetic revenue:** the daily revenue is generated.
- **Real weather:** the weather days are real NOAA Central Park days.
- **Shape:** 1,004 days, **2024-01-01 to 2026-09-30**, with columns `date,revenue`.
- **Header:** two `#` comment lines at the top label the file as synthetic.

### Privacy

In the demo the file is read inside the browser for its row count and dates, and nothing leaves
the browser. In the planned version, revenue would be stored in local SQLite only and never sent to Kalshi.

---

## 3. What the protocol found on Hudson Bike Co.

### The protocol

These are the same rules as the hand research in [RESEARCH.md](RESEARCH.md):

- **Model:** log revenue on day of week, year-month fixed effects, holidays and the event flag.
  `home_game` is also controlled when testing a game result.
- **Weather data:** flags come from NOAA Central Park, the Kalshi settlement station.
- **Train:** 2024.
- **Holdout:** the unseen 2025–26 data, fitted **independently**, with nothing tuned on it.
- **Corrections:** 90% CIs, and Benjamini–Hochberg at 10% across every hypothesis in the run.
- **Placebo:** the same flag shifted 7 days, which must come back not significant.
- **FOUND** means all of these hold:
  - the train interval excludes 0;
  - it survives BH;
  - the holdout has the same sign, with its own interval excluding 0;
  - the placebo is quiet;
  - there are at least 10 event days.

### Results

| Hypothesis | Train (2024) | Holdout (2025–26) | Verdict |
|---|---|---|---|
| **Rain** (≥ 0.01 in) | **−18.4%**: −$1,955.68/day, 90% CI −$2,171.00 to −$1,734.86, 124 rain days | **−20.4%**: −$2,485.41/day | **FOUND**. Placebo p = 0.38. Hedgeable via `KXRAIN` (NYC). |
| **Cold** (tmax < 40 °F) | **−27.0%** | **−26.4%** | **FOUND** |
| **Warm** (tmax > 80 °F) | **+10.9%** | **+15.5%** | **FOUND**, as an upside |
| Hot (tmax > 90 °F) | not distinguishable from zero | | NOT FOUND |
| Knicks home game | not distinguishable from zero | | NOT FOUND |
| Knicks win | not distinguishable from zero | | NOT FOUND |

The protocol recovered all three planted effects close to their planted sizes (−20%, −28%, +10%).
It rejected the hot and game hypotheses, and no game effect was planted. That is the behavior the
recovery check is looking for.

### "Send to the desk": rain

The rain row is FOUND and maps to Kalshi's NYC daily rain series `KXRAIN` (markets `KXRAIN-<date>-NYC`; the older `KXRAINNYC` series was retired after 2026-07-15), so it can be sent to the desk. The scripted
hedge is:

| | |
|---|---|
| Contracts | **1,955 YES @ 33¢** |
| Premium | **$675.41** (including a $30.26 fee) |
| Expected cost | **≈ $64.86** (premium minus expected payout) |

The 1,955 contracts are no more than the measured exposure (−$1,955.68/day ÷ $1), as invariant
I1 requires. As everywhere else, only the owner can approve, and no order is ever placed.

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

## 4. Planned: real upload + research API (not implemented)

**None of this is implemented.** It records the contract we designed for a real version, in which an owner
uploads any CSV and research runs live.

**Upload**
- `POST /businesses/upload` (multipart: `name`, `kind`, `file`) returns 201 with a
  `Business` (`uploaded: true`).
- Validation errors are 422s: `bad_csv`, `too_short` (< 540 days), `out_of_window`,
  `duplicate_dates`, `negative_revenue`.
- `DELETE /businesses/{id}` returns 204, or 403 `not_uploaded` for a built-in business.
- `GET /samples` lists the sample files.

**Research**
- `POST /businesses/{id}/research` returns 202 with a `run_id`. Poll `GET /runs/{run_id}`, then
  fetch the report with `GET /businesses/{id}/research`, which returns a `ResearchReport`.
- `POST /businesses/{id}/research/{hypothesis_id}/promote` adds a FOUND hypothesis to the
  business's exposures, so the real desk prices it under its six decline rules.

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

- **Scripted, not live.** The report is Hudson Bike Co.'s. The demo doesn't analyse any other
  file.
- **Synthetic revenue.** The effects were planted, so finding them shows that the protocol works.
  It says nothing about real bike shops.
- **NYC only.** The protocol uses one weather station (Central Park) and New York teams.
- **Small samples.** One train year means the rarer flags (hot > 90 °F, playoff nights) have few
  event days, and their intervals are wide.
- **Correlation, not a guarantee.** Our own taxi rain effect was significant one year and near
  zero the next (see [RESEARCH.md](RESEARCH.md)). A FOUND result replicated once; it is not a
  promise about next year.

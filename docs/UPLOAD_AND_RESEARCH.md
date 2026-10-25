# Upload your revenue, then research your risks

Hedge Desk ships with two demo businesses, but you can also bring your own. Upload a daily
revenue CSV and the app runs the same analysis, desk, backtest and ledger on it that it runs on the
taxi fleet. Then click **Research my risks**: Claude pre-registers a set of mechanisms, the harness
tests each one under a fixed protocol, and any risk that comes back **FOUND** can be sent to the
desk to be priced.

> **Status.** This page describes the contract the upload and research features are being built
> against. Anything marked *fill in after integration* depends on code that hasn't merged yet;
> replace it with the number from a real run, and don't guess.

---

## 1. Uploading your revenue

### Where

Click **Upload your revenue** in the header. The drawer asks for:

| Field | Rule |
|---|---|
| **Name** | 1 to 60 characters. It's how the business shows in the switcher. |
| **Type** | One of `bar`, `restaurant`, `shop`, `transport`, `other`. Research uses it to choose which hypotheses fit. |
| **File** | A CSV of daily revenue (format below). |

On success the app switches to the new business, and the switcher shows it with an **Uploaded**
badge and a delete action.

### CSV format

Two columns, one row per day:

```csv
date,revenue
2024-01-01,1834.50
2024-01-02,2210.00
```

- **Headers are forgiving.** `Date`/`date`, and `revenue`, `Revenue`, `sales` or `amount` are all
  accepted.
- **Values can be formatted.** `$1,234.50` is read as `1234.50`.
- **One row per date.** Repeated dates are rejected rather than summed.
- **No negative revenue.** Refunds and chargebacks should be netted into the day before upload.
- **Missing days are fine.** A closed day can be left out. Don't fill it with 0 unless you really
  took in nothing.

### Limits

| Limit | Why |
|---|---|
| **At least 540 days** after clipping to the data window | Research fits the first 365 days (train) and the rest (holdout) **independently**. 540 days leaves a holdout of at least 175 days. |
| **Must overlap the cached weather and schedule data** | Every event flag (rain, heat, game nights) comes from the committed NOAA Central Park and Knicks/Rangers files, so revenue outside that window can't be tested. Rows outside it are clipped, and `detail.clipped_to` tells you the range that was kept. The committed NOAA file currently runs 2024-01-01 to 2026-09-30; *fill in after integration: the exact window the upload code clips to.* |
| **Maximum file size / row count** | *Fill in after integration.* |

### Errors

Every rejection is a **422** with a code and the shape
`{"error": {"code", "message", "detail": {rows, first_date, last_date, clipped_to?}}}`. The drawer
shows the message inline.

| Code | Meaning | What to do |
|---|---|---|
| `bad_csv` | The file couldn't be parsed, or no date/revenue columns were found. | Export as CSV with a `date` and a `revenue` column. |
| `too_short` | Fewer than 540 days remain after clipping. | Upload a longer history. |
| `out_of_window` | None of your dates overlap the cached weather/schedule data. | Upload dates inside the window above. |
| `duplicate_dates` | The same date appears more than once. | Sum to one row per day first. |
| `negative_revenue` | A day has revenue below zero. | Net refunds into the day's total. |

### NYC only

The weather comes from **NOAA station USW00094728 (Central Park)**, which is the station Kalshi's
NYC rain and temperature contracts settle on. The sports events are **Knicks and Rangers** home
games at Madison Square Garden. If your business isn't in New York City, the analysis still runs,
but it measures your revenue against *New York* weather and *New York* games, so the results mean
nothing for you. There's no location field, because there's no other city's data to switch to.

### Privacy

**Your revenue stays on this machine. It's never sent to Kalshi or anywhere else.**

- The rows are stored in the local SQLite database only.
- Kalshi only ever sees public market reads. The app never places orders, for any business.
- With `ANTHROPIC_API_KEY` set, Claude sees what its tools return. For research that's the
  business profile (`get_business`), the candidate list and the harness's *results* (effects,
  intervals, p-values), not the daily rows. The desk and the "why?" chat likewise see exposures and
  check results. *Fill in after integration: confirm that no tool returns raw revenue rows.*
  Without a key, nothing leaves the machine at all.
- **Delete** in the switcher (or `DELETE /businesses/{id}`) removes the business and its revenue.

### Sample files

The drawer links two sample CSVs, which are also served at `GET /samples`:

| File | What it is |
|---|---|
| `sample_revenue_nyc_bike_shop.csv` | A bike shop's daily revenue |
| `sample_revenue_msg_sports_bar.csv` | A sports bar near MSG |

**These are synthetic.** They're generated from a seeded script with effects planted on purpose,
so you can see what a FOUND looks like. They aren't anyone's real books, and a result on them is a
check that the harness recovers what was planted, not a finding about bike shops.
*Fill in after integration: the planted effect sizes, from the sample generator.*

---

## 2. How research works

### In one paragraph

Click **Research my risks**. Claude reads your business type and the catalog of events Kalshi can
settle on, picks the ones that plausibly matter (at most 12), and for each one **writes down the
mechanism before any test is run**: why rain would cut a bike shop's sales, for example. The
harness then tests every hypothesis with the same fixed protocol. Claude doesn't choose the model,
the split or the thresholds, and can't re-run a test that came back badly. Claude then writes a
plain-language summary and one explanation per hypothesis, but **every number in them must come
from the harness**. A summary with any other number is rejected and re-prompted once, then
replaced by a template.

**Claude does the analyst's work, but it never produces a number.**

Without an API key (or if Claude fails), a deterministic fallback runs instead. It tests every
catalog event that fits the business type, uses the catalog's own mechanism text and writes
templated explanations. The report says `agent: "fallback"`.

### The protocol

The protocol is fixed in code and printed in every report under `protocol`.

1. **Model.** Log revenue on day of week + year-month fixed effects + holidays + the event flag.
   For game-result or playoff flags, `home_game` is controlled as well, so "the Knicks won"
   isn't confused with "there was a game".
2. **Errors.** HC3 robust standard errors, or classical ones when there are fewer than 10 event
   days (HC3 collapses on very sparse flags).
3. **Train / holdout.** Train is the first 365 days; holdout is everything after. Each period is
   fitted **separately**. Nothing is tuned on the holdout.
4. **Intervals.** 90% confidence intervals. Effects are reported in **dollars per day** at the
   train-period mean revenue.
5. **Multiple testing.** Benjamini–Hochberg at 10% across **every hypothesis in the run**, so
   testing 12 things doesn't buy 12 lottery tickets.
6. **Placebo.** The same flag is shifted 7 days later and refitted. A real rain effect shouldn't
   show up a week after the rain, so the placebo has to come back **not significant**.
7. **Settlement data.** Weather flags are built from the NOAA Central Park station that Kalshi
   settles on, so the event we measure is the event the contract pays on.

### Verdicts

| Verdict | Plain meaning |
|---|---|
| **FOUND** | The effect is real by every test we run: the train interval excludes zero, it survives the multiple-testing correction, the holdout shows the same direction with its own interval excluding zero, the week-later placebo is quiet, and there were at least 10 event days in train. |
| **NOT_FOUND** | At least one of those checks failed. The reasons say which. |
| **UNTESTABLE** | We couldn't run a fair test, usually because there were too few event days. |

A FOUND risk is **hedgeable** only if a Kalshi series settles on it.

### Reasons, in plain language

| Reason | What it means |
|---|---|
| `thin_support` | Fewer than 10 event days in train. Too few to trust. |
| `not_significant` | On the first year, the effect's interval includes zero. |
| `did_not_replicate` | It showed up in the first year, but not in the later data. |
| `sign_flipped` | The later data points the *other way*. |
| `failed_bh` | It looked significant alone, but not after correcting for how many things we tested. |
| `placebo_fired` | The same test shifted a week also "found" something, so the original result is probably seasonality or chance. |
| `no_contract` | It may be real, but no Kalshi contract settles on it daily, so it can't be hedged. Examples: heavy rain (≥5 mm), and regular home games, which are scheduled and so belong in a forecast. |
| `not_enough_data` | The history doesn't cover enough of the event to fit at all. |

### The catalog

| Event | Kalshi series | Notes |
|---|---|---|
| Rain ≥ 0.01 in | `KXRAINNYC` / `KXRAIN` | NOAA Central Park |
| Rain ≥ 5 mm | none | `no_contract` |
| Hot: tmax > 80 / 85 / 90 °F | `KXHIGHNY` | strict ">", as the contract settles |
| Cold: tmax < 40 °F | `KXHIGHNY` (lower strikes) | |
| Snow ≥ 0.1 in | `KXSNOWSTORM` | event-driven |
| Home game | none | scheduled, informational (`no_contract`) |
| Home win | `KXNBAGAME` / `KXNHLGAME` | controls for `home_game` |
| Playoff home game | `KXNBASERIES` / `KXNBAPLAYOFF` | controls for `home_game` |
| Away playoff night | `KXNBASERIES` | |
| Weekend × rain | `KXRAIN` | |

Each entry carries a mechanism hint, which the fallback uses verbatim and Claude may rewrite.

### "Send to the desk"

On a **FOUND** row with a Kalshi series, the **Send to the desk** button promotes the hypothesis
into the business's exposures (`source: "research"`). From then on:

- `/analyze` lists it next to the measured exposures;
- **Run desk** treats it like any other exposure: it looks for a market inside the desk week, sizes
  the hedge at no more than the measured exposure (I1), and applies all six decline rules;
- the owner still has to approve. Nothing is ever sent to Kalshi.

Sending a risk to the desk doesn't promise a hedge. The desk can still decline it, for example
with `no_market` if no contract is listed for a day in the desk week, or with `overpriced`.

---

## 3. API reference

All money is a Decimal string. Errors use `{"error": {"code", "message", "detail"}}`. Everything
works offline (`DEMO_OFFLINE=1`).

### Upload

**`POST /businesses/upload`** (multipart/form-data: `name`, `kind`, `file`)

```bash
curl -F name="Hudson Bikes" -F kind=shop \
     -F file=@sample_revenue_nyc_bike_shop.csv \
     localhost:8000/businesses/upload
```

- **201** → `Business` with `id: "up_<slug>_<6hex>"`, `estimated: false`,
  `data_label: "uploaded"`, `uploaded: true`.
- **422** → `bad_csv` | `too_short` | `out_of_window` | `duplicate_dates` | `negative_revenue`.

**`DELETE /businesses/{id}`** → **204** for an uploaded business; **403** `not_uploaded` for a
built-in; **404** if it doesn't exist.

**`GET /businesses`** now includes uploaded businesses (`uploaded: true`; built-ins default to
`false`).

**`GET /samples`** → `[{"file", "title", "description"}]`.
**`GET /samples/{file}`** → `text/csv`.

Every existing route (`/analyze`, `/desk/run`, `/hedges`, `/backtest`, `/chat`, `/settings`,
`/ledger`) works unchanged with an uploaded id.

### Research

**`POST /businesses/{id}/research`** with body `{}` → **202** `{"run_id", "status": "queued"}`. It
runs in the background. Poll **`GET /runs/{run_id}`**, which reports `kind: "research"`.

```bash
curl -XPOST localhost:8000/businesses/$ID/research -H 'content-type: application/json' -d '{}'
curl localhost:8000/runs/$RUN_ID
curl localhost:8000/businesses/$ID/research
```

**`GET /businesses/{id}/research`** → **200** `ResearchReport` (the latest one); **409**
`research_not_ready` if no run has finished.

**`POST /businesses/{id}/research/{hypothesis_id}/promote`** → **200** `Exposure`
(`source: "research"`); **409** `not_found_verdict` if the hypothesis isn't FOUND.

### Models

```
ResearchReport   { business_id, run_id, created_at, agent: "claude" | "fallback",
                   protocol: { train_start, train_end, holdout_start, holdout_end,
                               fe: "year_month", alpha: 0.10, bh: 0.10, min_events: 10 },
                   n_tested, n_found, hypotheses: [HypothesisResult], summary, notes: [str] }

HypothesisResult { id, event_id, label, family: "weather" | "sports" | "calendar", mechanism,
                   kalshi_series | null, settlement,
                   n_events_train, n_events_holdout,
                   train:   { effect_usd, ci90: [lo, hi], p_value },
                   holdout: { effect_usd, ci90: [lo, hi], p_value } | null,
                   placebo: { effect_usd, p_value, shift_days } | null,
                   bh_q | null,
                   verdict: "FOUND" | "NOT_FOUND" | "UNTESTABLE",
                   reasons: [...], hedgeable, promoted, explanation }

CandidateEvent   { id, family, label, kalshi_series | null, settlement, mechanism_hint }
```

`effect_usd` and the CI bounds are Decimal strings in $/day at the train mean. All models are
`extra="forbid"`.

---

## 4. Limitations

- **Small samples.** A 540-day upload gives a 365-day train and a holdout as short as 175 days.
  Snow, cold and playoff flags may have only a handful of event days, so expect `thin_support` and
  `UNTESTABLE`, and wide intervals even on a FOUND. A FOUND means "this survived every check we
  run", not "this is the exact size of your risk".
- **NYC-only data.** One weather station (Central Park) and two teams (Knicks, Rangers). For a
  business elsewhere the numbers are meaningless. For a business in an outer borough, Central Park
  weather is still a proxy.
- **The samples are synthetic.** The two sample CSVs are seeded and have planted effects. Use them
  to see the flow and to check that the harness finds what was planted, never as evidence about
  real shops or bars.
- **It runs on your own data, with no hindsight tuning.** The protocol, the split, the thresholds
  and the catalog are fixed before your file arrives. Claude only chooses *which* catalog events to
  test and writes the mechanism *before* the test. It can't add a covariate, move the split or
  retry a failed hypothesis. Every hypothesis tested is counted in the BH correction and shown in
  the report, including the ones that failed.
- **Correlation, not a guarantee.** A FOUND effect is a historical association that replicated.
  The desk sizes against it, but next year can differ. Our own research shows a taxi rain effect
  that was significant one year and close to zero the next (see [RESEARCH.md](RESEARCH.md)).
- **One business rarely notices a daily weather hedge.** Even a real rain effect usually moves a
  single business's variance only a little. The desk shows the cost and the swing so the owner
  can judge.

# Research contract: `POST /research`

The contract between the backend research endpoint (`backend/app/research.py`, route in
`backend/app/main.py`) and the upload flow in the frontend (`components/DemoDesk.tsx`,
`components/SetupWizard.tsx`). Models: `ResearchResponse`, `ResearchRow`, `ResearchSide` in
`backend/app/models.py`. Example: `backend/fixtures/examples/research_response.json`.
The protocol itself is in [UPLOAD_AND_RESEARCH.md §3](UPLOAD_AND_RESEARCH.md#3-what-the-protocol-found-on-hudson-bike-co).

## Request

`POST /research`, `multipart/form-data`:

| Field | Required | Notes |
|---|---|---|
| `file` | yes | The CSV. UTF-8, at most 5 MB. |
| `name` | no | Business name, ≤ 60 chars. Accepted for the caller's own display; not echoed, not stored. |
| `kind` | no | Business kind (`Bike rental`, …), ≤ 40 chars. Same. |

Synchronous, stateless (nothing stored), offline (no network, no API key, no LLM call).

### The CSV

- Header row `date,revenue`, one row per day, ISO dates (`YYYY-MM-DD`). Lines starting with `#`
  and blank lines are skipped. `$`, `,` thousands separators and surrounding quotes are stripped
  from revenue.
- Revenue `0` is a closed day: dropped before fitting (log revenue), not an error, and not counted
  in `n_days`.

### Validation (422), checked in this order

Body is the usual `{"error": {"code", "message", "detail"}}`. `message` is a plain sentence the
frontend shows as-is.

| Code | When | `detail` |
|---|---|---|
| `bad_csv` | No file, empty, not UTF-8, over 5 MB, no `date`/`revenue` header, or any data row whose date or revenue doesn't parse | `{"line": n}` for the first bad row, else `null` |
| `duplicate_dates` | A date appears more than once | `{"dates": [...]}` (first 5) |
| `negative_revenue` | Any revenue < 0 | `{"dates": [...]}` (first 5) |
| `out_of_window` | Any date outside the weather record, 2024-01-01..2026-09-30 | `{"dates": [...], "window": ["2024-01-01", "2026-09-30"]}` |
| `too_short` | Fewer than 540 usable (non-zero) days | `{"days": n, "min_days": 540}` |

## Response (200): `ResearchResponse`

```jsonc
{
  "summary": "Rain and cold reliably cost you money; …",   // deterministic template, no numbers
  "protocol_chips": ["Training year: 2024", "Unseen: 2025–26", …],
  "n_days": 1004,              // usable days fitted
  "first": "2024-01-01",       // first/last usable date
  "last": "2026-09-30",
  "rows": [ResearchRow × 6],   // always all six, in the order below
  "source": "live"
}
```

`ResearchRow` is field-for-field the frontend's `ResearchRow` in `frontend/lib/demoScript.ts`
(including the camelCase `verdictNote`), so the UI renders a response row exactly like a
precomputed one:

```ts
type ResearchRow = {
  id: "rain" | "cold" | "warm" | "hot" | "knicks_home" | "knicks_win";
  label: string;            // "Rain day", "Cold day <40°F", "Warm day >80°F", "Hot day >90°F", "Knicks home game", "Knicks win"
  mechanism: string;        // fixed in code before fitting (same text as HYPOTHESES)
  train:  { text: string; ci: string; days: string; plot: [string, string, string] };
  unseen: { text: string; ci: string; days: string; plot: [string, string, string] };
  placebo: string;
  verdict: "FOUND" | "NOT FOUND";
  verdictNote: string | null;
  kalshi: string;           // from backend/fixtures/kalshi_series_catalog.json
  sendable: boolean;
};
```

### Formatting (backend formats; the frontend never calculates)

All numbers come from `Decimal` values quantized to cents (percent to 0.1). Negative sign is
U+2212 `−`; positive values carry `+`. Thousands separators are commas.

| Field | Format | Example |
|---|---|---|
| `text` | `{±pct}% · {±$}/day` | `−18.4% · −$1,955.68/day` |
| `ci` | `90% CI {±$low} to {±$high}` | `90% CI −$2,171.00 to −$1,734.86` |
| `days` | `{n} days` (event days in that period) | `124 days` |
| `plot` | `[effect, ci_low, ci_high]`, $/day, Decimal strings, 2 dp, ASCII `-` | `["-1955.68", "-2171.00", "-1734.86"]` |
| `placebo` | `Not significant (p 0.38)` or `Significant (p 0.04)`; p to 2 dp, `<0.01` below that | |

$/day = (exp(b) − 1) × that period's mean daily revenue; the CI bounds use exp(ci) − 1 the same way.

If a period can't be fitted (fewer than 2 event days or a singular design), that side is
`{"text": "Not estimable", "ci": "—", "days": "{n} days", "plot": ["0.00", "0.00", "0.00"]}`.

### Periods and chips

Train = usable days from the first usable date through one year later (exclusive); for a file
starting 2024-01-01 that is exactly 2024. Unseen = every usable day after that, fitted
independently. Chips: `Training year: 2024` when train is calendar 2024, else
`Training: {first} to {end}`; `Unseen: 2025–26` (the years covered); then the fixed chips in the
example. Knicks hypotheses are fitted only on dates the schedule fixture covers (from its first
date), so pre-schedule days aren't miscounted as non-game days; `days` counts game days in range.

### Verdicts

FOUND iff all of: ≥ 10 train event days; train 90% CI excludes 0; survives BH at 10% across the
six train p-values; placebo p ≥ 0.10; unseen effect has the same sign with its own 90% CI excluding 0.

`verdictNote`:

| Case | Note |
|---|---|
| FOUND, downside, sendable | `hedgeable` |
| FOUND, downside, not sendable | `null` |
| FOUND, upside | `upside, no protection needed` |
| NOT FOUND | the first failing rule, in this order: `thin_support` → `Too few event days in the training year`; `not_significant` → `Not distinguishable from zero`; `failed_bh` → `Not significant after correcting for 6 tests`; `placebo_fired` → `The week-shifted placebo fired too`; `sign_flipped` → `Unseen data points the other way`; `did_not_replicate` → `Didn't hold up on unseen data` |

`sendable` = FOUND, downside, and the catalog lists a daily, fixed-strike Kalshi instrument that
settles on exactly that flag (on Hudson only rain qualifies). The frontend shows "Send to the desk"
only for rows with `sendable: true`, and that step stays scripted for now.

## Frontend behavior

- The upload drawer and the wizard's upload path `POST /research` and show a spinner while it's
  pending. No staged delay, no progress animation.
- A 422 shows its `message` plainly in the drawer; the user can pick another file.
- A network error or non-422 failure falls back to the precomputed `RESEARCH_ROWS`/`SUMMARY`,
  labeled **"Precomputed on the sample file"** (I6).
- `NEXT_PUBLIC_MOCK=1` serves `backend/fixtures/examples/research_response.json` through the mock.

# On-screen values (for checking captions)

Captured 2026-10-25 by `video/capture/run.sh`. The setup is the same as `make demo`: `DEMO_OFFLINE=1`, `DEMO_AS_OF=2026-10-24T19:00:00Z`, the same seed steps and a production frontend. Each pass uses a freshly seeded database. The viewport is 1440×900 at 2x. The raw text of every panel is in `onscreen-values.json`.

## Which business and state each frame shows

The model check is computed per business, so the same panel shows different numbers for the taxi fleet and the bar. Caption from the frame you actually use.

| Frame | Business | State | Model check shown |
|---|---|---|---|
| **shot-04-model-check.png** (this set) | **Midtown taxi fleet** (`taxi`) | After **Run desk** (real run, no sample banner); demo week Oct 26 | Planted $500 · Recovered **−$1,644.72** · 90% interval −$4,085.85 to $796.42 · Coverage **96%** · 50 trials · Holdout R² 0.2363… |
| shot-08-not-hedged-list.png (this set) | Midtown taxi fleet | Same state as shot-04 (the model check is in the lower half of the crop) | Same as shot-04 |
| shot-15-dashboard-wide.png (this set) | Midtown taxi fleet | Same state as shot-04 | Same as shot-04 |
| `earlier/shot-10-model-check.png` | **Bar across from MSG** (`restaurant`) | Seeded **sample week**, before any desk run (sample banner shown); 1920 viewport | Planted $500 · Recovered **$1,589.50** · 90% interval −$15.18 to $3,194.18 · Coverage **86%** · 50 trials · Holdout R² 0.0458… |
| `earlier/shot-08/09/18` (dashboard, exposure panel) | Bar across from MSG | Sample week | Same as `earlier/shot-10` |

The other frames' business and state:

- **Hudson Bike Co.** (scripted demo, `up_hudson_bike_co_demo`) in the setup wizard: shot-01, shot-02, shot-02b and shot-03 (step 2, after the analysis bar), plus shot-05, shot-06 and shot-09 (step 4, Proposed). shot-10 is the same card after Approve.
- **Hudson Bike Co.** on the dashboard, after the approval: shot-11.
- **Midtown taxi fleet**, after Run desk: shot-07, shot-08, shot-14 and shot-15.
- **Midtown taxi fleet**, Books tab: shot-12 (the stored reconciliation is already shown) and shot-13 (after clicking Run reconciliation; same values).

## Reconciliation gap (shot-13, taxi, after Run reconciliation)

- Summary line: **As of Oct 23, 2026 · 2 matched · 1 flagged · off by −$0.89**
- Flagged row: **KXHIGHNY-26OCT20-T72**, with Expected $60, Kalshi ledger $60 and Bank (simulated) $59.11, marked **⚠ Flagged · −$0.89**.
- Matched rows: KXHIGHNY-26OCT21-T66 at $0 / $0 / $0, and KXHIGHNY-26OCT22-T70 at $45 / $45 / $45.
- Note text: "Bank deposit is $0.89 short of the Kalshi payout; equals the $0.89 fee recorded for hdg_s01."
- Question text: "Question for you: Did you authorize the $0.89 fee to be netted from this withdrawal?"
- **The S14 caption "−$0.89" is confirmed.**

## Model check (shot-04: Midtown taxi fleet, after Run desk)

- Planted: **$500**
- Recovered: **−$1,644.72** (a negative number)
- 90% interval: **−$4,085.85 to $796.42**. This interval **does** contain $500 (500 < 796.42), but the point estimate has the wrong sign. (Corrected by team-lead.)
- Coverage: **96% · 50 trials**
- Holdout R²: **0.23632632956599398** (the app shows it unrounded)

> ⚠ **The S8 caption "Planted $500 → found" is not supported by this screen.** On taxi, this example recovers −$1,644.72 (wrong sign); the interval contains $500 only because it is wide. The one claim the screen does support is "Coverage 96% over 50 trials", meaning the interval contained the planted effect in 96% of the trials.
>
> For comparison, the bar's (restaurant) model check in the earlier sample-week capture (`earlier/shot-10-model-check.png`, 1920 viewport) showed Planted $500, Recovered $1,589.50, 90% interval −$15.18 to $3,194.18, Coverage 86% · 50 trials and Holdout R² 0.0458… That example's interval also contains $500.
>
> Recommendation: the current S8 caption "Planted $500, inside the 90% interval" is accurate; "caught in 96% of 50 trials" is also accurate. Don't caption "found $500".

## Taxi rain: Last year vs. Recent months (shot-07, taxi, after Run desk)

- Comparison block: **Last year $2,080.20 · Recent months $228.41**
- Card sentence: "rain added $2,080 a day last year but only $228, not distinguishable from zero, in the most recent months, so the risk isn't reliable enough to insure."
- Reason lines: "No open market" (n candidates 0) and "Not reliable: the effect didn't hold up in recent months".
- Recent window: 2025-10-01 to 2026-08-31, with 158 rain days. Its CI is −1885.02 to 2341.83, as raw numbers. Direction flipped is false.
- The title reads "No matching market", and the status chip reads "Declined".
- **The S11 caption "+$2,080 → +$228" is confirmed.** On screen, these figures are per day.
- Wording note: on screen the reasons read "No open market" and "Not reliable: …", not "No market" or "Unstable".

## Other values the captions use

- shot-01: "Hudson Bike Co. · 1,004 days · 2024-01-01 → 2026-09-30", with the "Uploaded · sample" badge.
- shot-02b, Rain row: training −18.4% · −$1,955.68/day; unseen **−20.4%** · −$2,485.41/day; FOUND · hedgeable; placebo "Not significant (p 0.38)".
- shot-03: Hot day >90°F, Knicks home game and Knicks win, each "Not distinguishable from zero".
- shot-06: "Buy YES · 1,955 contracts @ 33¢ · premium $675.41 (includes $30.26 fee) · pays $1,955.00 if it rains", followed by "Expected cost ≈ $64.86 (premium minus expected payout at the 31% NOAA rain rate)".
- shot-08: taxi "What moves revenue", with the **Real** badge, Rain $2,080.20 (90% interval $385.70 to $3,774.69), and "Measured, not hedged (1): Home-team result · Evidence is not strong enough".
- shot-11: APPROVAL · OWNER and PROPOSAL · DESK, both timestamped by the wall clock (05:17 AM ET in the final run). The text reads "(scripted demo)".

## Labels: what is and isn't on screen

- The **"Fictional shop · synthetic sales · real weather"** badge does not exist anywhere in the app, on this branch or on `origin/main`. The nearest on-screen label is "Uploaded · sample" (shot-01). Add the fictional-shop chip in the edit, as the script's S6 already plans.
- **Simulated** appears in shot-12 (the panel badge "Simulated · settlements and the bank statement are simulated from real market results", plus a "Simulated" tag on every ledger row) and in shot-13 ("Simulated · bank statement", "Bank (simulated)").
- **"Booked on approval"** does **not** appear in shot-12. Taxi's seeded ledger has no owner-approved hedge, so every row is "Simulated". The badge appears only after an approval; see the bar's ledger in `earlier/shot-22-ledger-tab.png`.
- **Estimated**: the taxi screens show "Real" instead (shot-08, shot-14). The bar near MSG shows "Estimated · visits × average check" (see `earlier/`).

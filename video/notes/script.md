# Offset: product video script

**Runtime:** 1:54.8 with the recorded VO (hard cap 2:00) · voiceover plus keyword captions over Motion graphics and real screenshots. The narration text is in `vo.txt`.

**Logline:** A rainy Saturday or a home-game night can swing a small business's week. Offset measures that swing in dollars, prices protection on Kalshi, says no when the risk isn't real, and leaves every decision to the owner.

**Principles** (exact slide wording; S4 shows all four, later scenes call back with a corner tag, `principleTag` in `lib.js`):

| # | Name | Line | Tagged in |
|---|---|---|---|
| 1 | Measured, not guessed | Every number comes from harness or tool output. Estimates and simulations are labeled. | S8, S9 |
| 2 | Built for steady income | Hedges are sized to cancel a measured exposure, not to make money. Our goal is to stabilize. | S11 |
| 3 | Owner's call, every time | Offset is human-first; only the owner can approve. Offset can’t approve its own hedge. | S13 |
| 4 | Interpretable, human-facing | Every accepted or declined hedge comes with its evidence. | S12, S14, S15 |

## Ground rules for the edit

- **Numbers.** Every number in a caption or the VO is cited in the *Source* column. If a figure isn't cited, it must be read off the screenshot ("[from screenshot]"), never typed in. Where the VO rounds, the caption rounds the same way and doesn't count up.
- **Labels (I6).** Hudson Bike Co. is **fictional**, with synthetic sales on real weather. The taxi ledger and bank statement are **simulated**. Keep the app's own badges visible in frame, and add a small caption chip where noted.
- **What's live.** On `main` the upload and the research report are **live**: the CSV goes to `POST /research` and every number in the table is computed on it. "Send to the desk" and the hedge card after it are **scripted** (`frontend/lib/demoScript.ts` DEMO_HEDGE; the app labels it "Example hedge (scripted)"). Captions may say the research is live; never call the hedge, its price or its approval live.
- **Screenshots are from an earlier run.** The captures (2026-10-25, merge-base 482cbfa) predate the live research API. That run's rain row reads −$1,955.68/day (−18.4%, 124 days); main's live run reads −$1,923.43/day (−18.2%, 125 days, `docs/UPLOAD_AND_RESEARCH.md`). The VO says "nearly $2,000", true of both. The hedge card (1,955 contracts, sized to the earlier run's −$1,955.68) carries the window chip "Example hedge · earlier run", and S11's "1,955 ≤ $1,955.68" is consistent within those frames. Don't put main's −$1,923.43 next to 1,955 contracts: that reads as an I1 breach. A re-capture needs DEMO_HEDGE re-sized first.
- **Ledger.** The bike-shop hedge is not booked to a ledger, because the demo business has no ledger tab. S15 shows **taxi's** books, with the chip "Simulated books · taxi fleet".
- **Naming.** Never name the real bar. The Jeffrey isn't ours, so leave it out.

## Scene table

Times are from the recorded VO (`assets/vo/user.m4a`, synced with `vo-sync.py --starts …`; the silence method mis-split two pauses, so the starts were set by hand from the pause map). The placeholder (`vo-tts.py`) ran 98.6 s.

| ID | Time (s) | VO | Caption (keywords) | On screen | Source for numbers |
|---|---|---|---|---|---|
| **Hook** | | | | | |
| S1 | 0.0–3.9 | Rain on a Saturday empties the shop. | **Rain.** · on a Saturday | Graphic: storefront in rain, OPEN → CLOSED | — |
| S2 | 3.9–8.1 | A home game could crowd the street, or it might not. | **Game night.** · Or it might not. | Graphic: arena lights, crowd fills then drains | — |
| S3 | 8.1–13.4 | Either way, as an owner, your week swings, and you can't plan around it. | **Revenue swings.** · Daily revenue · illustrative | Graphic: illustrative revenue line, next week as "?" | — |
| **Principles** | | | | | |
| S4 | 13.4–24.9 | Offset is built on four principles. Measured, not guessed. Built for steady income. The owner's call, every time. And interpretable, human-facing. | **Built on four principles** | Shield + 2×2 cards, all four held; each number lights as it's named | — (slide wording) |
| **What Offset does** | | | | | |
| S5 | 24.9–29.5 | Offset measures that swing in real dollars, from your own revenue. | **The swing, in real dollars,** from your own revenue. | Shield, rail Measure → Match → Propose | — |
| S6 | 29.5–35.3 | It finds a Kalshi contract that pays out when that risk hits. And you decide. | Finds a **Kalshi** contract that pays out when that risk hits · **Your call.** | Rail lights; "You decide" pill | — |
| **Demo** | | | | | |
| S7 | 35.3–41.7 | Here's a bike shop with fictional sales but real weather. Upload its daily revenue. | A bike shop. Fictional sales, **real weather.** · Upload daily revenue: **1,004 days** · chip *Fictional shop · synthetic sales · real weather* | `shot-01` | shot-01 (unchanged on main) |
| S8 | 41.7–48.4 | Rain costs it nearly $2,000 a day, and that holds up on data the model never saw. | Rain costs nearly **$2,000/day** · Holds up on data the model never saw: **−20.4%** · tag #1 | `shot-02` research table, Rain row | shot-02b (−$1,955.68, −20.4%); main live −$1,923.43, −20.4% |
| S9 | 48.4–62.6 | Knicks games? No real effect. In our research we tested about forty risks like this, and most were noise. And a fake effect we planted lands inside the model's range, so the test is reliable. | Knicks games: **no real effect.** · **About 40 risks** tested in our research · most were noise · Taxi model check: a planted **$500** lands inside the 90% interval. · **Coverage 96%** over 50 trials: a reliable test. · tag #1 | `shot-03` declined list + `shot-04` taxi model check; number line | About 40: `docs/RESEARCH.md` on main ("about 40 experiments"; the team's research, not this upload). $500, −$4,085.85, $796.42, 96%, 50: shot-04 |
| S10 | 62.6–69.6 | The desk picks Kalshi's rain contract for Central Park, the same weather station we measured with. | Kalshi · **Central Park** rain · Settles on the **same station** we measured · chip *Example hedge · earlier run* | `shot-06` header; ring ticker → Central Park → ticker; card with the Rain row's market cell | DEMO_HEDGE (KXRAIN-26OCT28-NYC, on screen only) |
| S11 | 69.6–77.8 | It buys only enough contracts to cover the measured loss, and not more, and shows the full cost up front. | **1,955 ≤ $1,955.68** (equation) · Full cost up front: premium **$675.41**, fee included · Expected cost ≈ $64.86 at the 31% NOAA rain rate · tag #2 | `shot-06` full card, payoff table | shot-06 / DEMO_HEDGE (earlier run) |
| S12 | 77.8–88.2 | But not every risk gets a hedge. For a taxi fleet, rain looked big last year, then almost vanished. So Offset says no, and explains why. | Not every risk gets a **hedge.** · Taxi fleet, rain: **+$2,080/day** last year, **+$228** lately · **Says no,** and explains why: no open market · not reliable · tag #4 | `shot-07` taxi declined card, DECLINED stamp | shot-07 (unchanged on main) |
| S13 | 88.2–93.3 | And nothing happens until the owner approves. | **Owner only.** Nothing happens until you approve. · chip *Example hedge · earlier run* · tag #3 | `shot-09` → `shot-10` | — |
| S14 | 93.3–99.8 | Every proposal, decline and approval is logged with its reasons. | Every decision logged **with its reasons** · tag #4 | `shot-11` decision log | — |
| S15 | 99.8–109.7 | Approved hedges go into the books, and Offset even caught a deposit that came in eighty-nine cents short, and named the fee as the cause. | **$0.89 short** · fee found · chip *Simulated books · taxi fleet* · tag #4 | `shot-12` taxi ledger + three-way check | shot-12/13 ($0.89, unchanged on main) |
| **Close** | | | | | |
| S16 | 109.7–114.8 | Offset. Steady income in an unsteady week. | **Offset** / Steady income in an unsteady week. | Logo lockup | — |

## Shot list (capture team)

Run `make demo` (offline, `DEMO_AS_OF` week of Oct 26) at a 1440×900 viewport. Hide the cursor except in shot-09, and capture light theme at 2x. To reach the wizard, use a fresh db, or click "Re-run setup" on the dashboard.

| File | Screen and state |
|---|---|
| `shot-01-wizard-upload.png` | Setup wizard, step 1 ("Your business"). The "Upload your revenue" button is pressed after choosing `hudson_bike_co_daily_revenue.csv`. The status line shows "Hudson Bike Co. · 1,004 days · 2024-01-01 → 2026-09-30" and the "Uploaded · sample" badge. |
| `shot-02-wizard-research-table.png` | Step 2 ("Your risks"), after the "Running analysis…" bar finishes. The full research table, with the Rain row's FOUND verdict and forest plot visible. Also grab a tight crop of the Rain row (`shot-02b-rain-row.png`). |
| `shot-03-wizard-declined-list.png` | Step 2, scrolled to "Declined, and why", showing Hot / Knicks home game / Knicks win as "Not distinguishable from zero". |
| `shot-04-model-check.png` | Dashboard, taxi selected: the "Model check" subsection (Planted, Recovered, 90% interval, Coverage, Holdout R²). |
| `shot-05-hedge-card-header.png` | Step 4 ("Your hedges"), after "Send to the desk →" and "Pricing protection…": a crop of the hedge card header showing "Will it rain in Central Park on Oct 28?" and `KXRAIN-26OCT28-NYC · series KXRAIN`. |
| `shot-06-hedge-card-full.png` | The same card, uncropped: the "Buy YES · 1,955 contracts @ 33¢ · premium $675.41…" line, the payoff bars, the "Both outcomes, including the premium" table and "Expected cost ≈ $64.86". Status: Proposed. |
| `shot-07-taxi-declined-card.png` | Dashboard, taxi, **after clicking Run desk** (the sample-week banner must be gone). The rain card in **Declined**, with "No market" and "Unstable" and the Last year / Recent months comparison. |
| `shot-08-not-hedged-list.png` | Dashboard, taxi: the left panel's "What moves revenue", with the exposures and the "measured, not hedged" list (game results, not significant). Keep the "Real" badge in frame. |
| `shot-09-approve-hover.png` | The bike hedge card (wizard step 4 or demo dashboard), chip "Proposed · only you can approve", cursor hovering **Approve**. |
| `shot-10-approved-chip.png` | The same card after clicking Approve, with the chip reading "Approved by you". |
| `shot-11-decision-log.png` | Dashboard on Hudson Bike Co. (demo business) after the approval: the Decision log panel with "Approval · owner" on top and "Proposal · desk" under it, timestamps visible. |
| `shot-12-ledger.png` | Dashboard, taxi, "Books & reconciliation" tab: the ledger table with the "Simulated" / "Booked on approval" badges and the simulated note visible. |
| `shot-13-reconcile.png` | The same tab after clicking **Run reconciliation**: the "Three-way check" table with the ⚠ flagged row (−$0.89), and the explanation and "Question for you" below. |
| `shot-14-labels.png` | A tight crop of the dashboard header area showing the "Estimated" or "Real" badge and the "No real orders are placed" badge. |
| `shot-15-dashboard-wide.png` | (B-roll, optional) The full taxi dashboard after Run desk, used as a wide establishing frame behind S11 or S15. |

**Verify before locking captions** (done for the 2026-10-25 captures; see `assets/verify.md`): confirm $0.89 in shot-13 and the model-check values in shot-04 match the captions. If shot-07 doesn't show +$2,080 and +$228 (the cache may have been re-warmed), retype S11 from the screenshot.

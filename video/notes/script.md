# Offset: product video script

**Runtime:** 0:90 (hard cap 1:45) · voiceover plus keyword captions over Motion graphics and real screenshots. The narration text is in `vo.txt`.

**Logline:** A rainy Saturday or a home-game night can swing a small business's week. Offset measures that swing in dollars, prices protection on Kalshi, says no when the risk isn't real, and leaves every decision to the owner.

## Ground rules for the edit

- **Numbers.** Every number in a caption or the VO is cited in the *Source* column. If a figure isn't cited, it must be read off the screenshot ("[from screenshot]"), never typed in.
- **Labels (I6).** Hudson Bike Co. is **fictional**, with synthetic sales on real weather. The taxi ledger and bank statement are **simulated**. Keep the app's own badges visible in frame, and add a small caption chip where noted.
- **Scripted flow.** The upload → research → hedge flow is a scripted demo whose numbers come from a real offline run (`docs/UPLOAD_AND_RESEARCH.md` §1). Never caption it "live" or "computing now".
- **Ledger.** The bike-shop hedge is not booked to a ledger, because the demo business has no ledger tab. S14 shows **taxi's** books. Its caption says "approved hedges are booked", not "this hedge was booked".
- **Naming.** Never name the real bar. The Jeffrey isn't ours, so leave it out.

## Scene table

The VO runs at about 150 wpm. Captions are keywords that back up the VO, not a transcript.

| ID | Time (s) | VO | Caption (keywords) | On screen | Motion idea | Source for numbers |
|---|---|---|---|---|---|---|
| **Hook** | | | | | | |
| S1 | 0–3 | Rain on a Saturday empties the shop. | **Rain.** | Motion graphic: a storefront, rain streaks start | The word drops in with the rain, and the storefront dims | — |
| S2 | 3–6 | A home game packs the street, or it doesn't. | **Game night.** | Motion graphic: arena silhouette, lights flick on | The lights flash on the beat | — |
| S3 | 6–10 | Either way, your week swings, and you can't plan around it. | **Revenue swings.** | Motion graphic: a daily revenue line wobbling | The line jitters and shakes once on "swings" | — |
| **What Offset does** | | | | | | |
| S4 | 10–14 | Offset measures that swing in real dollars, from your own revenue. | **Measure** | The Offset shield (`frontend/public/offset-logo.svg`), then the rail *Measure → Match → Propose* | The shield draws on, the pills stagger in, and "Measure" lights | — |
| S5 | 14–19 | Then it finds a Kalshi contract that pays when it hits. And you decide. | **Match → Propose → You decide** | The same rail, with a green *Owner decides* pill added | The pills light in turn; "You decide" lands bold | — |
| **Demo** | | | | | | |
| S6 | 19–23 | Here's a bike shop: fictional sales, real weather. Upload its daily revenue. | **1,004 days** · chip *Fictional shop · real weather* | `shot-01` wizard step 1 | The screenshot rises into a device frame; the day count ticks up to 1,004 | `docs/UPLOAD_AND_RESEARCH.md` §2 |
| S7 | 23–30 | Rain costs it about $1,956 a day, and that held up on data the model never saw. | **−$1,955.68/day** · **Unseen: −20.4%** | `shot-02` / `shot-02b` research table, Rain row | Push-in on the row; the number counts up; the forest whiskers draw; a FOUND stamp lands | `frontend/lib/demoScript.ts` RESEARCH_ROWS; `docs/PITCH.md` 0:35 beat |
| S8 | 30–35 | Knicks games? Nothing there. And a planted test effect lands inside the model's interval, so the check is honest. | **Knicks: no effect** · **Planted $500, inside the 90% interval** | Split: `shot-03` declined list and `shot-04` model check | The list slides in, then the panel flips in; ring on the 90% interval and coverage lines (the point estimate is off, so don't claim it was "found") | `demoScript.ts`; `docs/PITCH.md` 1:40 beat ($500). Recovered and coverage are [from screenshot] |
| S9 | 35–40 | The desk matches Kalshi's Central Park rain contract, the same station we measured. | **KXRAIN · Central Park** | `shot-05` hedge card header | The ticker types on; a line links the Rain row to the card | `demoScript.ts` DEMO_HEDGE |
| S10 | 40–48 | It sizes protection to the measured loss and never more: 1,955 contracts, with the full premium shown up front. | **1,955 ≤ $1,955.68** · **Premium $675.41** · **Exp. cost ≈ $64.86** | `shot-06` full hedge card | The card slides in, a ≤ sign snaps between the numbers (I1), the payoff bars grow, and the premium column highlights | `demoScript.ts` DEMO_HEDGE; `docs/UPLOAD_AND_RESEARCH.md` §3 |
| S11 | 48–59 | But not every risk gets a hedge. For a taxi fleet, rain looked big last year, then almost vanished. So the desk says no, and shows you why. | (add +$2,080 → +$228 once shot-07 confirms) · **DECLINED: no market · unstable** | `shot-07` taxi declined card; cut-in `shot-08` | A beat of black, then the card drops in; $2,080 morphs to $228; the red DECLINED stamp lands with a shake. **Hold 1s, the trust moment** | `docs/DEMO.md` "Real pipeline today"; `docs/PITCH.md` 0:10 beat |
| S12 | 59–63 | And nothing happens until the owner approves. | **Owner only** | `shot-09` then `shot-10` | The cursor clicks Approve; the chip flips from amber to green | — |
| S13 | 63–67 | Every proposal, decline and approval gets a receipt in the log. | **Every decision logged** | `shot-11` decision log | The new row slides in from the top; the actor tags highlight | `demoScript.ts` demoLog |
| S14 | 67–73 | Approved hedges are booked to a real ledger, and reconciliation catches a deposit that came in short, and names the fee as the cause. | **Ledger** · **Short deposit = the fee** (add −$0.89 once shot-13 confirms) · chip *Simulated* | `shot-12` then `shot-13` (taxi books) | Rows cascade in; the three columns light; the mismatch row flashes amber | `docs/PITCH.md` 1:15 beat; `backend/tests/books/test_reconcile.py` |
| **Trust** | | | | | | |
| S15 | 73–83 | The desk never approves its own hedge. Every number comes from a tool, not the AI. And anything estimated or simulated says so. | **Never self-approves** · **Tool-sourced numbers** · **Labeled estimates** | Brand background with insets from `shot-09` and `shot-14` | Three lines stack, each ticked green as the VO lands | — (spec §1 I4, I2, I6) |
| **Close** | | | | | | |
| S16 | 83–90 | Offset. Steadier weeks. Your call. | **Offset** / **Steadier weeks. Your call.** | Logo lockup | The shield settles, the wordmark wipes on, the tagline fades; hold | Tagline from `SetupWizard.tsx` |

**Timing:** hook 0–10 · what 10–19 · demo 19–73 · trust 73–83 · close 83–90, for a total of 90s. The VO is about 220 words, about 88s at 150 wpm (`vo.txt`). It speaks none of the unverified figures ($0.89, model-check coverage, +$2,080/+$228), which stay out of captions until the screenshots confirm them. Trims already applied: S7 7s, S10 8s, S11 11s.

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

**Verify before locking captions:** confirm $0.89 in shot-13 and the model-check values in shot-04 match the captions. If shot-07 doesn't show +$2,080 and +$228 (the cache may have been re-warmed), retype S11 from the screenshot.

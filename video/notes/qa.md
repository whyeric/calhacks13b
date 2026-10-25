# QA punch list: pass 1

Pass 1 ran on 2026-10-25 against `app.js` before the S01..S16 split. The render is 92.47 s at 1920×1080.

**Method**
- Stills every 0.5 s: `out/qa/pass1/` (185 frames). Contact sheets: `out/qa/sheets/`.
- 60 fps bursts of 10 frames around 13 transitions: `out/qa/bursts/` and `out/qa/bursts_strip_*.png`.
- A full 30 fps render, frame-diffed to find pops. Spike times are listed under Engine.
- All times are positions in the rendered timeline. The page schedule is S1 0.00, S2 3.09, S3 6.30, S4 10.34, S5 14.52, S6 19.11, S7 24.66, S8 31.60, S9 38.68, S10 44.16, S11 52.74, S12 63.40, S13 66.77, S14 70.99, S15 78.80, S16 87.12.

**Severity:** P0 is broken or wrong. P1 is visibly unpolished. P2 is nice to have.

**Totals:** 2 P0 · 25 P1 · 25 P2.

## Accuracy check (numbers on screen against assets/verify.md and onscreen-values.json)

Every caption number matches the screenshots:
- S6: 1,004 days, 2024 → Sep 2026
- S7: −$1,955.68/day and −20.4%
- S9: KXRAIN-26OCT28-NYC
- S10: 1,955 contracts, $1,955.68, $675.41 and $64.86
- S11: +$2,080 and +$228 per day
- S14: −$0.89

No P0 accuracy problems in the captions.

> verify.md now agrees: $500 is inside −$4,085.85..$796.42, so the S8 caption and VO are supported. The real S8 risk is the large "Recovered −$1,644.72" next to it, and that this taxi panel sits in a bike-shop beat (see S08). shot-12 has no "Booked on approval" badge, which strengthens the S14 P0.

---

## engine (builder)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | every boundary from S6 to S15 | The scene fade out is 0.3 s with `ease: "in"` (quint), so almost all of the drop happens in the last ~80 ms. The fade in is 0.35 s ease-out quint. At 60 fps this reads as a blink through black, not the 600 ms crossfade in brand.md. Frame diffs peak at 22–42 per frame. | In the scene-fade block (`app.js` ~L540), use `ease: "move"` on both sides, with out 0.3 s and in 0.4 s (≈ 700 ms through dark). Or crossfade by overlapping the outgoing and incoming scenes by 0.3 s. |
| P1 | 4.5 → S5 14.52 · S9 → S10 44.16 | The same visual (the rail, the hedge card) dips to black and comes back identical. This is the worst blink (diff 41.6 at 44.1). | Add a per-scene flag such as `continue: true` that skips the fade out of the previous scene and the fade in of this one, so both scenes share the frame. |
| P1 | 31.07, 63.97, 66.13, 77.20 (and every ring start) | The ring dim (outer shadow at 55%) arrives with the 0.4 s ease-out quint. About 80% of the darkening lands in 2 frames, so the screen "flashes dark". | Drive the dim with `ease: "move"` over 0.3 s, separate from the ring outline, which can keep its 0.4 s scale. |
| P1 | 40.0, 42.0, 43.0 (and others) | The ring box sits low: text touches the ring's top edge, with about 25 px of empty space under it (title and ticker rings in S9, the reasons ring in S11). | Either the anchors in shots.json are off by about half a line, or `pad` should be applied around the text's visual box. Check `A()` for the `dsf` and `hy` math on cropped shots. A quick fix is to shift the box up by about 0.4 × its height. |
| P1 | 19.5, 24.0, 39–52, 71–78 | The window-bar label chips ("Fictional shop · synthetic sales · real weather", "Simulated settlements & bank", "Scripted demo · real offline run") are about 16 px. These are the I6 labels the script requires, and they are too small to read on a laptop or projector. | Use the brand badge style: 22 px/600, +0.04em. Or repeat the label as a caption chip under the window. The script already asks for a caption chip in S6 and S14. |
| P2 | all captions | Captions start at x=210, while titles, the logo and the rail start at x=160. That gives two left edges. | Pick one gutter, either 160 or the window's 210, and use it for captions, titles and eyebrows. |
| P2 | all captions | Captions reveal word by word with a 70 ms stagger and a 12 px rise. brand.md: "Words aren't typed out". | Fade the caption in as one line (opacity plus 12 px, 500 ms), and keep the per-number count-up. |
| P2 | 23.0, 26.0, 45.0, 75.0 | Counted numbers switch to Plex Mono inside Plex Sans. "1,004" and "$1,955.68" get a wide mono comma and look gapped next to the sans text. | Use Plex Sans with `font-variant-numeric: tabular-nums` for inline numbers, and keep mono for the ticker chip only. |
| P2 | window top 64 px | The window top bar sits at y=64, inside the 72 px top safe area. | Use y ≥ 72. |
| P2 | 92.47 end | The video ends on a hard cut from the end card. | Fade to `#0f1a14` over the last 0.6 s, or hold 0.5 s longer. |

## S01 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P2 | 0.00–0.4 | The first frame is an empty gradient (dead frame) before the storefront fades in. | Start with the storefront at about 30% opacity at t=0, so the thumbnail and frame 0 aren't blank. |

## S02 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P2 | 3.1–3.9 | Dark stadium with no title for about 0.8 s. The VO starts at 3.39. | Bring the title in at VO start (3.4), or light the first lamp at 3.4. |

## S03 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 7.0–7.6 | The orange leading dot detaches from the line tip while the line draws. At 7.5 it is about 30 px right of and below the line end. | Compute the dot position from the same dash progress as the path (`getPointAtLength(len·p)`), not from a separate tween. |

## S04 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 10.5–11.2 | The "→" arrows of the rail are visible before their pills, so two arrows float in empty space while the logo is still drawing. | Tie each arrow's opacity to the pill that follows it, or stagger the arrows after the pills. |
| P2 | 10.5 | A tiny orange stroke stub floats at the top left (logo path start) for one frame or more. | Start the logo's dash at 0 with the line cap hidden, or fade the logo in during the first 100 ms. |

## S05 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 14.3–14.9 | The rail and logo dim to black and come back in the same place (see engine: continuity). | Keep S4's rail on screen and only light Match, Propose and You decide. |
| P2 | 18.0 | The caption "You decide." repeats the pill label right above it. | Drop the caption, or make it "The owner decides" to echo the green pill. |

## S06 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 19.5–21.5 | The window's bottom edge cuts through the Back and Next buttons. | Frame the shot so it ends above the buttons, or show them whole. |
| P1 | 19.5 onward | The fictional-shop label exists only as the 16 px bar chip (see engine). The script asks for a caption chip *Fictional shop · real weather*. | Add the chip at 22 px under the window, next to the caption. |
| P2 | 22.0 | Mid push-in, "Offset" and "Step 1 of 5 · Yo…" are clipped at the window edges. | Ease the push-in so it stays at z=1 until the ring has faded, then move in. |

## S07 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 25.5–31.6 | The push-in crops out the Risk column, so the "Rain day" row label is never visible while the caption says "Rain". The right crop cuts "FOUND" to "FOUI". | Center the focus on the Rain row with a box that spans from the Risk column to the Verdict (z ≈ 1.3, not about 1.6), or pan right before the verdict ring. |
| P1 | 31.0–31.6 | The FOUND ring appears 0.6 s before the scene fade and is clipped by the window edge. | Pan to the verdict at about 29.8, and give the FOUND ring at least 1.2 s before the fade. |
| P2 | 24.9 → 25.5 | The label chip changes from "Fictional shop · synthetic sales · real weather" to "Fictional shop · real weather". | Use one wording for the bike shop throughout. |

## S08 (polishA)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 32.0–38.6 | The declined list is a short, wide strip (1000×190 px, 16 px text) at the top left. The rest of the left half is empty, and the two windows aren't aligned (tops at 250 and 96). | Scale the list up to about 1.6× (≥ 24 px text), crop to the three rows, and align both windows on a shared top and centerline. |
| P1 | 35.5–38.6 | The model check is taxi data ("Taxi · real data", 16 px chip) inside the bike-shop story, and "Recovered −$1,644.72" is big next to "$500". Viewers may read this as a failed check. | Add a caption line or chip "Model check · taxi data". Keep the ring on interval and coverage (already done). Optionally dim the Recovered figure, but don't crop it. |
| P2 | 34.5 | During its slide-in, the model-check window's right edge is at x=1850, inside the 96 px safe area. | End the slide at x ≤ 1824 throughout. |
| P2 | 35–38 | The unrounded R² (0.23632632956599398) is the most eye-catching number. | Crop above the R² line (it stays honest, because the script doesn't cite it). |

## S09 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 39.0–44.0 | The "Buy YES … pays $1,9…" line runs off the window's right edge, and the bars run off the bottom. | Use z ≈ 1.0 here, or crop to the header (title, ticker) as the script says (`shot-05`). |
| P1 | 40.0, 42.0 | The title and ticker rings sit low and their top edge touches the text (engine ring offset). | See engine. |
| P2 | 38.7–44 | The script's "line links the Rain row to the card" (same station) isn't shown. The VO says "same station we measured". | Optionally add a small ring or chip "Settles on Central Park, the station we measured", taken from the card's checklist. |

## S10 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 44.0–44.6 | The dip to black and back on the same card is the hardest blink in the film. | See engine continuity. Pull back from S9's framing with a camera move instead. |
| P1 | 49.5–52.7 | Reject and Approve are cut by the window's bottom edge. | Frame to end above the action row, or include it fully. |
| P2 | 51.5 | The expected-cost ring overlaps the "(" of the following text. | Add 4–6 px of right padding to the `expected_cost` box. |

## S11 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 59.5 | The DECLINED stamp has a slight rotation and a shake. brand.md: "Nothing bounces, spins, or flashes… stamps, not fireworks". | Keep the tilt (it reads as a stamp) but remove the shake. Use scale 0.96 → 1 over 250 ms. |
| P2 | 53.0–53.5 | About 0.8 s of empty dark (the intentional beat) plus the fade from S10 makes about 1.1 s of nothing. | Trim the beat to about 0.5 s. |
| P2 | 59.9–63.1 | The frame is completely static for 3.2 s (the trust hold). Holding is right, but with no motion it looks frozen. | Add a slow Ken Burns (1.00 → 1.02) during the hold. |
| P2 | 59.5–63 | The caption "Declined: no market · not reliable" paraphrases the on-screen reasons, which read "No open market" and "Not reliable: …". | Use the app's own words: "Declined: no open market · not reliable". |
| P2 | 54–63 | The window's bottom crop cuts mid-row ("-1885.02"), and the `shot-08` cut-in from the script isn't used. | Crop above the debug rows. Optional `shot-08` cut-in. |

## S12 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| **P0** | 66.0–66.8 | **The chip flip that pays off the scene, "Proposed" → "Approved by you", is cropped off the window's right edge.** Only "Proposed · only y" and then a sliver "A" are visible. The `status_chip` focus box puts the chip outside the viewport. | Focus on a box that contains the whole chip (`[0.70, 0.02, 0.29, 0.06]` or wider) with z ≤ 1.6. Or show the chip as a crop inset. Check that the green ring is fully inside the window. |
| P1 | 65.2–65.6 | After the click, the camera jumps (diff 23 at 65.37) to a blank white area with the outcome table, before panning to the chip. | Pan straight from the Approve button to the chip with the move ease over 0.7 s, without passing through the payoff table. |
| P1 | 63.5–65.2 | The push-in crops words mid-letter ("ts available", "asured exposure", "l payout at…"). | Frame the action row with "Only you can approve protection." on the left, at z ≈ 1.6. |

## S13 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 67.0–70.9 | The "Decision log" heading is half hidden under the window bar. | Shift the framing down by about 40 px so the heading shows fully. |
| P2 | 69.0 | Both rings are visible during the handoff (two highlights at once). | Fade out the first ring before the second starts (the gap is ≥ 0.1 s). |
| P2 | 67–70 | The script's "new row slides in from the top" isn't animated. | Optional: slide the approval entry in. |

## S14 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| **P0** | 71.5–74.5 | **I6 and overclaim.** The caption reads "Ledger: every approved hedge is booked" over taxi's ledger, but every row there is simulated and none is an owner-approved hedge (verify.md). The only Simulated label is the 16 px window chip plus the small row tags. The script requires the caption chip *Simulated*. | Add a 22 px **Simulated** chip beside the caption, and reword it to "Ledger: approved hedges get booked here (simulated history)". |
| P1 | 74.6–75.0 | The cut from the ledger to the reconcile panel is a jump (constant diff of 7 per frame, a re-frame without easing). | Use one camera move with the move ease over 0.8 s, or a 250 ms crossfade swap. |
| P2 | 75.0–75.5 | The caption counts up "−$0.00 → −$0.89", and "Deposit −$0.89 short" is a double negative. | Use "Deposit $0.89 short: it's the fee" with no count-up for numbers under $1. |
| P2 | 75–78 | A half-cut "Simulated · settlements…" banner under the window bar and ledger slivers at the left. | Crop tighter to the three-way check panel. |

## S15 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P1 | 82–87 | The insets are illegible. The "Buy YES …" strip is about 15 px and truncated ("pays"), the "Simulated · settlements and the bank state" pill is about 13 px and truncated, and "Uploaded · sample" wraps to an orphan second row. | Use fewer, bigger insets, one per line, ≥ 22 px text: line 2 "premium $675.41" plus the `from size_hedge` tag; line 3 two chips side by side ("Simulated", "Uploaded · sample"). |
| P1 | 79.5–87 | Inset 1 is mostly an empty white bar with two small buttons and a cursor on Approve. It says "the owner clicked", which is the opposite of the beat. | Crop to the "Proposed · only you can approve" chip plus the buttons, with no cursor. |
| P2 | 84.3–86.8 | Static for 2.5 s. | Fine as a hold. Optional 1.00 → 1.02 drift. |

## S16 (polishB)

| Sev | Time | Issue | Fix |
|---|---|---|---|
| P2 | 87.2–87.6 | A lone orange stroke stub draws in the middle of an empty frame before the shield takes shape. | Start the stroke at the shield's top point with a round cap, or fade the mark in over the first 200 ms of the draw. |

## Pacing against the VO (timing.json starts mapped through the page schedule)

The captions land within ±0.6 s of their VO phrases in every scene except these:
- **S6:** "Upload daily revenue" appears at 20.0, about 1.5 s before the VO says "Upload".
- **S12:** The chip flip happens at 66.0–66.8, after the VO ends at 65.97. That's OK once P0 is fixed, but consider moving it 0.4 s earlier.

---

# Pass 2: S01–S08 (polishA round 1)

Pass 2 was rendered on 2026-10-25 with polishA's `stills.mjs`. Stills every 0.5 s from 0 to 37 s are in `out/qa/pass2/`, contact sheets in `out/qa/sheets2/`, and caption-swap frames in `out/qa/pass2/swap*`.

The schedule: S1 0, S2 2.99, S3 5.95, S4 9.74, S5 13.77, S6 18.21, S7 23.51, S8 30.20.

polishA was still editing during this pass, so a few frames come from different revisions. I didn't judge transitions, because builder hasn't announced the crossfade fix yet.

## Pass 1 items resolved
- S03: the leading dot now stays on the line tip. The "Daily revenue · illustrative" label and the next-week "?" row read well.
- S04: the arrows no longer float. The connectors draw between the pills.
- S05: the rail stays put and the pills light in turn. The fourth pill re-centers the rail smoothly.
- S06: the fictional-shop chip is now a 22 px caption chip. Back and Next are whole at 19.6. The caption reads "A bike shop. Fictional sales, real weather."
- S07: the Risk column and "Rain day" are visible. The pan right lands on "FOUND · hedgeable".
- S08: the declined list is now big (about 28 px). The windows are aligned. The panel is labeled "Taxi fleet · real data", the caption says "Taxi model check…", R² is cropped out and Recovered is dimmed. The interval number line plots $500 at the right spot (−4,085.85 to 796.42 puts $500 at 0.94).
- Accuracy: every number matches verify.md, including 1,004 days, −$1,955.68/day, −20.4%, $500, −$4,085.85 to $796.42, and 96% · 50 trials.

## Open, pass 2

| Scene | Sev | Time | Issue | Fix |
|---|---|---|---|---|
| S08 / engine | P1 | 32.40, 35.40–35.55 | **Caption swaps overlap.** The outgoing caption fades out (0.3 s) while the next one fades in on the same baseline, so for about 0.2 s two lines of text sit on top of each other ("Knicks games: nothing there." with "Taxi model check…", then "Taxi model check… lands inside the" with "Coverage 96% over 50 trials"). S7's swap at 27.9 is clean (sequential), so match that. | Start the next caption's entry at or after the previous `out` + 0.3. Or engine: make `caption()` take a `after: prevCaption` so the entry waits for the exit. |
| S07 | P1 | 30.0–30.2 | The FOUND ring lands about 0.2 s before S8 begins, so the verdict, the payoff of the scene, is on screen for a blink. The VO "held up on data the model never saw" ends at about 29.85. | Pan right and ring FOUND at about 29.0 (as the VO says "never saw"), or extend S7's tail pad by about 0.6 s. |
| S06 | P1 | 19.6 | The new framing clips the "Which business are we protecting?" heading under the window bar, and the lower 40% of the window is empty below Back and Next. | Frame about 60 px higher in the image (start above the heading), or crop the bottom so the buttons sit near the bottom edge. |
| S07 | P2 | 24.0–25.0 | The caption "Rain:" sits alone for about 1 s before the number arrives. | Reveal "Rain:" with the number, or start the count 0.4 s earlier. |
| S07 | P2 | 25.0, 29.0 | The count-up shows interim values ("−$1,873.88/day", "−9.2%") that a still or thumbnail could capture. | Count over at most 0.5 s, or count only the last 20% (from −$1,600 to −$1,955.68). |
| S07 | P2 | 29.5 | The caption is still counting "−20.3%" after the camera has panned away from the Unseen column. | Finish the count before the pan. |
| S08 | P2 | 32.0 | The model-check window slides in with a slight 3D tilt. brand.md says nothing spins. | Slide plus fade only. |
| S06 | P2 | 21.5 | The push-in clips "Step 1 of 5 · Your bus…" at the right edge. | Stop the push before the header leaves the frame, or the header can go. |
| S05 | P2 | 17.5–18.2 | The caption "You decide." repeats the "You decide" pill. | Keep one of them. |
| S01 | P2 | 0.00 | Frame 0 is an empty gradient (dead frame / thumbnail). | Start with the storefront at about 30%. |
| S04 | P2 | 10.5 | The wordmark wipe shows a partial "Of" with a clipped "f" edge. | That's fine for a wipe. Optional: add a feathered mask edge. |

**Pass 2 S01–S08 totals:** 0 P0 · 3 P1 · 8 P2. Down from 9 P1 in pass 1.

### Pass 2b re-check after polishA's round-1 report (`out/qa/pass2b.png`)
- S06 framing at 19.6: **resolved.** Header, tabs and card are whole, and the buttons are out of frame. P2 still open: the push-in at 21.5 cuts the Offset logo and tagline at the window bar.
- S07 FOUND: **resolved.** The ring is up from about 29.2 into the S8 crossfade (≥1 s). P2 still open: at z≈1.22 the full table text is small (about 15 px). It's acceptable because the ring isolates the Rain row.
- S08 swap at 32.4: **resolved** (sequential).
- **S08 swap at 35.40–35.55: still open (P1).** "Taxi model check: … interval." and "Coverage 96% over 50 trials:" are text-on-text for about 0.15 s.

**S01–S08 now:** 0 P0 · 1 P1 · 9 P2.

---

# Pass 2: S09–S16 (polishB round 1)

Pass 2 for S09–S16 used stills every 0.5 s from 37.0 to 90.5 s, in `out/qa/pass2b/s916/`, with contact sheets in `out/qa/sheets3/`.

The schedule: S9 37.03, S10 42.26, S11 51.79, S12 63.25, S13 67.02, S14 70.99, S15 78.55, S16 86.52. The VO starts are S9 37.23, S10 42.51, S11 52.69, S12 63.55, S13 67.22, S14 71.19, S15 78.75, S16 86.92.

I didn't judge crossfades, because builder hasn't announced the fix. The S11→S12 window ghosting at 63.5 and the S14 residue at 79.0 are the engine crossfade issue.

## Accuracy (special checks)

**S10, the I1 equation.** The S10 numbers are all correct:
- "1,955 contracts · pays $1,955.00 if it rains ≤ $1,955.68 measured loss on a rain day".
- "Full premium up front: $675.41, fee included".
- "Expected cost ≈ $64.86 at the 31% NOAA rain rate".
- The ≤ sign sits between contracts and dollars, but the "pays $1,955.00" sub-label makes the comparison honest.
- It lands at 46.5, on the VO "1,955 contracts".

**S14, the fee connector.** The S14 values are all correct:
- The ring is on "Expenses:Hedging:Fees $0.89" on the Oct 19 KXHIGHNY-26OCT20-T72 premium.
- The connector runs from that row to the note "equals the $0.89 fee recorded for hdg_s01".
- The flagged row reads $60 / $60 / $59.11, "⚠ Flagged · −$0.89".
- "Short by exactly the $0.89 fee, named as the cause" is supported.

**S14, Simulated labeling.** The window chip "Simulated settlements & bank" is now 22 px and legible. The per-row "Simulated" tags and "Simulated · bank statement" are readable.

**S11.** "+$2,080/day last year, +$228 lately" and "Declined: no open market · not reliable" both match verify.md.

**S15.** "tool · size_hedge" is a real tool (`backend/app/agent/desk.py`).

## Pass 1 items resolved
- **S12 P0:** "Approved by you" is now fully in frame with a green ring (66.5–67.0).
- **S09:** the title and ticker rings fit, and the station link card ("Measured in step 2 · Rain day · KXRAIN · NYC daily rain (Central Park…)") makes the "same station" claim.
- **S10:**
  - The payoff and the Approve row are no longer cut.
  - The expected-cost line is legible.
  - The "Premium $675.41" caption landing and the premium-column ring are good.
- **S11:** the stamp no longer shakes in the stills. The comparison rings are red, and the reasons use the app's own wording.
- **S13:** the approval row now slides in on top (67.5 → 69.5).
- **S15:** no cursor. There is one evidence card per line, and the lines are big serif with ticks.
- **S16:** the video ends with a fade to dark (90.0–90.5).

## Open

| Scene | Sev | Time | Issue | Fix |
|---|---|---|---|---|
| S14 | **P1** (was P0) | 71.5–74.5 | The caption "Ledger: every approved hedge is booked" sits over a ledger with no approved hedge, and every row is simulated. The Simulated labeling is now adequate, so this is no longer P0. The claim still reads as "this ledger shows approved hedges". | "Approved hedges get booked here (simulated history)". Or keep the app's sentence, but add "Simulated" as a caption chip next to it. |
| S14 | P1 | 78.3–78.55 | **The fee connector, the scene's payoff, is on screen for about 0.25 s.** It draws after the VO "names the fee as the cause" ends (about 78.2), then S15 starts at 78.55. | Draw the connector at about 77.0 (VO "names the fee"), and hold at least 1.2 s. Or extend S14's tail. |
| S14 | P1 | 77.0 | The note ring is mis-placed during the camera move. Its top edge cuts through the flagged row and its middle strikes through "$0.89 fee recorded for hdg_s01". | Start the ring after the camera settles (77.4), or ring the note box only after the move. |
| S15 | P1 | 79.5–86.0 | **The evidence cards are too small to read.** The chip text is about 13–15 px ("Proposed · only you can approve", "APPROVAL · OWNER", "Simulated · bank statement", "No real orders are placed"), and "tool · size_hedge" is about 12 px mono. Card 2 is truncated: "…premium $675.41 (" is cut at the card edge. | Scale each card about 1.6× so chip text is at least 22 px. Shorten card 2 to "1,955 contracts · premium $675.41", ending cleanly, plus a "size_hedge" tag at 22 px. There's room: the cards use about 290 px of an 800 px right column. |
| S10 | P1 | 48.0 | A ring sits on an empty white area (no content) for about 0.3 s while the camera scrolls to the payoff table. | Start the premium-column ring after the scroll settles (about 48.4). |
| S10 | P1 | 43.0, 45.5 | The bar ring is mis-registered mid-move. The box cuts through the middle of the unhedged bar and covers half the hedged bar. | Same fix: ring after the camera settles, or have the ring track the final framing. |
| S13 | P1 | 68.5–70.5 | The "Decision log" heading is clipped under the window bar (half-letters). At 70.5 the APPROVAL · OWNER ring is mis-registered and covers the timestamp, not the label. | Frame 40 px lower so the heading stays whole, or crop it out entirely. Ring after the scroll ends. |
| S12 | P1 | 64.0–65.5 | The push-in still crops words mid-letter ("ts available", "asured exposure", "l payout at the"). At 65.5 the camera drifts to an empty grey strip with a cursor. | Frame the action row with its left context ("Only you can approve protection.") or crop tight to the buttons. Pull back directly from Approve to the full card. |
| S12 | P1 | 66.5–67.0 | The "Approved by you" chip is now in frame, but it's about 11 px at this zoom, so the flip is hard to see. | Push in on the chip (z ≈ 2) for the flip, then pull back. |
| S16 | P1 | 86.9–89.0 | **Pacing.** The VO says "Offset." at about 87.0, while the frame shows only a stroke stub. The wordmark completes at about 89.0, under "Your call." | Have the shield fill and wordmark land by about 87.5, the tagline on "Steadier weeks" (about 88.0), and "Your call." bold at about 88.8. |
| S11 | P1 | 54.5 | The title "Not every risk gets a hedge." overlaps the incoming card for about 0.3 s, making text on text over "$2,080.20". | Exit the title before the card enters, or move the card in below the title. |
| S11 | P2 | 55.0–59.0 | The card is mostly empty pink and white space (masked reveal), which can read as a broken screenshot. | Reveal title and sentence first, or crop to the comparison block. |
| S09 | P2 | 37.5–42.0 | "…pays $1" is truncated at the window's right edge during the header beat. | Fine while the ring is on the header. Optional: end the crop before "· pays". |
| S10/S11/S14 | P2 | 45.5, 46.0, 48.5, 55.5, 75.0 | Count-ups show interim numbers ("1,007", "1,950", "$553.82", "+$1,735/day … +$190", "−$0.81"). | Count only the last 15–20%, or at most 0.5 s. |
| S14 | P2 | 75.0–77.0 | "Deposit came in −$0.89 short" is a double negative. Ledger slivers ("emiums", "es") show at the left. | "Deposit came in $0.89 short". Crop to the three-way panel. |
| S12 | P2 | 66.5 | The chip flips after the VO ends (about 65.8). | Move the flip about 0.5 s earlier. |
| S16 | P2 | 87.0 | A lone stroke stub draws in empty space. | Fade the mark in during the draw, or start at the shield's top point. |

**Pass 2 S09–S16 totals:** 0 P0 · 11 P1 · 6 P2. Pass 1 had 2 P0 and 11 P1.

### Pass 2c re-check on the current build (`out/qa/pass2c_*.png`)

**S01–S08: 0 P0 · 0 P1.**
- Resolved: the S08 swaps at 32.4 and 35.45 (clean gap), the S07 FOUND ring (up by 29.6, about 1.5 s on screen), and the S06 framing (heading, tabs and card whole). The P2s polishA listed are confirmed.
- Remaining P2s: S01 frame 0 (builder's), and the count-up on −$1,955.68 (lib's).

**S09–S16: S14 caption resolved.** It now reads "Books and bank, reconciled" → "A −$0.89 gap, flagged" → "The gap is the $0.89 fee", with a 22 px "Simulated books · taxi fleet" chip. That's accurate and clearly labeled. S12 framing at 64.0 is also resolved: the whole action row is in frame, including "Only you can approve protection." S13's heading is whole at 68.8.

**Still open (P1)**, unchanged in this render:
- S14: the fee connector appears at 78.4, and the scene ends at 78.55.
- S14 at 77.0, S10 at 43.0, 45.5 and 48.0, and S13 at 70.5: rings are mis-registered during camera moves.
- S15 at 84.5: the evidence chips are still about 13–15 px. polishB's note says 20–30 px, but the render doesn't show that.
- S12: at 65.5 the camera drifts to an empty strip with a cursor, and at 66.6 the "Approved by you" chip is about 11 px.
- S11 at 54.5: the title sits text-on-text over the card.
- S16: the wordmark lands about 2 s after the VO says "Offset."

**S09–S16 now:** 0 P0 · 9 P1.

---

# Transitions, after builder's crossfade fix

I rendered 84 frames at 60 fps around each of the 15 boundaries (±0.7 s) and frame-diffed them. A mid-dissolve sheet is in the scratchpad (`dissolves.png`).

| Boundary | Type | Active window | Peak diff | Verdict |
|---|---|---|---|---|
| S1→S2 | dissolve | soft, long | 1.7 | ✓ |
| S2→S3 | dissolve | +0.0…+0.5 s | 1.8 | ✓ |
| S3→S4 | dissolve | +0.05…+0.5 | 1.0 | ✓ |
| S4→S5 | continuity cut | none | 0.3 | ✓ (invisible) |
| S5→S6 | dissolve | +0.03…+0.57 | 9.8 @ +0.25 | ✓ (bell-shaped) |
| S6→S7 | dissolve | +0.03…+0.68 | 4.7 | ✓ |
| S7→S8 | dissolve | +0.02…+0.53 | 5.8 | ✓ |
| S8→S9 | dissolve | +0.03…+0.52 | 8.7 | ✓ |
| S9→S10 | continuity cut | none | 1.4 | ✓ (invisible) |
| S10→S11 | dissolve | +0.03…+0.50 | 7.1 | ✓ |
| S11→S12 | dissolve | +0.03…+0.67 | 6.5 | ✓ |
| S12→S13 | dissolve | +0.0…+0.63 | 6.0 | ✓ |
| S13→S14 | dissolve | +0.03…+0.68 | 8.0 | ✓ |
| S14→S15 | dissolve | +0.0…+0.67 | 6.5 | ✓ |
| S15→S16 | dissolve | soft | 1.2 | ✓ |

**The pass-1 P0 is resolved.** No boundary has a single-frame hard cut: every peak sits at the middle of a roughly 0.5 s ramp, with no dip to black. There are no frozen frames, so no stutter at 60 fps. The S4→S5 and S9→S10 continuity cuts are pixel-continuous.

## Remaining (P2)
- **Text on text mid-dissolve (about 0.15 s):** S8→S9 at 37.28, S13→S14 at 71.24, S14→S15 at 78.80 ("Never approves…" over the reconcile table), and S5→S6 at 18.46 (the rail over the wizard). That's inherent to a straight dissolve between busy frames. Optional: let the outgoing caption exit 0.2 s before the boundary (scene-level), or use a 0.25 s out, 0.35 s in dip through the backdrop for these four.
- **Window geometry jumps across a dissolve:** S8 has two windows, S9 one wide one; S13 is a narrow window, S14 a wide one. A shared-window move (the S6→S7 approach) would read smoother.
- **S1 frame 0 is still a flat backdrop** (std 0). The first visible content arrives at about 0.1 s. Give S1 `transition: "cut"` with content at t=0.
- **The end fades fully to the backdrop by 90.5.** ✓

---

# Pass 3: S09–S16 (polishB round 2)

Pass 3 used stills every 0.5 s from 38.0 to 93.0 s, in `out/qa/pass3/`, with sheets in `out/qa/sheets4/`.

The schedule: S9 38.33, S10 43.56, S11 53.09, S12 64.55, S13 68.33, S14 72.29, S15 80.40, S16 88.37. The total is about 93.5 s.

## All pass-2 P1s resolved

| # | Item | Pass-3 evidence |
|---|---|---|
| 1 | S14 fee connector held | The ring is on Fees $0.89 from 79.0 and the connector is drawn by 79.5. It holds through 80.5 (about 1.5 s or more), then the dissolve. ✓ |
| 2 | S14 wording | "Books and bank, reconciled" → "A $0.89 gap, flagged" → "The gap is the $0.89 fee", plus the "Simulated books · taxi fleet" chip. ✓ Accurate. |
| 3 | S14 note ring mid-move | The ring appears only after the camera settles (78.0). ✓ |
| 4 | S15 card legibility | The chips are now about 20–24 px. "1,955 contracts @ 33¢ · premium $675.41" ends cleanly, and "tool · size_hedge" is legible. ✓ |
| 5–6 | S10 rings mid-move | The bar ring at 45.0 and the premium ring at 50.0 appear after the moves, with no ring on empty space. ✓ |
| 7 | S13 heading and ring | "Decision log" is whole, and the APPROVAL · OWNER ring is tight on the label (71.0). ✓ |
| 8 | S12 cropped words | The action row is whole at 65.0–66.0, including "Only you can approve protection." ✓ |
| 9 | S12 chip size | At 67.5 it pushes in to "Approved by you" at about 28 px with a green ring. ✓ |
| 10 | S16 pacing | The lockup is complete by 89.5, "Steadier weeks." at 89.5, and "Your call." at 91.0, in sync with the VO (88.77–91.33). ✓ |
| 11 | S11 title overlap | The title and card no longer overlap. ✓ |

Accuracy re-verified: 1,955 · $1,955.00 · $1,955.68 · $675.41 · $64.86 at 31% · +$2,080/+$228 · $60/$60/$59.11 · −$0.89 · $0.89 fee for hdg_s01.

## Remaining (all P2)

| Scene | Time | Issue | Fix |
|---|---|---|---|
| S10 | 45.0–46.9 | The equation builds right-first: "≤ $1,955.68" sits with an empty left side for about 1.5 s until "1,955" arrives at 47.0. | Reveal the left side first, or both together. Or hold the "≤" until the left side lands. |
| S11 | 53.3–54.0, 55.3–55.8 | Two empty-frame beats, about 0.7 s and about 0.5 s, around the title. The first is the intended "beat of black". The second reads as a dropped frame. | Shorten the second gap to at most 0.2 s, or bring the card in under the title's fade-out. |
| S11 | 56.0–57.0 | The masked card is mostly blank pink and white space. | Optional: reveal the card title and sentence first. |
| S09 / S11 | 41.0, 59.0 | Rings mid-glide pass across text (between the title and ticker lines, and across "$2,080.20 | $228.41"). | Fine at speed. Optional: shorten glides to at most 0.3 s. |
| S12 | 67.5–68.3 | The push-in on the chip leaves a mostly empty dimmed frame with a cropped "…41 (includes $30.26 fee)…" strip. | Optional: dim the rest further, or frame chip plus card title. |
| S15 | 83–86 | The buy-line chip's left edge clips a sliver of the preceding "·". | Shift the crop 4–6 px right. |
| S16 | 89.0 | The wordmark wipe shows a lone "(" (the left edge of "O"). | Fine as a wipe. Optional: a feathered mask edge. |

**Pass 3 S09–S16 totals:** 0 P0 · 0 P1 · 7 P2.

**Whole film, scene-level:** 0 P0 · 0 P1.

**Open engine items, not re-measured:**
- The S16 VO-vs-sting level (was 8 dB).
- S1 frame 0 is blank (P2).

The S01–S08 schedule shifted (S8 now 30.85+7.49), so a spot check of S07 and S08 is worth doing on the final candidate.

### Pass 3b: spot-check of polishB's P2 fixes
- S10 equation: **fixed.** "1,955" and "$1,955.68" enter together, and "≤" snaps in afterwards (S10+2.0, +3.0).
- S15 buy-line crop: **fixed.** It's clean at 1:1, with no "·" sliver.
- S11 title-to-card handoff: **improved.** An empty frame still shows at S11+2.60, between the title out (about +2.45) and the card in (about +2.75), so the gap is about 0.2 s. Acceptable. It reads as a cut beat, not a dropped frame.
- #3 and #5 were left as is by polishB, which is acceptable. #7 needs no change.

---

# Candidate check: out/scratch/xfcheck/offset-product.mp4 (93.52 s, 60 fps)

| Check | Result |
|---|---|
| Transitions | All 15 boundaries are smooth 0.5–0.7 s ramps, with peak diffs of 1–11 at mid-ramp. There are no boundary spikes. S4→S5 is invisible. ✓ |
| Frame 0 | A flat #112b1f veil, per the lead's call; it lifts by about 0.6 s. ✓ |
| Stutter | Two 1-frame holds, at the starts of the S6 dissolve (18.233) and the S16 dissolve (88.383): a frame of motion, one identical frame, then motion resumes. The diffs are about 1, so it's barely visible. **P2:** likely the incoming scene's first rendered frame equals its at=0 state. Check the overlap start and the ease at p=0. |
| Dim pops | 39.77 (S9, d 8.5) and 76.15 (S14, d 8.8), the known glideRing items with polishB. **P2.** |
| 79.18–79.20 | A fee-connector draw, ramped over 6 frames. Fine. |
| A/V sync | The mp4 audio equals mix.m4a (0 ms lag). All 16 VO clips land at their scheduled start (±1 ms). ✓ |
| VO over bed | S1–S16 are 15–30 dB, with a 10th percentile of 15–28 dB. **S16 is now 21.7 dB (p10 17.7), up from 8.4.** Masking is fixed. ✓ |
| Loudness | −16.0 LUFS integrated, −2.9 dBTP, LRA 2.9. ✓ |

**Candidate verdict:** 0 P0 · 0 P1 · 2 P2 engine items (the boundary-start hold, and the two glideRing dim pops with polishB). The candidate is ready for `--final`, pending polishB's ring-dim easing and the two cue changes builder mentioned. I'll re-diff the final in about 2 min when it lands.

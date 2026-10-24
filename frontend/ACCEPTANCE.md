# C7 · Frontend

> Cross-chunk conflicts are resolved in [CONTRACTS.md](../docs/CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | One-page Next.js dashboard: header, exposures (left), hedge cards (center), decision log (right), backtest + ledger/reconciliation (bottom), chat and settings drawers. Formats API output; never calculates. |
| **Files** | `frontend/app/page.tsx`, `frontend/components/*`, `frontend/lib/api.ts`, `frontend/lib/format.ts`, `frontend/lib/mock.ts`, `frontend/tests/`, `frontend/e2e/` |
| **Spec sections** | §1 (I2, I3, I6), §7 headline, §8 decision object, §12 (stack, API, "frontend formats and never calculates"), §13, §14 demo beats, §15 fallbacks, §16 cut list |
| **Owner role** | Frontend and story |
| **Depends on** | C6 API/models/db (hard: JSON contract). Soft, via C6 fixtures: C1 Data (real/estimated flags), C2 Stats (exposures, model check, backtest), C3 Markets (hedge, payoff, checks), C4 Agent/policy/log (summary, decisions, chat), C5 Books (ledger, reconciliation). C8 Demo ops/Makefile/offline runs the e2e and `make demo`. |
| **Gate** | 3:30 PM: example JSON checked in, mock mode renders every region. 9 PM: dashboard on real API. Never cut: decline moment, payoff table with premium, model check, decision log. Cuttable: settings drawer, approval timing UI, reconciliation tab, restaurant switch. |

## Interfaces

**Routes by region** (all via `lib/api.ts`, SWR keyed on `[route, businessId]`; base URL `NEXT_PUBLIC_API_URL`)

| Region | Route(s) | Trigger |
|---|---|---|
| Header: switcher | `GET /businesses` | mount |
| Header: budget remaining | `Business.budget` (from `/businesses`) and `GET /businesses/{id}/hedges` | mount, after approve/reject/run |
| Header: Run desk | `POST /businesses/{id}/desk/run` then poll `hedges` + `decisions` until run done | click |
| Left: exposures, dropped, Model check | `POST /businesses/{id}/analyze` (idempotent read) | mount, business switch, threshold change |
| Center: hedge cards | `GET /businesses/{id}/hedges?week_of=` | mount, after run |
| Card: Approve / Reject | `POST /hedges/{id}/approve`, `/reject` (`actor: owner`) | click |
| Right: decision log | `GET /businesses/{id}/decisions` | mount, after any mutation |
| Bottom: backtest | `GET /businesses/{id}/backtest` | mount |
| Bottom: ledger tab | `GET /businesses/{id}/ledger`; `POST /businesses/{id}/reconcile` | tab open / click |
| Chat drawer | `POST /businesses/{id}/chat` | send |
| Settings drawer | Not in §12 API: assumed `GET/PUT /businesses/{id}/settings` (see gaps) then re-fetch analyze + hedges | save |

**Components and props** (props are API objects passed through untouched; no derived money)

| Component | Props (source object) |
|---|---|
| `Header` | `businesses[]`, `selectedId`, `dataLabel` (`Business.data_label`), `budget` (`Business.budget`: `weekly`, `spent`, `remaining`), `onRun`, `running` |
| `EstimatedBadge` | `kind: "estimated" \| "simulated" \| "real"`, `note?` (from `Business.estimated`, `Ledger.simulated`) |
| `ExposureList` | `exposures[]` (Exposure: `effect_usd`, `ci90`, `direction`, `hedgeable`, `reasons`) |
| `ExposureBar` | one Exposure; plots `ci90` against a scale computed server-side (`axis_min/max` if provided, else see gaps) |
| `NotHedgedList` | `dropped[]` (Exposure with `reasons`) |
| `ModelCheck` | `model_check` (`planted`, `recovered`, `ci90`, `coverage_pct`, `r2_holdout`) |
| `HedgeCard` | `hedge` (market, side, contracts, `premium`, `fill`, `payoff[]`, `headline`, `decision`) |
| `PayoffChart` | `hedge.payoff[]` (two rows: event / no event; fields revenue_vs_base, payout, premium, net) |
| `HeadlineStrip` | `hedge.headline` ({`unhedged_swing`, `hedged_swing`, `cost`} as strings) |
| `DecisionChip` | `decision.status` (`proposed`, `declined`, `pending_approval`, `approved`, `rejected`, `expired_unapproved`) |
| `DeclineReasons` | `decision.checks[]`, `decision.reasons[]`, `decision.summary` |
| `ApproveBar` | `hedge.id`, `status`, `alternative` (within-budget hedge, if present), callbacks |
| `DecisionLog` / `DecisionRow` | `decisions[]` (id, ts, actor, agent, type, `summary`, `checks[]`) |
| `BacktestPanel` | `BacktestResult` (`weekly[]`, `std_*`, `reduction_pct`, `worst_week_*`, `total_premium`, `n_*`, `priced_real_pct`, `per_exposure`) |
| `MetricsStrip` | same BacktestResult scalar fields |
| `LedgerTab` / `ReconcilePanel` | `Ledger` (`entries[]`, `reconciliation`: matches, `mismatches[]` with `explanation`, `simulated: true`) |
| `ChatDrawer` | `ChatReply` (`reply`, `tool_calls[]`) |
| `SettingsDrawer` | `Settings` (thresholds from §8 + `weekly_budget`) |
| `StateBoundary` | wraps SWR result: loading skeleton, empty copy, error + Retry |

**Mock-fixture mode:** `NEXT_PUBLIC_MOCK=1` makes `lib/api.ts` resolve from `frontend/fixtures/*.json` (copies of C6 examples) with 150 ms delay; a `?scenario=` query selects `default`, `empty`, `error`, `slow`. Mock approve/reject/run mutate in-memory state only. Mock mode shows a visible "MOCK DATA" corner tag. Same components, same types, no branches in components.

## Automated acceptance tests

Tooling: Vitest + React Testing Library + MSW (component/integration, `frontend/tests/`); Playwright (e2e, `frontend/e2e/`, runs against mock mode and against `make demo` with `DEMO_OFFLINE=1`); ESLint for static rules.

| ID | Test name | Future test file | Setup / fixture | Assertion |
|---|---|---|---|---|
| C7-A1 | No money arithmetic in frontend (static) | `frontend/tests/no-money-math.test.ts` + `.eslintrc` rule | Scan `components/`, `app/`, `lib/` (not `format.ts` tests) | Zero `parseFloat/Number/+/-/*//` applied to identifiers matching `/usd|premium|cost|price|swing|payout|effect|revenue|budget|cents/i`; no `Decimal`/`big.js` import; `Math.*` only in chart-scale helper allowlist |
| C7-A2 | Displayed values equal API strings | `frontend/tests/passthrough.test.tsx` | MSW serves `hedges_*.json` with sentinel strings (`"1234.50"`, `"0.62"`) | Every `$` / `%` / `¢` token in rendered DOM maps to a fixture string via `format.ts` (formatting only: grouping, symbol); no token exists that is absent from the fixtures |
| C7-A3 | `format.ts` is pure formatting | `frontend/tests/format.test.ts` | Table of strings | `fmtUsd("1240.0")="$1,240"`, `fmtUsd("0.5")="$0.50"`, `fmtPct("0.27")="27%"`, `fmtCents("0.62")="62¢"`; big and negative strings keep exact digits (no float rounding drift, e.g. `"0.1"+"0.2"` style cases not applicable) |
| C7-A4 | Declined hedges render with reasons | `frontend/tests/hedge-card-declined.test.tsx` | `hedge_declined_overpriced.json` (§8 example) | Card present in center list, chip "Declined", each `reasons[]` code shown as plain-language label, failed-check metrics shown (62¢, 27%, 36%), `summary` text shown, no Approve button |
| C7-A5 | Declined card never hidden | `frontend/tests/hedge-list.test.tsx` | `hedges_mixed.json` (1 proposed, 1 declined, 1 pending) | 3 cards rendered, declined sorted visibly (not collapsed); count in header of region equals array length |
| C7-A6 | `no_market` decline | `frontend/tests/hedge-card-no-market.test.tsx` | `hedge_declined_no_market.json` (no contracts, null premium) | Renders reason "no open market" without crashing; no payoff chart, no "Open on Kalshi" link |
| C7-A7 | Estimated label on restaurant | `frontend/tests/labels.test.tsx` | `businesses.json`, select `restaurant` | Header shows "Estimated" badge with "visits × average check"; every revenue figure region (backtest, exposures) carries the badge or tooltip; taxi shows "Real" |
| C7-A8 | Simulated label on reconciliation | `frontend/tests/labels.test.tsx` | `ledger_with_mismatch.json` | Ledger tab and ReconcilePanel show "Simulated" badge; bank statement rows labelled simulated; badge cannot be dismissed |
| C7-A9 | Label driven by data flag, not business name | `frontend/tests/labels.test.tsx` | Flip `estimated` on taxi fixture | Badge appears for taxi; removed for restaurant when flag false |
| C7-A10 | Payoff chart shows both outcomes incl. premium | `frontend/tests/payoff-chart.test.tsx` | `hedge_proposed_rain.json` | Two outcome groups ("It rains", "It stays dry"), each with unhedged and hedged bars; accessible table/`aria-label` lists revenue, payout, premium (with minus sign), net for each; premium string equals `hedge.premium` |
| C7-A11 | Chart bars use API numbers only | `frontend/tests/payoff-chart.test.tsx` | Same | Recharts `data` prop deep-equals fixture `payoff[]` (strings coerced only for axis scale in `chartScale.ts`) |
| C7-A12 | Headline text | `frontend/tests/headline.test.tsx` | `hedge_proposed_rain.json` | Text exactly `Unhedged swing $900 · hedged swing $60 · cost $41` formatted from `headline` fields; appears on every non-declined card |
| C7-A13 | Approve only when pending_approval | `frontend/tests/approve-bar.test.tsx` | Parametrize all six statuses | Approve and Reject buttons exist only for `pending_approval`; `proposed` (within budget, auto), `declined`, `approved`, `rejected`, `expired_unapproved` have none |
| C7-A14 | Approve flow | `frontend/tests/approve-bar.test.tsx` | MSW for `POST /hedges/{id}/approve` | Click sends `actor: owner`; button disabled while pending; card flips to "Approved"; budget in header and log both refresh from API (assert refetch, not local subtraction) |
| C7-A15 | Over-budget shows alternative | `frontend/tests/approve-bar.test.tsx` | `hedge_pending_over_budget.json` | Full-size hedge shown with Approve, plus within-budget alternative card/section from API |
| C7-A16 | Business switch reloads all regions | `frontend/e2e/switch-business.spec.ts` | Mock mode, record requests | After switching fleet to restaurant: `analyze`, `hedges`, `decisions`, `backtest`, `ledger` each requested with new id; no fleet text remains; rain direction label flips (positive to negative); chat drawer history cleared |
| C7-A17 | Switch during in-flight request | `frontend/tests/race.test.tsx` | Delay fleet response, switch, then resolve | Stale fleet data never renders under restaurant |
| C7-A18 | Settings threshold change flips decision | `frontend/e2e/threshold-flip.spec.ts` | Against `make demo` offline; `overpriced` hedge at 0.35 overpay | Open settings, raise `overpriced` threshold above 0.35, save: `analyze`/`hedges` re-fetched, same card chip changes Declined to Proposed (or Pending), log gets new row; restoring threshold flips back |
| C7-A19 | Settings validation | `frontend/tests/settings-drawer.test.tsx` | Input out-of-range / blank | Save disabled with inline message; values sent as strings, unchanged otherwise |
| C7-A20 | Loading states | `frontend/tests/states.test.tsx` | MSW delay | Each region shows its own skeleton; Run desk shows "Running…" and is disabled; no layout jump > skeleton height |
| C7-A21 | Empty states | `frontend/tests/states.test.tsx` | `scenario=empty` | No hedges: "No hedges this week. Run the desk." ; no decisions; empty ledger; no exposures; none render `undefined`, `NaN`, `$null` |
| C7-A22 | Error states | `frontend/tests/states.test.tsx` | MSW 500 / network fail per route | Failing region shows message + Retry; other regions still render; Retry refetches; approve failure keeps card actionable with toast |
| C7-A23 | Agent fallback marker | `frontend/tests/decision-log.test.tsx` | Log row `agent: "fallback"` | Row shows "Automatic summary" tag |
| C7-A24 | Log expand to checks | `frontend/tests/decision-log.test.tsx` | `decisions.json` | Rows newest first; expand shows each check pass/fail with metric values; collapsed by default |
| C7-A25 | Model check display | `frontend/tests/model-check.test.tsx` | `analyze.json` | Toggle shows planted vs recovered, 90% CI, coverage share, `r2_holdout` verbatim |
| C7-A26 | Not hedged list | `frontend/tests/exposures.test.tsx` | `analyze.json` with 2 dropped | Collapsed by default, count shown, expand lists each with reason text |
| C7-A27 | Backtest panel | `frontend/tests/backtest.test.tsx` | `backtest.json` | Headline "weekly income swings fell X% for $Y in premiums" from API fields; worst-week before/after shown; `ineffective` exposures flagged; `priced_real_pct` shown when < 100 with "frequency-priced" label |
| C7-A28 | Reconciliation mismatch | `frontend/tests/reconcile.test.tsx` | `ledger_with_mismatch.json` | Flagged row highlighted, explanation text shown, three sources side by side |
| C7-A29 | Chat drawer | `frontend/tests/chat.test.tsx` | MSW `chat` | User message echoed, reply rendered as text, `tool_calls[]` expandable; error keeps input; reply numbers not reformatted |
| C7-A30 | Open on Kalshi link | `frontend/tests/hedge-card.test.tsx` | Proposed fixture | `<a target=_blank rel="noopener noreferrer">` to API-provided URL; absent for no_market |
| C7-A31 | 1280px layout | `frontend/e2e/projector.spec.ts` | Viewport 1280x720, mock default | No horizontal scroll; header, exposures, first hedge card, log visible without vertical scroll above the fold; no text clipped (`scrollWidth<=clientWidth` on card/log); screenshot snapshot |
| C7-A32 | Narrow fallback | `frontend/e2e/projector.spec.ts` | 1024px | Layout stacks; still no horizontal scroll |
| C7-A33 | A11y smoke | `frontend/e2e/a11y.spec.ts` | axe on default page | 0 serious/critical; decision chips not color-only; contrast AA |
| C7-A34 | Mock mode parity | `frontend/tests/types.test.ts` | Validate fixtures against C6 JSON schema/types | All fixtures parse; mock and live typed identically |
| C7-A35 | Full demo path e2e | `frontend/e2e/demo-script.spec.ts` | `make demo` with `DEMO_OFFLINE=1` | Scripted §14 beats complete with no console errors; Run desk completes < 20 s |
| C7-A36 | Build | CI `frontend` job | | `tsc --noEmit`, `next build`, ESLint all pass |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C7-H1 | 2-minute demo script | Run §14 beats with a stopwatch, `DEMO_OFFLINE=1`, 3 rehearsals | Each beat within its window (0:15, 0:45, 1:15, 1:40, 2:00); no waiting on spinners; no manual URL typing |
| C7-H2 | Back-of-room readability | Project at 1280px, read from ~10 m | Headline, chips, premium, and swing numbers legible; body text >= 16px, key numbers >= 28px |
| C7-H3 | Declined card in 5 seconds | Show a declined card to a non-trader; ask "what happened and why?" | Says "it skipped it because it was too expensive" within 5 s, unprompted by explanation |
| C7-H4 | Jargon sweep, first minute | Read all default-visible copy | No "hedge ratio", "basis risk", "OLS", "HC3", "N*", "strike"; uses "insurance for a single Saturday", "protection", "swing" |
| C7-H5 | Real vs estimated honesty | Walk both businesses | Restaurant dollars visibly "Estimated"; reconciliation visibly "Simulated"; no way to read them as real |
| C7-H6 | Payoff chart comprehension | Show chart for 5 s, ask "what happens if it rains / stays dry?" | Viewer sees both outcomes land near flat and notices the cost |
| C7-H7 | No "profit" language | Read copy | Premium framed as cost; nothing says "make money", "win", "profit" (principle 2, prompt rule 5) |
| C7-H8 | Decline moment lands | Rehearse beat 4 including a threshold move | Judge can open settings, move one slider, and see the flip in under 10 s |
| C7-H9 | Planted-error moment | Run reconcile with the planted short deposit | Flag, amount, and explanation are readable at a glance |
| C7-H10 | Business switch story | Switch fleet to restaurant live | Opposite rain direction obvious without narration; no stale data flicker |
| C7-H11 | Visual hierarchy / color | Squint test; grayscale screenshot | Status and direction survive without color; consistent palette; no chart legend needed to read bars |
| C7-H12 | Failure drill | Kill API mid-demo; set `scenario=error` | Page degrades region-by-region with clear Retry; presenter can recover in < 10 s |
| C7-H13 | Number provenance spot check | Pick 5 on-screen figures, trace each to API JSON / log | All five match exactly (I2) |

## Fixtures & sample data needed

Provided by C6 (checked in at 3:30 PM, copied to `frontend/fixtures/`); frontend adds `scenario` variants only.

| Fixture | Content | Source chunk |
|---|---|---|
| `businesses.json` | taxi (`estimated:false`) + restaurant (`estimated:true`), budget object | C6/C1 |
| `analyze_taxi.json`, `analyze_restaurant.json` | 3+ exposures (rain positive/negative), 2 dropped with reasons, `model_check`, `r2_holdout` | C2 |
| `hedges_mixed.json` | proposed rain NO, declined overpriced+too_expensive (§8 example), declined `no_market`, partial fill (illiquid), `basis_too_loose` resized | C3/C4 |
| `hedge_pending_over_budget.json` | full size + within-budget alternative | C4 |
| `hedge_approved.json`, `hedge_expired_unapproved.json` | status coverage | C4 |
| `decisions.json` | ~12 rows incl. `agent: fallback`, approve, expired | C4 |
| `backtest_taxi.json` | weekly series (unhedged vs hedged), metrics, one `ineffective`, `priced_real_pct < 100` | C2 |
| `ledger_with_mismatch.json` | entries + reconciliation with planted short deposit, `simulated:true` | C5 |
| `chat_reply.json` | reply + `tool_calls[]` | C4 |
| `settings.json` | thresholds and weekly budget | C6 |
| `errors.json` | 4xx/5xx body shape | C6 |
| Scenarios | `empty` (all arrays empty), `error`, `slow`, `longtext` (long summaries, 2-digit-thousand money), `negative` (negative effects) | C7 |

All money as strings; at least one fixture value with trailing zeros and one > $10,000 to catch float formatting.

## Definition of done

- [ ] All C7-A tests pass in CI; C7-A1 lint rule enforced in pre-commit.
- [ ] Every region renders from mock fixtures (3:30 PM gate) and from the real API (9 PM gate) with identical components.
- [ ] Never-cut items present: declined cards with reasons, payoff with premium, Model check, decision log.
- [ ] Estimated/simulated labels present everywhere required (I6) and verified by C7-A7/A8/A9.
- [ ] C7-H1, H3, H4, H8 signed off by someone other than the author; H1 done on `DEMO_OFFLINE=1` after the 2 AM cache warm.
- [ ] Works at 1280px without scroll surprises; demo video recorded from this build.
- [ ] No console errors in demo path; `next build` clean.
- [ ] `make demo` (C8) serves frontend + backend with one command.

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| 1 | No settings route in §12 API | Add `GET/PUT /businesses/{id}/settings`; on save, frontend re-fetches `analyze` and `hedges`. Server re-evaluates (frontend never re-decides) |
| 2 | "Re-evaluate" after threshold change: does it re-run Claude or only `rules.py`? | Only deterministic re-evaluate of existing hedges (fast, no LLM); log row `threshold_changed` |
| 3 | Desk run is async (`202 {run_id}`) but no status route | Poll `hedges` + `decisions` every 1 s up to 30 s; stop when `run_id` appears in newest decision. Ask C6 for `GET /runs/{id}` as nicety |
| 4 | Budget remaining has no explicit route | Part of `/businesses` payload (`budget.{weekly,spent,remaining,pending}`) |
| 5 | Payoff chart scale and bar heights need arithmetic | API supplies `payoff[]` plus `axis_min/axis_max`; chart helper may only scale pixels, never display derived dollars |
| 6 | Exposure CI bars need a shared axis | Server provides `axis` on the analyze response; fallback is per-list min/max of API strings used only for pixel position |
| 7 | Backtest series shape not specified | `weekly[] = {week_of, unhedged, hedged}` as strings |
| 8 | Headline fields not in the hedge object | `hedge.headline = {unhedged_swing, hedged_swing, cost}` strings from C3 |
| 9 | Payoff row shape | `{outcome: "event"\|"no_event", revenue_vs_base, payout, premium, net}` |
| 10 | Which stored string is shown for "Open on Kalshi" | `hedge.market.url` built by C3; hide if missing |
| 11 | Approver identity ("owner only") | Hardcode `actor: "owner"` in the demo; no login |
| 12 | Where "real/estimated" flag lives | `Business.estimated` and `Business.data_label`; ledger/reconcile `simulated: true` |
| 13 | Plain-language labels for decline codes (`basis_too_loose`, etc.) | Static map in `lib/labels.ts` (e.g. "The weather source doesn't match your hours"); codes shown only inside expanded details |
| 14 | `week_of` default | Latest Monday-start week from API; selector hidden unless > 1 week exists |
| 15 | Auto-approved vs `proposed`: spec has `pending_approval` only for over-budget | Treat `proposed` (within budget) as awaiting owner too? Default: owner still approves everything in demo; Approve shown for `pending_approval` only, so C4 should emit `pending_approval` for all not-declined hedges, or `proposed` is display-only. Confirm with C4 |
| 16 | Pre-3:30 PM schema churn | Types generated from C6 pydantic OpenAPI (`openapi-typescript`) so drift fails `tsc` |

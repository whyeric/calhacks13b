# Cross-chunk contract resolutions

The chunk `ACCEPTANCE.md` files were written in parallel and disagree in places. **Where they conflict, this file wins.** C6 turns these into pydantic models + `fixtures/examples/*.json` by the 3:30 PM gate.

## Resolved

| # | Conflict | Between | Resolution |
|---|---|---|---|
| R1 | Exposure money as `float` (C2) vs `Decimal` strings (C3, C6) | C2 ↔ C3/C6 | C2 may compute in float internally; `fit_exposures` **returns Decimal** (2 dp) for `effect_usd`, `ci90`, `se`, `beta_settlement`. JSON = strings. `p_value`, `r2_*`, `coverage`, `reduction_pct`, `priced_real_pct` stay numbers (stats, not money/price). |
| R2 | β_S output: `beta_settlement() -> {beta_S, se, r2_flags}` (C2) vs `BasisStat{r2, beta_s}` (C3) | C2 ↔ C3 | C2 returns **`BasisStat{r2: Decimal, beta_s: Decimal, se: Decimal}`**, defined in `models.py`. |
| R3 | Rules as one `evaluate()` (C3) vs individual callables for backtest (C2) | C2 ↔ C3 | C3 exposes pure `check_overpriced`, `check_basis`, `check_too_expensive` → `{code, passed, metric}`; `evaluate()` composes all six. Backtest calls the three directly. |
| R4 | `partial` as a decision status (C4) vs a flag (C3) | C3 ↔ C4 | **Flag** (`metric.partial`, `hedge.partial`). Decision `status` ∈ `proposed \| declined \| pending_approval`. |
| R5 | Hedge lifecycle status enum | C3, C6, C7 | `proposed → pending_approval → approved → settled` plus terminal `declined`, `rejected`, `expired_unapproved`. Decision status is the first three; Hedge status is the full set. |
| R6 | ModelCheck fields: `coverage`/`example.recovered` (C2) vs `coverage_pct`/`planted`/`recovered` (C6, C7) | C2 ↔ C6/C7 | Use C2's shape: `{planted_usd, frac, n_seeds, example{seed, recovered, ci90, contains_truth}, coverage, mean_recovered, target}`. `r2_holdout` lives on the analyze response, not ModelCheck. |
| R7 | Budget: flat `weekly_budget`/`budget_remaining` (C6) vs `Business.budget{weekly,spent,remaining}` (C7) vs `check_budget` (C4) | C4, C6, C7 | One **`Budget{budget, spent, remaining, pending, week_start}`** object (C4's `check_budget` output). `Business.budget: Budget`. |
| R8 | Log entry `log_id`/`kind` (C4) vs `id`/`type` (C7) | C4 ↔ C7 | C4's shape: `log_id`, `kind`. |
| R9 | Reconciliation mismatch `{id, expected, actual, diff}` (C4 tool) vs `{hedge_id, expected, kalshi_ledger, bank, difference, …}` (C5) | C4 ↔ C5 | C5's `ReconResult` everywhere; the `reconcile` tool returns it unchanged. |
| R10 | Ledger response `{entries, reconciliation_status}` (C6) vs `{entries, reconciliation, simulated}` (C7) | C6 ↔ C7 | `GET /ledger` → `{entries: LedgerEntry[], reconciliation: ReconResult \| null, simulated: true}`. |
| R11 | Settlement result `"win"/"lose"` (C5) vs Kalshi `"yes"/"no"` (C2, C3) | C5 ↔ C3 | Store Kalshi's `result` (`yes`/`no`); win iff `result == hedge.side`. Payout = `n_filled × $1`. |
| R12 | `/health` (C6) vs `/healthz` (C8) | C6 ↔ C8 | `/health`. |
| R13 | `CacheMiss` (C3) vs `OfflineCacheMiss` (C8) | C3 ↔ C8 | `CacheMiss`, defined in `markets/kalshi.py`. |
| R14 | Settings route missing from C6; C7 assumes one | C6 ↔ C7 | Add `GET/PUT /businesses/{id}/settings` → `Settings{thresholds…, weekly_budget}`. PUT re-runs rules only (no Claude) on this week's hedges and logs each flip. |
| R15 | Run status: `GET /runs/{run_id}` (C6) vs poll hedges+decisions (C7) | C6 ↔ C7 | Add `GET /runs/{run_id}`; frontend polls it, then refetches hedges + decisions on `done`. |
| R16 | Headline "cost $Z" = premium or expected cost | C3, C7 | **Premium** (what the owner pays). `expected_cost` stays in the decision metrics. |
| R17 | `fair` source: business flag vs settlement flag | C1 ↔ C3 | p̂ of the **settlement** flag on `train` (`features.event_frequency(df, settlement_col)`). |
| R18 | I2 allowed-number set covers only `checks[].metric` (C4) | C3, C4, C5 | Allowed = numbers from `checks[].metric` ∪ Hedge sizing fields ∪ `Budget` ∪ `ReconResult` in the same turn. Same validator runs on chat replies. |
| R19 | Owner of `config.py` thresholds | C1, C3, C6 | C6 owns the file; one `Thresholds` dataclass, consumed by C3 rules, C2 backtest, C6 settings route. |
| R20 | Playoff home-game exposure: one exposure hedged with several season contracts | C2, C3, C4, C7 | `Exposure.event = "playoff_home"`, `effect_usd` = $ per playoff home game, plus optional `expected_count` (number), `estimated: true`, `basis_note`. Each futures leg is its own `Hedge` with the same `exposure_id` (`exp_playoff_home`), optional `leg_label` and `group_total_premium` (sum of leg premiums, same on every leg); single-contract hedges leave both null. Every leg runs the six rules; the leg's swing is its protected amount (I1 per leg). |
| R21 | I6 label on analysis and hedges, not just `Business` / `BacktestResult` | C2, C3, C4, C6, C7 | `AnalyzeResponse.estimated` and `Hedge.estimated` (optional, default `false`) are `true` when the business's dollars are estimated (`Business.estimated`, the restaurant); a hedge on a pooled-estimate exposure (`Exposure.estimated`) is also `true`. The desk stamps it when storing; the API also sets it from the business on every hedge it returns. |
| R22 | Second venue (Polymarket) without a second set of shapes | C3, C5, C7 | Polymarket candidates are the same `Candidate` with `venue: "polymarket"`, `fee_rate`, `market_url`, `settlement_source`; their token asks fold into the Kalshi `Orderbook` shape so sizing and rules don't change. `Hedge.venue` (default `"kalshi"`) and `Hedge.fee_rate` (null = Kalshi 0.07). A no_market check that scanned both venues carries `n_kalshi`, `n_polymarket` and optional `venue_note`. Polymarket premiums and payouts post to `Assets:Polymarket:Cash`. |
| R23 | Segregation of duties beyond I4 | C4, C6, C7 | Actor `"controller"`. `Thresholds.materiality_usd` (default 200.00, mirrored in `ThresholdSettings`): a premium above it needs `POST /hedges/{id}/cosign {actor: "controller", approve, note}` before the owner's approval books it (`409 needs_controller` / `controller_refused`). Only the controller co-signs, changes materiality (PUT settings with `X-Actor: controller`) or closes the books; only the owner approves or rejects. `Hedge.needs_controller` and `Hedge.controller` (`ControllerSignoff`). Tokens: `X-Owner-Token` / `X-Controller-Token` when `OWNER_TOKEN` / `CONTROLLER_TOKEN` are set. Log kinds `cosign`, `cosign_refused`, `refusal`. |
| R24 | The desk's memory across weeks | C4, C7 | `Hedge.owner_history: OwnerHistory | null` (earlier hedges for the same exposure: counts, totals, up to 5 recent outcomes with the owner's notes, `pattern: "rejected_recently" | null`) and `Hedge.decision_note` (the owner's approve note or reject reason). Computed in code when the desk stores a hedge (`agent/memory.py`); it changes the proposal's first sentence, never a rule. |
| R25 | "Why?" from the record | C6, C7 | `GET /hedges/{id}/receipt` → `DecisionReceipt{hedge, exposure, thresholds, trail, approvals_required, sources}`; read-only, no LLM. |
| R26 | Period close | C5, C6, C7 | `POST /businesses/{id}/close {actor: "controller", through, acknowledge_exceptions, note}` → `PeriodClose` (trial balance, carried exceptions, open hedges); `GET /businesses/{id}/closes` → `PeriodCloses{locked_through, closes}`. Ledger writes dated on or before `locked_through` move to the next open day with a narration suffix. Log kind `period_close`. |
| R27 | Pricing an uploaded file's FOUND downside | C3, C6, C7 | `POST /research/quote?hypothesis=<id>` (raw CSV body, like `/research`) → `ResearchQuote{hypothesis_id, exposure, hedge, budget, p_hat, window, basis_note}`. Not stored, so never approvable. |

## Needs a human decision

| # | Question | Affects | Proposed default |
|---|---|---|---|
| D1 | Does **every** hedge need owner approval (principle 3), or only over-budget ones (§8)? C6 currently allows approve only from `pending_approval`, so in-budget `proposed` hedges could never be booked. | C3, C4, C6, C7 | Every passing hedge waits for the owner; approve/reject allowed from `proposed` **or** `pending_approval`. Over-budget ones additionally show the within-budget alternative. |
| D2 | May aggregated Dewey-derived daily series be committed (spec C6 license check)? | C1, C8 | Commit daily aggregates only, no place names; confirm against Yale's Dewey terms. |
| D3 | Which `data/` folder is Advan Weekly Patterns+ vs the other product? | C1 | Inspect schemas once Python deps are installed. |
| D4 | Do pending hedges count against the weekly budget? | C4, C7 | Yes: `remaining = budget − approved − pending`. |
| D5 | "Frozen from train" vs "re-estimate monthly" in the backtest | C2 | Re-estimate monthly on an expanding window ending before each month; never uses future data. |

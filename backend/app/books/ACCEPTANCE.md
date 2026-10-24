# C5 · Books & reconciliation

> Cross-chunk conflicts are resolved in [CONTRACTS.md](../../../docs/CONTRACTS.md); that file wins over this one.

| | |
|---|---|
| **Scope** | Beancount ledger booking of approved hedges; simulated settlement; simulated bank statement; three-way reconciliation with one planted mismatch that is caught and explained |
| **Files** | `backend/app/books/ledger.py`, `backend/app/books/reconcile.py`, `ledgers/{taxi,restaurant}.beancount`, `fixtures/bank_statement.csv` (+ simulated settlement fixture, see Fixtures) |
| **Spec sections** | §9 (books), §1 invariants I5, I6; §7 (premium = cost + fee); §11 (`book_hedge`, `reconcile` tools); §12 API (`/ledger`, `/reconcile`); §14 step 4 |
| **Owner role** | Agent and books |
| **Depends on** | C3 Markets (approved Hedge object, market `result`, `fee_type`); C4 Agent/policy/log (approval event with `actor: owner`, `decision_id`, decision-log append for I5); C6 API/models/db (Hedge model, Decimal-as-string serialization, endpoints); C8 Demo ops (`make seed` regenerates ledger + statement; offline cache). Not C1/C2 directly |
| **Gate** | Midnight checkpoint: "reconciliation with the planted mismatch". Ledger booking is on the never-cut list; reconciliation is cut-list item 4 (ledger must still ship if recon slips) |

## Interfaces

All money is `Decimal` (never float); serialized as strings.

| Function | Contract |
|---|---|
| `book_hedge(hedge, approval) -> list[str]` | Appends premium + fee transaction to `ledgers/{business_id}.beancount`; returns entry IDs. Raises if `hedge.status != approved` or `approval.actor != "owner"`. Idempotent on `hedge_id` (second call returns existing IDs, writes nothing). Appends I5 log event `booked`. |
| `book_settlement(hedge, market_result) -> list[str]` | `result == "win"` (hedge side pays): payout txn, `Assets:Kalshi:Cash` +N, `Income:Hedging:Payouts` -N. `result == "lose"`: no cash entry, log `expired`, write a Beancount `note` directive. Idempotent per `hedge_id`. |
| `book_withdrawal(business_id, amount, date, hedge_ids)` | Debit `Assets:Bank:Checking`, credit `Assets:Kalshi:Cash`. |
| `simulate_settlement(hedge, market) -> SettlementRecord` | Derives outcome from real market `result` and hedge side; fee/payout per Kalshi rules; flagged `simulated: true`. |
| `generate_bank_statement(settlements, plant=True) -> csv` | Writes `fixtures/bank_statement.csv`; applies the planted error to exactly one line. |
| `load_ledger(business_id) -> list[Entry]` | Parses via beancount loader; raises on parse/validation error. |
| `reconcile(business_id) -> ReconResult` | Compares (a) expected payout from market `result`, (b) Kalshi cash ledger entries, (c) bank CSV rows. Pure, deterministic, no LLM. Appends I5 log event `reconciled`. |

**Ledger entry shape** (one txn per event; narration prefixed `[SIMULATED]` for settlement/withdrawal entries):

```
2026-10-26 * "Hedge Desk" "Premium: KXHIGHNY-26OCT28-T65 NO x 40"
  hedge_id: "hdg_01"  ticker: "KXHIGHNY-26OCT28-T65"  decision_id: "dec_07"  approved_by: "owner"
  Expenses:Hedging:Premiums   22.40 USD
  Expenses:Hedging:Fees        0.98 USD
  Assets:Kalshi:Cash         -23.38 USD
```

Metadata keys required on every hedge-related transaction: `hedge_id`, `ticker`, `decision_id`, `approved_by`; simulated entries additionally `simulated: "true"`. File opens with `option "operating_currency" "USD"` and `open` directives for all accounts used, plus an opening deposit to `Assets:Kalshi:Cash` (labeled).

**Bank statement CSV columns:** `date,description,amount,currency,reference,simulated` (`reference` = hedge_id or ticker; `simulated` = `true` on every row; header comment/line or filename makes it explicit).

**ReconResult JSON:**

```json
{
  "business_id": "taxi", "as_of": "2026-10-30", "simulated": true,
  "matches": [{"hedge_id": "hdg_01", "ticker": "…", "expected": "40.00", "kalshi_ledger": "40.00", "bank": "40.00"}],
  "mismatches": [{
    "hedge_id": "hdg_02", "ticker": "…", "expected": "30.00", "kalshi_ledger": "30.00", "bank": "29.12",
    "difference": "-0.88", "source_pair": "kalshi_ledger_vs_bank",
    "explanation": "Bank deposit is $0.88 short of the Kalshi payout; equals the $0.88 fee recorded for hdg_02.",
    "likely_cause": "fee_deducted_from_deposit", "action": "ask_owner",
    "question": "Did you authorize the fee to be netted from this withdrawal?"
  }],
  "summary": {"n_matched": 1, "n_mismatched": 1, "total_difference": "-0.88"}
}
```

`explanation`/`question` are templated from numbers in the same object (I2); any Claude paraphrase is validated by `log.py`.

## Automated acceptance tests

Test files under `backend/tests/books/`. Fixtures named in Setup are in the Fixtures section.

| ID | Test name | Future test file | Setup / fixture | Assertion |
|---|---|---|---|---|
| C5-A1 | ledger_passes_bean_check | `test_ledger_beancount.py` | Seed ledgers via `make seed` | `bean-check ledgers/*.beancount` exits 0 with no errors/warnings, both businesses |
| C5-A2 | transactions_balance | `test_ledger_beancount.py` | Same | Per txn, sum of postings == 0 (debits = credits); trial balance sums to 0 USD |
| C5-A3 | premium_fee_match_hedge | `test_book_hedge.py` | `approved_hedge.json` (premium 23.38 = 22.40 + 0.98) | `Premiums + Fees == hedge.premium` exactly, to the cent (Decimal ==); Kalshi cash credited by the same amount; fee equals `ceil_cent(0.07*C*P*(1-P))` |
| C5-A4 | metadata_complete | `test_book_hedge.py` | Same | Every hedge txn has non-empty `hedge_id, ticker, decision_id, approved_by`; `approved_by == "owner"` |
| C5-A5 | payout_only_on_win | `test_settlement.py` | Markets with `result` yes and no; hedges on both sides (4 combos) | Payout entry exists iff hedge side == result; amount == N × $1.00; credit account `Income:Hedging:Payouts` |
| C5-A6 | no_cash_entry_on_expiry | `test_settlement.py` | Losing hedge | `Assets:Kalshi:Cash` balance unchanged after settlement; zero new postings; decision log has `expired` event |
| C5-A7 | idempotent_rebooking | `test_book_hedge.py` | Call `book_hedge` and `book_settlement` twice | File bytes identical after 2nd call; same entry IDs returned; no duplicate `hedge_id` txn |
| C5-A8 | rejected_never_booked | `test_book_hedge.py` | Hedges with status `declined`, `pending_approval`, `rejected`, `expired_unapproved` | `book_hedge` raises; ledger unchanged; no `booked` log event |
| C5-A9 | non_owner_cannot_book | `test_book_hedge.py` | approval `actor: "desk"` | Raises; ledger unchanged (I4) |
| C5-A10 | planted_mismatch_flagged | `test_reconcile.py` | `bank_statement.csv` with planted short deposit | Exactly 1 mismatch; `difference == -fee` (e.g. -0.88) to the cent; correct `hedge_id`; `likely_cause == fee_deducted_from_deposit`; explanation text contains the difference and fee amounts |
| C5-A11 | zero_false_positives_clean | `test_reconcile.py` | Same ledger, `bank_statement_clean.csv` (no plant) | `mismatches == []`; `n_matched == n_settled_hedges` |
| C5-A12 | recon_deterministic_and_pure | `test_reconcile.py` | Run twice | Identical JSON; ledger/CSV files unmodified by `reconcile` |
| C5-A13 | expired_not_flagged | `test_reconcile.py` | Losing hedge with no bank row | Not reported as a mismatch (expected payout 0, bank 0) |
| C5-A14 | unmatched_bank_row_flagged | `test_reconcile.py` | Extra bank row with no ledger counterpart | One mismatch of kind `unexplained_bank_row` with amount |
| C5-A15 | simulated_labeled | `test_simulated_labels.py` | Seeded ledgers, CSV, ReconResult | Every settlement/withdrawal txn has `simulated: "true"` and `[SIMULATED]` narration; every CSV row `simulated=true`; ReconResult `simulated == true`; `/ledger` API payload carries the flag (I6) |
| C5-A16 | decimal_precision | `test_book_hedge.py` | Fee with fractional cents | No float anywhere; `Decimal` quantized to 0.01; round-up on fee |
| C5-A17 | log_events_appended | `test_book_hedge.py`, `test_reconcile.py` | Run full flow | Decision log contains `booked`, `settled`/`expired`, `reconciled` events in order, each with `hedge_id` (I5) |
| C5-A18 | seed_reproducible | `test_seed.py` | `make seed` twice from cached Kalshi results | Ledger and CSV byte-identical; works with `DEMO_OFFLINE=1` |

## Human review checklist

| ID | What to examine | How | Pass looks like |
|---|---|---|---|
| C5-H1 | Ledger readability | Open `ledgers/taxi.beancount` in fava (`fava ledgers/taxi.beancount`) or read raw | An accountant-literate person confirms premiums and fees are expenses, payouts income, accounts sensible, narrations plain English, no jargon |
| C5-H2 | Balance sheet / P&L in fava | Fava Balance Sheet and Income Statement tabs | Kalshi cash ties to expected balance; hedging cost shows as a net expense line; no negative cash surprise |
| C5-H3 | Metadata traceability | Pick one entry; follow `hedge_id` to the decision log and to the hedge card | Same ticker, premium, and approver appear in all three places |
| C5-H4 | Simulated labels | Read ledger, CSV, and Ledger tab in UI | Every simulated item is obviously labeled without hovering; nothing simulated looks like a real bank record (I6) |
| C5-H5 | Mismatch explanation | Show recon output/UI card to a non-finance person (an owner stand-in) | They can say in their own words what is off, by how much, why it likely happened, and what the question to them is, in under 30 seconds |
| C5-H6 | Planted mismatch is plausible | Compare bank CSV line to settlement | Short-by-fee looks like a realistic netting error, not an arbitrary number; amounts tie to real market results |
| C5-H7 | Clean run looks clean | Run recon on unplanted data in the UI | Green "all reconciled", no warnings or noise |
| C5-H8 | Demo moment (§14 step 4) | Rehearse with `DEMO_OFFLINE=1` | Recon catch takes under 20 seconds on screen; flagged row, amount, and explanation all legible at projector size |
| C5-H9 | No real money implied | Grep copy for "paid", "deposited" without a simulated qualifier | Judges cannot read it as real trading (spec: "never places real orders") |

## Fixtures & sample data needed

| Fixture | Contents | Source / owner |
|---|---|---|
| `fixtures/businesses/*.json` ref | business ids `taxi`, `restaurant` | C6 |
| `approved_hedge.json` | Approved Hedge with `premium`, `fee`, `N`, `side`, `ticker`, `decision_id`; premium = cost + fee exact | C3/C4 example JSON (3:30 PM gate) |
| Hedge variants | `declined`, `pending_approval`, `rejected`, `expired_unapproved` | C4 |
| `settled_markets.json` | Real settled Kalshi market objects (`ticker`, `result`, `fee_type`, `fee_multiplier`) from `kalshi_cache/`, with at least one yes and one no | C3 cache |
| `ledgers/taxi.beancount`, `ledgers/restaurant.beancount` | Generated by seed: opening deposit, approve entries, settlements (>= 1 win, >= 1 loss), one withdrawal | C5 `make seed` |
| `fixtures/bank_statement.csv` | One row per withdrawal, `simulated=true`, exactly one planted short deposit | C5 |
| `fixtures/bank_statement_clean.csv` | Same without the plant (test-only) | C5 |
| Edge fixtures | Fractional-cent fee case; two hedges on same ticker; extra unmatched bank row | C5 |

## Definition of done

- C5-A1..A18 pass in CI; C5-H1..H9 signed off by a named reviewer.
- `bean-check` clean on both ledgers; fava opens them.
- `book_hedge` wired as agent tool and called by `POST /hedges/{id}/approve`; `reconcile` wired to `POST /businesses/{id}/reconcile` and `GET /ledger` (with reconciliation status).
- Every booking, settlement, expiry, and reconciliation appears in the decision log (I5); all simulated artifacts labeled (I6).
- `make seed` regenerates ledger + statement deterministically; works offline.
- Planted mismatch caught on the demo ledger with the correct amount and explanation; documented in code comment as the answer key.
- Cut-order respected: if time is short, ship booking (A1-A9) and drop recon (A10-A14).

## Spec gaps / open questions

| # | Gap | Proposed default |
|---|---|---|
| 1 | Premium split: spec says Premiums and Fees but `premium = cost + fee` in §7 | Premiums account = contract cost; Fees = fee; sum must equal `hedge.premium` |
| 2 | Spec lists no entry for the opening cash funding of `Assets:Kalshi:Cash` | Labeled simulated opening deposit from `Assets:Bank:Checking`; bank CSV includes it |
| 3 | "Result" semantics and mapping to hedge side (yes/no) unspecified | Win iff `market.result == hedge.side`; payout = N × $1.00 |
| 4 | Kalshi fee on settlement/payout | None at settlement (taker fee only at entry), per §7; confirm on first API call |
| 5 | Which settled markets feed the simulation, given approved hedges are on this week's open markets that haven't closed | Seed with recent settled markets of the same series as stand-in hedges, labeled simulated; live flow books approval only |
| 6 | Planted mismatch type and location | One withdrawal deposit short by the fee of that hedge; on the taxi ledger only |
| 7 | Reconciliation tolerance and matching key | Exact to the cent; match on `hedge_id`/ticker in `reference`, fall back to date + amount |
| 8 | Does the second business get a plant | No; restaurant stays clean and doubles as the false-positive test |
| 9 | Ledger append vs regenerate; concurrency | Append-only with file lock; idempotency via `hedge_id` metadata scan |
| 10 | Rejected/expired_unapproved log vs books | Not booked; only the decision log records them |
| 11 | Partial fills (`illiquid` partial) | Book actual filled N and its premium, not the proposed N |
| 12 | Booking date | Approval timestamp (America/New_York date); settlement entries dated market close |
| 13 | Currency/precision for fractional-cent fees | Round up to cent per §7; premium already cent-exact |

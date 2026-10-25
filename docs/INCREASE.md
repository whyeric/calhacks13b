# Increase: a real bank for the bank leg of reconciliation

Reconciliation compares three records of every settled hedge, and each one is the **system of
record** for one fact. When they disagree, the desk says which one to trust and why, instead of
averaging them or quietly picking the books.

| Leg | What it says | System of record for | Read from |
|---|---|---|---|
| **venue** | what the exchange paid out, and the fee it charged | what was paid; the fee | a `VenueSource`: the simulated settlement (from the real Kalshi `result`, R11) today; the Kalshi demo/live portfolio plugs in at `books/sources.py:get_venue_source` |
| **ledger** | what we booked (the payout entry's venue-cash posting, the premium entry's fee) | what we booked | Beancount (`books/ledger.py`) |
| **bank** | what cash actually arrived | cash received | a `BankSource`: **Increase** (sandbox or live) when configured, else the simulated CSV |
| *expected* | the payout recomputed from the market result and the hedge's side | (sanity check only) | the settlement log |

So "Kalshi paid $60.00 and we booked $60.00; the bank received $59.11" is a **real** $0.89 cash
shortfall, because the bank is the record for cash; it equals the entry fee, so it looks netted
from the withdrawal. "Kalshi paid $66.00 but we booked $65.00, and the bank received $65.00" is a
**booking** error: the venue is the record for what was paid, and $1.00 is likely still in the
Kalshi account.

Code: `backend/app/integrations/increase.py` (client, `IncreaseBankSource`, `get_bank_source`),
`backend/app/books/sources.py` (`BankRow`, `VenueSettlement`, `CsvBankSource`,
`SimulatedVenueSource`), `backend/app/books/reconcile.py`. Tests:
`backend/tests/integrations/test_increase.py`, `backend/tests/books/test_three_way.py`.

> **What's real and what isn't.** By default the bank leg is the **SIMULATED** bank CSV
> (`fixtures/bank_statement.csv`), labeled `csv_simulated`. With Increase configured it is a real
> bank API, but the **sandbox** moves no real money, so its rows are labeled `increase_sandbox` and
> still count as simulated (I6). Only `increase_live` (production) is live money.
> `ReconResult.simulated` is true unless **every** leg is live; today the ledger's settlement
> entries are simulated, so it is always true. The Increase client has been tested **only against a
> mock of the API** (no network in tests); nobody has run it against a real sandbox key yet.

---

## 1. Demo mode (default)

Nothing to configure. With no `INCREASE_API_KEY`/`INCREASE_ACCOUNT_ID`, or with `DEMO_OFFLINE=1`,
the bank leg is the simulated CSV and no request is made. `GET /integrations/increase/status`
returns `"mode": "demo"`.

## 2. Staging the sandbox

1. Create an Increase sandbox API key (dashboard.increase.com → Developers → API keys, sandbox).
2. Dry run, then stage:

   ```bash
   cd backend
   .venv/bin/python -m scripts.stage_increase_sandbox --dry-run
   INCREASE_API_KEY=... .venv/bin/python -m scripts.stage_increase_sandbox
   ```

   For each business with settled demo hedges it creates (or reuses) an open account
   "Hedge Desk demo (taxi)" and an account number, then:

   | Sandbox action | Endpoint | What reconcile does with it |
   |---|---|---|
   | Owner capital in, $1,000.00, addenda `OWNER CAPITAL opening_balance` | `POST /simulations/inbound_ach_transfers` | opening balance, outside hedge activity (noted) |
   | Opening deposit out to Kalshi, $500.00, descriptor `opening_deposit to Kalshi` | `POST /ach_transfers`, then `POST /simulations/ach_transfers/{id}/submit` | matches the ledger's opening deposit |
   | **hdg_s01: $59.11** for a $60.00 payout (the answer key: short by the $0.89 fee) | `POST /simulations/inbound_ach_transfers` | `fee_deducted_from_deposit`, bank is the record |
   | **hdg_s03: $45.00 with `resolve_at` = now + 2 days** (stays pending: T+2) | same, with `resolve_at` | `in_transit`, not an error |
   | hdg_r01 (restaurant): $80.00 | same | matched |

3. Put the printed line in `.env`:

   ```
   INCREASE_API_KEY=...
   INCREASE_ENVIRONMENT=sandbox
   INCREASE_ACCOUNT_ID=taxi=account_...,restaurant=account_...
   ```

   `INCREASE_ACCOUNT_ID` is either one account id for every business or a `business=account` map.

**Re-running is safe.** Every POST sends a deterministic `Idempotency-Key`
(`hedge-desk-demo-v1-<business>-...`); Increase replays the first result for the same key and body,
and answers 409 `idempotency_key_already_used_error` when the body changed (e.g. a new `resolve_at`),
which the script reports as "exists" and skips. Accounts are found by name before creating.

**References.** A bank doesn't know our hedge ids. A `BankRow.reference` is set only when the
transfer itself carries one (an `hdg_...` id in the ACH addenda, discretionary data or descriptor);
otherwise it is `None` and reconcile matches the deposit on amount (the payout, or the payout net
of the venue's fee) dated within 3 days of the settlement. The staging script puts
`Kalshi withdrawal hdg_s01` in the addenda by default, **standing in for remittance info**; Kalshi
wouldn't send it. `--no-references` leaves the ids out, so reconcile uses only amount and date.
Sandbox transfers post at the time you run the script and can't be backdated, so without references
run it within 3 days of the settlement dates or the deposits fall outside the matching window.

## 3. What reconcile reads from Increase

| Increase | `BankRow` |
|---|---|
| `GET /transactions?account_id=` (cursor-paginated, `limit=100`) | one posted row each: `amount` (integer cents → `Decimal` dollars, inbound positive), `created_at` → date in New York time, `description`, `id` → `external_id`, `status: "posted"` |
| `GET /inbound_ach_transfers?account_id=&status.in=pending` | one **pending** row each (`status: "pending"`): seen by the bank, not cash yet |
| `source.<category>` (addenda entries, discretionary data, statement descriptor) | `reference` when it contains a hedge id, `opening_deposit` or `opening_balance` |

Timing vs error:

- a deposit **pending** at the bank whose amount equals the booked payout → `in_transit`;
- no deposit yet, within `DEPOSIT_WINDOW_DAYS` (3) of settlement → `in_transit`;
- no deposit after that → `missing_deposit`.

With Increase, the statement's `as_of` is today (the bank is read live), so the window runs to now.

If Increase can't be read (network, auth, `DEMO_OFFLINE`), reconcile falls back to the simulated
CSV for that call and says so in `ReconResult.sources.notes`; it never 5xxs on the bank.

## 4. The API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/integrations/increase/status` | | `IncreaseStatus{mode: demo|sandbox|live, environment, accounts, bank_origin, simulated, last_sync, last_rows, last_error}`; no network call, `last_sync` is the last bank read in this process |
| POST | `/businesses/{id}/reconcile` | `{}` | `ReconResult` with `sources`, `in_transit`, and on each row `venue`, `venue_origin`, `bank_origin`; on each mismatch `system_of_record` and `record_reason` (CONTRACTS R28) |

## 5. Likely causes and their source of record

| Cause | Pair | Record | Meaning |
|---|---|---|---|
| `ledger_payout_differs` | venue vs ledger | venue | we booked a payout the venue didn't pay |
| `venue_paid_differs_from_booked` | venue vs ledger | venue | our books match the market result but the venue paid something else (check fill count / side) |
| `result_differs_from_venue` | expected vs venue | venue | venue and books agree; our recomputation doesn't |
| `fee_differs_from_venue` | ledger fee vs venue fee | venue | the fee we booked isn't the fee charged |
| `venue_record_missing` / `unbooked_venue_settlement` | venue vs ledger | venue | one side has a settlement the other lacks |
| `fee_deducted_from_deposit` | ledger vs bank | bank | deposit short by exactly the fee |
| `duplicate_deposit` | ledger vs bank | bank | paid twice (two rows, or once whole and once split) |
| `missing_deposit`, `reversed_sign`, `transposed_digits`, `deposit_amount_differs`, `unexplained_bank_row` | ledger vs bank | bank | cash didn't arrive as booked |

The planted-error benchmark (`python -m app.books.benchmark`, `GET /benchmarks/reconciliation`)
scores these on a SIMULATED world with an answer key: 17 planted errors across the three legs and
7 traps, including two deposits in transit that must be reported `in_transit`. Current score:
17 of 17 caught with the right cause, 0 false flags, 7 of 7 traps.

## 6. Limitations

- Not yet run against a real Increase sandbox: field names follow Increase's public API reference
  (Transactions, Inbound ACH Transfers, Accounts, Account Numbers, ACH Transfers, sandbox
  simulations, `Idempotency-Key`) and are exercised against a mock.
- One Increase account per business; the account's whole history is read on each reconcile.
- Outbound transfers to the venue use a placeholder routing/account number; the sandbox moves no money.
- The venue leg is still simulated until the Kalshi demo source is wired into `get_venue_source`.

# QuickBooks Online: connect the books instead of uploading a CSV

The upload flow ([UPLOAD_AND_RESEARCH.md](UPLOAD_AND_RESEARCH.md)) takes a `date,revenue` CSV. The
QuickBooks integration reads the same revenue from the business's books, so there is no export
step, and adds what the business is already **committed to**: open purchase orders, unpaid bills,
pending estimates (booked future sales) and inventory. Transactions show what was spent; a hedge is
about what is coming. Transaction history is the bootstrap for the research protocol.

It also **writes back**: every entry the desk books (a hedge premium at owner approval, a
settlement payout, a withdrawal, the opening deposit) is mirrored into QuickBooks as a
JournalEntry, and a drift check reads them back to catch a bookkeeper's edit or delete.

Code: `backend/app/integrations/quickbooks.py` (connection, reads), `quickbooks_sync.py`
(write-back, drift check), `quickbooks_sync_routes.py` (route), `qbo_seed.py` and
`backend/scripts/seed_qbo_sandbox.py` (sandbox seeder). Tests: `backend/tests/integrations/`.

> **What's live and what isn't.** In demo mode (the default) the "books" are a **SYNTHETIC**
> company, Hudson Bike Co., read from `backend/fixtures/quickbooks_demo/`, and the desk's journal
> entries go to a **SYNTHETIC demo store** in the app DB. Every response says `"synthetic": true`
> (I6). Live mode talks to Intuit's real API. **Live mode, the seeder and the write-back have only
> been tested against a mock of Intuit's API** (`tests/integrations/fake_qbo.py`); nobody has run
> them against a real sandbox company yet. See section 8 for what that would verify.

---

## 1. Demo mode

Nothing to configure: with no `QBO_CLIENT_ID`/`QBO_CLIENT_SECRET`, or with `DEMO_OFFLINE=1`, the
integration is in demo mode, and it makes no network calls.

1. `POST /integrations/quickbooks/connect` connects at once (`authorize_url` is `null`). The
   connection is stored in the app DB, so it survives a restart.
2. `POST /integrations/quickbooks/research` runs the protocol on the company's revenue.
3. `GET /integrations/quickbooks/commitments` lists the forward-looking books.
4. Approve a hedge: its premium (and the opening deposit before it) is written to the demo store
   as JournalEntries, and the decision log says `qbo_posted`.
5. `GET /integrations/quickbooks/sync?business_id=taxi` shows each ledger entry next to its
   JournalEntry.

The demo company's revenue was generated so that each day's SalesReceipt and Invoices sum, to the
cent, to the sample file `frontend/public/samples/hudson_bike_co_daily_revenue.csv`. So the
QuickBooks report is the CSV report: the same fits, the same verdicts (rain, cold and warm FOUND;
hot and both Knicks hypotheses NOT FOUND), and the same rain effect, **−$1,923.43/day** in train
(2024) and −$2,488.09/day in holdout. Only the report's `name` and `notes` differ.

### What's synthetic

Everything in `backend/fixtures/quickbooks_demo/` (see its README), and every JournalEntry in the
demo store (table `qbo_demo_objects`, each object carries `"synthetic": true`). The fixtures are
temporary demo data and can be deleted and regenerated:

```bash
cd backend && .venv/bin/python scripts/gen_quickbooks_demo.py   # seeded, deterministic
```

| File | Contents |
|---|---|
| `salesreceipt.json` | 1,004 POS daily-batch receipts (walk-up hourly rentals + day passes), 2024-01-01 to 2026-09-30 |
| `invoice.json` | 163 corporate/group-rental invoices carved out of those days' totals |
| `purchaseorder.json` | 6 open POs (e-bikes, winter tires, helmets, storage racks, parts, signage) and 1 closed |
| `bill.json` | 9 unpaid bills due Nov 2026 to Jan 2027 (rent, insurance, dock fee, parts, power, repairs; one partly paid) and 1 paid |
| `estimate.json` | 6 pending/accepted estimates for Nov to Dec 2026 (group rides, a school trip, a holiday lights ride, a hotel guest block) and 2 closed/rejected |
| `item.json` | 13 inventory items (bikes, helmets, parts, resale ponchos) and 4 service items |
| `companyinfo.json` | CompanyName "Hudson Bike Co. (SYNTHETIC)" |

All counterparties are fictional. The closed, paid and rejected rows are there to exercise the
filters below. As of 2026-10-25 the demo shows $96,881.12 committed spend, $40,840.00 expected
revenue from estimates, and $100,720.50 of inventory at cost.

---

## 2. Live mode: an Intuit app and a sandbox company

1. Sign in at <https://developer.intuit.com> and create an app (**Dashboard → Create an app →
   QuickBooks Online and Payments**) with the **Accounting** scope
   (`com.intuit.quickbooks.accounting`).
2. Under the app's **Development** keys, add the redirect URI
   `http://localhost:8000/integrations/quickbooks/callback`, and copy the client id and secret.
3. A sandbox company comes with every developer account (**Dashboard → Sandboxes**; add one if
   there is none: choose **QuickBooks Online Plus**, US). It's a test company with its own data and
   chart of accounts; the seeder (section 3) fills it with Hudson Bike Co.
4. In `.env`:

   ```
   QBO_CLIENT_ID=...
   QBO_CLIENT_SECRET=...
   QBO_ENVIRONMENT=sandbox          # production only for a real company, with production keys
   QBO_REDIRECT_URI=http://localhost:8000/integrations/quickbooks/callback
   FRONTEND_URL=http://localhost:3000
   DEMO_OFFLINE=0
   ```

5. Restart the API. `GET /integrations/quickbooks/status` now says `"mode": "live"`.
6. `POST /integrations/quickbooks/connect` returns `authorize_url`; open it, sign in and pick the
   sandbox company. Intuit redirects to `/integrations/quickbooks/callback`, which checks `state`,
   exchanges the code for tokens, reads `CompanyInfo`, stores the connection, and sends the
   browser to `{FRONTEND_URL}/?qbo=connected` (or `?qbo=error`).

How it talks to Intuit:

- OAuth2 authorization code: `https://appcenter.intuit.com/connect/oauth2`, tokens from
  `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`, revocation at
  `https://developer.api.intuit.com/v2/oauth2/tokens/revoke` (all with HTTP Basic client id and
  secret; endpoints from Intuit's OpenID discovery document). `state` is random, single use, and
  expires after 15 minutes.
- API: `{base}/v3/company/{realmId}/...?minorversion=75`, where `base` is
  `https://sandbox-quickbooks.api.intuit.com` or `https://quickbooks.api.intuit.com`. Reads are
  `GET query?query=SELECT * FROM <Entity> STARTPOSITION n MAXRESULTS 1000`, paged until a page has
  fewer than 1,000 rows. Writes are `POST <entity>` and `POST batch`.
- **Throttling**: a 429 is retried after `Retry-After`, else 1, 2, 4, 8, 16 seconds, then the call
  fails as `502 quickbooks_unavailable`.
- Amounts are parsed as `Decimal` (`parse_float=Decimal`) and written as exact JSON numbers by
  `quickbooks.dumps`, never through a float.

### The stored connection

The connection is one row in the app DB (`qbo_connection`): environment (`demo`, `sandbox` or
`production`), realm id, company name, access and refresh tokens and their expiry times. It only
counts as connected in the mode it was made in (a demo connection isn't a live one; a sandbox
connection isn't a production one).

- **Refresh.** Access tokens last about an hour. A call within 60 seconds of expiry refreshes
  first, and a 401 refreshes once. Intuit rotates the refresh token (it lasts about 100 days), and
  every new one is saved at once. Refreshes take a lock and re-read the stored tokens first, so two
  callers never spend the same refresh token. Once the refresh token has expired, calls answer
  `409 not_connected` ("reconnect").
- **Disconnect** revokes the grant at Intuit (best effort) and deletes the row.
- **Secrets.** Tokens are never logged (`Tokens.__repr__` hides them). They are stored in SQLite
  as Intuit sent them, unencrypted: keep the DB file private (it's gitignored). A production
  deployment should encrypt them at rest.
- One app holds one connected company. The pending OAuth `state` values stay in process memory, so
  a restart between "connect" and Intuit's redirect means clicking connect again.

---

## 3. Seed the sandbox with Hudson Bike Co.

With a sandbox company connected (section 2):

```bash
cd backend
.venv/bin/python scripts/seed_qbo_sandbox.py            # seed, then verify against the demo files
.venv/bin/python scripts/seed_qbo_sandbox.py --verify   # only compare
```

It **refuses to run unless the connected company is a sandbox** (`QBO_ENVIRONMENT=sandbox` and the
sandbox API host); the check is in `qbo_seed.require_sandbox`. Then, in phases, all through
`POST /batch` (at most 30 items a request), paced at one batch every 1.6 s
(`QBO_SEED_BATCH_INTERVAL_S`; Intuit allows 40 batch requests a minute per company), with 429s
backed off:

| Phase | What | Matched on re-run by |
|---|---|---|
| Accounts | the 7 accounts the demo refers to (Checking, Accounts Payable (A/P), Inventory Asset, Rental income, Sales of product income, Cost of goods sold, Operating expenses) | `Name` (most exist in a new sandbox) |
| Names | customers and vendors; 4 service items and 13 inventory items (quantity on hand as of 2024-01-01, cost, price; `Taxable: false`) | `DisplayName` / `Name` |
| Documents | 1,004 SalesReceipts, 163 Invoices, 7 PurchaseOrders, 10 Bills, 8 Estimates with the demo's DocNumbers, lines, dates, statuses and memos | `DocNumber` |
| Payments | a Payment for each paid invoice, a BillPayment for the paid bill and the partly paid one (VSW-88213: $1,000.00 of $2,317.40) | the document's open `Balance` |

Every created document gets `[hedge-desk-seed]` at the end of its `PrivateNote` (the parser strips
it). QuickBooks computes `TotalAmt` and `Balance` from the lines, which carry the demo's exact
amounts; sales lines use tax code `NON` so sales tax can't change a total. A re-run creates
nothing that is already there, and a run that died part way resumes. Faults (one bad document)
are listed and the script exits 1; fix and re-run.

**Equivalence.** `qbo_seed.compare_with_demo` compares the live company with the demo files the way
the desk reads them: daily revenue to the cent, open POs, unpaid bills (with the partly paid
balance), pending estimates, inventory (by name, since Item ids differ) and the three totals. The
script runs it after seeding; `tests/integrations/test_qbo_seed.py` runs the whole seeder against
the mock company and asserts no differences and an identical research report
(`report.hypotheses` equal to the demo's).

---

## 4. Write-back: bookings mirrored as JournalEntries

When the desk books a ledger entry, it mirrors it into the connected company. **Beancount stays
the system of record** for the desk's entries; QuickBooks is a mirror for the bookkeeper.

When: right after the booking, in the approve route (`main.py`, one call) and in
`books/settlement.py` (`book_settlement` for a payout, `book_withdrawal`). Each call posts the new
entries plus any earlier one not yet posted (booked before QuickBooks was connected, or a failed
post), oldest first, so QuickBooks' balances follow the ledger's. Nothing is mirrored when
QuickBooks isn't connected or `QBO_MIRROR_ENABLED=0`.

What one JournalEntry holds:

| Field | Value |
|---|---|
| `DocNumber` | our ledger entry id (`le_hdg_01_premium`); if longer than QBO's 21 characters, its first 12 characters, `-` and 8 hex of its SHA-1 (stable) |
| `TxnDate` | the ledger entry's date |
| `Line` | one `JournalEntryLineDetail` line per non-zero posting: positive amount → `Debit`, negative → `Credit`, `AccountRef` per the mapping below; `Description` is the narration |
| `PrivateNote` | `[SIMULATED]` when the entry is simulated, the ledger entry id and kind, the hedge id, decision id and ticker, and "Posted by Hedge Desk on owner approval" (or "on settlement", "on withdrawal", "as the opening deposit") |

Debits equal credits to the cent by construction: the Beancount postings sum to zero (the
`LedgerEntry` model checks it), and the builder checks again.

**Account mapping** (found by name, created if missing; the types are QBO `AccountType` /
`AccountSubType` values):

| Beancount account | QBO account | AccountType | AccountSubType | Why |
|---|---|---|---|---|
| `Assets:Kalshi:Cash` | Kalshi Cash | Other Current Asset | OtherCurrentAssets | cash at a broker, not a bank account the business reconciles to a bank feed |
| `Assets:Polymarket:Cash` | Polymarket Cash | Other Current Asset | OtherCurrentAssets | same, second venue |
| `Assets:Bank:Checking` | Checking (`QBO_BANK_ACCOUNT_NAME`) | Bank | Checking | the business's existing checking account |
| `Expenses:Hedging:Premiums` | Hedging Premiums | Other Expense | OtherMiscellaneousExpense | a hedge is outside operations: below the operating line, not cost of sales |
| `Expenses:Hedging:Fees` | Hedging Fees | Other Expense | OtherMiscellaneousExpense | the venue's taker fee, kept apart from the premium |
| `Income:Hedging:Payouts` | Hedging Payouts | Other Income | OtherMiscellaneousIncome | the offsetting gain sits next to the premium, below the operating line |

So a premium posts *Debit Hedging Premiums + Debit Hedging Fees / Credit Kalshi Cash*, a payout
*Debit Kalshi Cash / Credit Hedging Payouts*, a withdrawal *Debit Checking / Credit Kalshi Cash*,
and the opening deposit *Debit Kalshi Cash / Credit Checking*.

**Idempotent.** A posted entry is never posted again (the `qbo_mirror` table remembers each entry's
JournalEntry id per company). If that record is lost, the mirror first looks for a JournalEntry
with the entry's `DocNumber` and adopts it instead of creating a duplicate.

**Failures never block.** The mirror runs after the booking is committed and never raises. A
QuickBooks error (down, throttled past the retries, a validation fault, an expired grant) is
recorded as `failed`, logged as `qbo_post_failed` with the reason, and retried with the next
booking. The approval, settlement or withdrawal stands either way.

**Logged (I5).** Each post appends `qbo_posted` (with the JournalEntry id, DocNumber and amount)
or `qbo_post_failed` to the decision log, after the entry's own `booking` event.

**Simulated entries** (settlement payouts, withdrawals and the opening deposit are simulated, see
`books/settlement.py`) are labeled `[SIMULATED]` in the JournalEntry, and are only ever written to
the demo store or a sandbox company. Against a production company they are skipped (the sync view
shows them `not_posted`, with the reason).

---

## 5. Drift check: when the sources disagree

`GET /integrations/quickbooks/sync?business_id=...` lists every ledger entry of the business with
its JournalEntry, read back from QuickBooks (or the demo store) now:

| Status | Meaning |
|---|---|
| `posted` | the JournalEntry is there and matches the ledger line for line (account, debit/credit, amount) |
| `missing` | we posted it, and it's gone from QuickBooks (deleted there) |
| `amount_differs` | it's there but edited: `detail` names each line that differs, ledger vs QuickBooks |
| `failed` | posting failed (`detail` has the reason); retried with the next booking |
| `not_posted` | never mirrored: booked before QuickBooks was connected, the mirror is off, or a simulated entry and a production company |

The report says `"system_of_record": "beancount"` and why: each ledger entry was approved by the
owner and is in the decision log, so where the two disagree the ledger is right, and the fix is to
restore or re-post the QuickBooks entry. The check is read-only: it changes nothing in either.

---

## 6. Entity → field mapping (reads)

| We show | QBO entity | Rows used | Fields |
|---|---|---|---|
| Daily revenue | `SalesReceipt`, `Invoice` | all | `TotalAmt` summed by `TxnDate` |
| Open purchase orders | `PurchaseOrder` | `POStatus == "Open"` | `amount` = `TotalAmt`; `due_date` = `DueDate`, else `ShipDate`; counterparty `VendorRef.name`; description `Memo`, else `PrivateNote`, else first line |
| Unpaid bills | `Bill` | `Balance > 0` | `amount` = `Balance`; `due_date` = `DueDate`; `status` "Unpaid", or "Partially paid" when `Balance < TotalAmt`; counterparty `VendorRef.name`; description `PrivateNote`, else first line |
| Pending estimates | `Estimate` | `TxnStatus` is `Pending` or `Accepted` | `amount` = `TotalAmt`; `due_date` = `ShipDate` (when the sale happens), else `ExpirationDate`, else `TxnDate`; counterparty `CustomerRef.name`; description `CustomerMemo`, else first line |
| Inventory | `Item` | `Type == "Inventory"` and active | `qty_on_hand` = `QtyOnHand`; `unit_cost` = `PurchaseCost`; `value` = qty × cost |
| Company name | `CompanyInfo` | first row | `CompanyName` |

Totals: `committed_spend` = open PO totals + unpaid bill balances; `expected_revenue` = estimate
totals; `inventory_value` = sum of item values. The model checks each total against its lines.
`PrivateNote` is read without the seeder's `[hedge-desk-seed]` tag.

**Revenue basis.** Accrual: an invoice counts on its `TxnDate`, not when it's paid. `TotalAmt`
includes any sales tax, and amounts are taken in the company's home currency as-is. Days with no
transactions are left out, the same as a missing CSV row.

---

## 7. The API

| Route | Returns | Notes |
|---|---|---|
| `GET /integrations/quickbooks/status` | `QuickBooksStatus` | `mode`, `connected`, `company_name`, `realm_id`, `connected_at`, `synthetic` |
| `POST /integrations/quickbooks/connect` | `QuickBooksConnect` | Demo: connected, `authorize_url: null`. Live: not yet connected, `authorize_url` set |
| `GET /integrations/quickbooks/callback?code&state&realmId` | `302` | to `{FRONTEND_URL}/?qbo=connected` or `?qbo=error`; `400 bad_state` on a state mismatch |
| `POST /integrations/quickbooks/disconnect` | `QuickBooksStatus` | Revokes the grant at Intuit and deletes the stored connection |
| `GET /integrations/quickbooks/commitments` | `Commitments` | |
| `POST /integrations/quickbooks/research?name=` | `QuickBooksResearch` | `report` is a normal `ResearchReport`; `name` (≤ 60) defaults to the company name |
| `GET /integrations/quickbooks/sync?business_id=` | `QboSyncReport` | The drift check (section 5); read-only |

Models are in `backend/app/models.py`, with examples in `backend/fixtures/examples/`
(`quickbooks_*.json`, `commitments.json`, `commitment_line.json`, `inventory_line.json`).
`LogEntry.kind` gained `qbo_posted` and `qbo_post_failed`.

Errors use the usual `{"error": {"code", "message", "detail"}}` body:

| Status | Code | When |
|---|---|---|
| 404 | `business_not_found` | `sync` for an unknown business |
| 409 | `not_connected` | Commitments, research or sync before connecting, or after the refresh token expired |
| 502 | `quickbooks_unavailable` | Intuit unreachable, an API error, throttled past the retries, or a failed token refresh |
| 422 | `bad_csv`, `too_short`, ... | The same research input errors as `POST /research` (e.g. a company with under 540 days of sales) |
| 400 | `bad_state` | The OAuth callback's `state` doesn't match a connect request |

Settings (end of `Settings` in `config.py`): `QBO_MIRROR_ENABLED` (default on),
`QBO_BANK_ACCOUNT_NAME` (default `Checking`), `QBO_SEED_BATCH_INTERVAL_S` (default 1.6).

---

## 8. Limitations and what still needs real credentials

- **Never run against a real sandbox.** The OAuth flow, refresh and rotation, revoke, queries,
  creates, `/batch`, the seeder and the JournalEntry write-back are all tested against a mock of
  Intuit's API built from Intuit's API reference. With real credentials, check: the seeder runs
  clean and `--verify` reports no differences (in particular that a sandbox with automated sales
  tax leaves the seeded totals alone, and that `TxnStatus`/`POStatus` are accepted on create);
  the account types and subtypes above are accepted; a JournalEntry posts and reads back line for
  line; editing or deleting it in the QuickBooks UI shows as `amount_differs` / `missing`; refresh
  after an hour and revoke on disconnect work.
- **Demo data is synthetic** and its revenue is the sample CSV's, planted effects included. The
  commitments are hand-written and plausible, not from a real shop.
- **One connected company per app.** Every business's ledger is mirrored into it (the PrivateNote
  names the hedge; `taxi` and `restaurant` would share one QuickBooks company).
- **Tokens are unencrypted in SQLite** (section 2).
- **Live posting is synchronous.** The approve request waits for QuickBooks (seconds; longer if
  throttled) but never fails because of it.
- **Commitments aren't in the desk yet.** They're shown next to the research report; sizing a
  hedge against booked revenue or committed spend is a next step.

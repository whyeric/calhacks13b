# QuickBooks Online: connect the books instead of uploading a CSV

The upload flow ([UPLOAD_AND_RESEARCH.md](UPLOAD_AND_RESEARCH.md)) takes a `date,revenue` CSV. The
QuickBooks integration reads the same revenue from the business's books, so there is no export
step, and adds what the business is already **committed to**: open purchase orders, unpaid bills,
pending estimates (booked future sales) and inventory. Transactions show what was spent; a hedge is
about what is coming. Transaction history is the bootstrap for the research protocol.

Code: `backend/app/integrations/quickbooks.py`. Tests: `backend/tests/integrations/test_quickbooks.py`.

> **What's live and what isn't.** In demo mode (the default) the "books" are a **SYNTHETIC**
> company, Hudson Bike Co., read from `backend/fixtures/quickbooks_demo/`. Every response says
> `"synthetic": true`, and the report's notes say so (I6). Live mode talks to Intuit's real API,
> but it has only been tested against a mock of it (no network in tests).

---

## 1. Demo mode

Nothing to configure: with no `QBO_CLIENT_ID`/`QBO_CLIENT_SECRET`, or with `DEMO_OFFLINE=1`, the
integration is in demo mode.

1. `POST /integrations/quickbooks/connect` connects at once (`authorize_url` is `null`).
2. `POST /integrations/quickbooks/research` runs the protocol on the company's revenue.
3. `GET /integrations/quickbooks/commitments` lists the forward-looking books.

The demo company's revenue was generated so that each day's SalesReceipt and Invoices sum, to the
cent, to the sample file `frontend/public/samples/hudson_bike_co_daily_revenue.csv`. So the
QuickBooks report is the CSV report: the same fits, the same verdicts (rain, cold and warm FOUND;
hot and both Knicks hypotheses NOT FOUND), and the same rain effect, **−$1,923.43/day** in train
(2024) and −$2,488.09/day in holdout. Only the report's `name` and `notes` differ.

### What's synthetic

Everything in `backend/fixtures/quickbooks_demo/` (see its README). It's temporary demo data and
can be deleted and regenerated:

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

## 2. Live mode (a real Intuit app)

1. Create an app at <https://developer.intuit.com> with the **Accounting** scope, and add
   `http://localhost:8000/integrations/quickbooks/callback` as a redirect URI. A sandbox company
   comes with every developer account.
2. In `.env`:

   ```
   QBO_CLIENT_ID=...
   QBO_CLIENT_SECRET=...
   QBO_ENVIRONMENT=sandbox          # or production
   QBO_REDIRECT_URI=http://localhost:8000/integrations/quickbooks/callback
   FRONTEND_URL=http://localhost:3000
   DEMO_OFFLINE=0
   ```

3. Restart the API. `GET /integrations/quickbooks/status` now says `"mode": "live"`.
4. `POST /integrations/quickbooks/connect` returns `authorize_url`; open it, sign in and pick a
   company. Intuit redirects to `/integrations/quickbooks/callback`, which checks `state`,
   exchanges the code for tokens, reads `CompanyInfo` and sends the browser to
   `{FRONTEND_URL}/?qbo=connected` (or `?qbo=error`).

How it talks to Intuit:

- OAuth2 authorization code: `https://appcenter.intuit.com/connect/oauth2`, scope
  `com.intuit.quickbooks.accounting`, tokens from
  `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer` (HTTP Basic with the client id and
  secret). `state` is random, single use, and expires after 15 minutes.
- Queries: `GET {base}/v3/company/{realmId}/query?query=SELECT * FROM <Entity> STARTPOSITION n
  MAXRESULTS 1000&minorversion=75`, paged until a page has fewer than 1,000 rows. `base` is
  `https://sandbox-quickbooks.api.intuit.com` or `https://quickbooks.api.intuit.com`.
- The access token is refreshed when it's within 60 seconds of expiring, and once more on a 401.
  If the refresh fails, the call is a `502 quickbooks_unavailable`; reconnect.
- **Tokens live in process memory only.** A restart disconnects, and one API process holds one
  company. Fine for a demo; a real deployment would store encrypted tokens per business.

Amounts are parsed as `Decimal` (`parse_float=Decimal`), never floats. Filtering happens in our
code, not in the query, so demo and live data go through the same parser.

---

## 3. Entity → field mapping

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

**Revenue basis.** Accrual: an invoice counts on its `TxnDate`, not when it's paid. `TotalAmt`
includes any sales tax, and amounts are taken in the company's home currency as-is. Days with no
transactions are left out, the same as a missing CSV row.

---

## 4. The API

| Route | Returns | Notes |
|---|---|---|
| `GET /integrations/quickbooks/status` | `QuickBooksStatus` | `mode`, `connected`, `company_name`, `realm_id`, `connected_at`, `synthetic` |
| `POST /integrations/quickbooks/connect` | `QuickBooksConnect` | Demo: connected, `authorize_url: null`. Live: not yet connected, `authorize_url` set |
| `GET /integrations/quickbooks/callback?code&state&realmId` | `302` | to `{FRONTEND_URL}/?qbo=connected` or `?qbo=error`; `400 bad_state` on a state mismatch |
| `POST /integrations/quickbooks/disconnect` | `QuickBooksStatus` | Forgets the tokens |
| `GET /integrations/quickbooks/commitments` | `Commitments` | |
| `POST /integrations/quickbooks/research?name=` | `QuickBooksResearch` | `report` is a normal `ResearchReport`; `name` (≤ 60) defaults to the company name |

Models are in `backend/app/models.py`, with examples in `backend/fixtures/examples/`
(`quickbooks_*.json`, `commitments.json`, `commitment_line.json`, `inventory_line.json`).

Errors use the usual `{"error": {"code", "message", "detail"}}` body:

| Status | Code | When |
|---|---|---|
| 409 | `not_connected` | Commitments or research before connecting |
| 502 | `quickbooks_unavailable` | Intuit unreachable, an API error, or a failed token refresh |
| 422 | `bad_csv`, `too_short`, ... | The same research input errors as `POST /research` (e.g. a company with under 540 days of sales) |
| 400 | `bad_state` | The OAuth callback's `state` doesn't match a connect request |

Nothing is stored, and the desk only reads from QuickBooks (the accounting scope would allow
writes; no code path makes one).

---

## 5. Limitations

- **Demo data is synthetic** and its revenue is the sample CSV's, planted effects included. The
  commitments are hand-written and plausible, not from a real shop.
- **One connection per process, in memory.** Not multi-tenant, and lost on restart.
- **Commitments aren't in the desk yet.** They're shown next to the research report; sizing a
  hedge against booked revenue or committed spend is a next step.
- **Live mode is tested against a mock** of Intuit's API, not a real sandbox company.

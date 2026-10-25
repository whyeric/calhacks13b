"""Seed an Intuit **sandbox** company with the SYNTHETIC Hudson Bike Co. books.

The demo company in `fixtures/quickbooks_demo/` is files shaped like QBO query responses. This
pushes the same data into a real sandbox company through the v3 API, so live research on the
sandbox gives the demo's report (same daily totals, same commitments). CLI:
`scripts/seed_qbo_sandbox.py`.

Phases, each sent through `/batch` (at most 30 items a request, paced to Intuit's 40 batch
requests a minute, with 429s backed off by the client):

1. Accounts the demo refers to (found by name, created if missing).
2. Customers and vendors (by DisplayName) and items (by Name: services, inventory with its
   quantity on hand, cost and price; non-taxable so sales tax can't change a total).
3. SalesReceipts, Invoices, PurchaseOrders, Bills and Estimates, skipped when a document with the
   same DocNumber exists. Each gets `SEED_TAG` in its PrivateNote. QBO computes `TotalAmt` and
   `Balance` from the lines, which carry the demo's exact amounts.
4. Payments: a Payment per paid invoice, a BillPayment per paid or partly paid bill, sized from the
   document's current Balance in the sandbox, so re-runs pay nothing twice.

Idempotent: every phase looks before it writes. Refuses anything but a sandbox company.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from app.integrations import quickbooks as qbo

TRANSACTIONS = ("SalesReceipt", "Invoice", "PurchaseOrder", "Bill", "Estimate")
LAST_DEMO_DAY = date(2026, 10, 24)  # payments are dated no later than this

# Accounts the demo documents refer to, by name -> (AccountType, AccountSubType) if we create them.
ACCOUNTS = {
    "Checking": ("Bank", "Checking"),
    "Accounts Payable (A/P)": ("Accounts Payable", "AccountsPayable"),
    "Inventory Asset": ("Other Current Asset", "Inventory"),
    "Rental income": ("Income", "ServiceFeeIncome"),
    "Sales of product income": ("Income", "SalesOfProductIncome"),
    "Cost of goods sold": ("Cost of Goods Sold", "SuppliesMaterialsCogs"),
    "Operating expenses": ("Expense", "OfficeGeneralAdministrativeExpenses"),
}
ACCOUNT_REFS = ("AccountRef", "IncomeAccountRef", "ExpenseAccountRef", "AssetAccountRef", "DepositToAccountRef",
                "APAccountRef", "BankAccountRef")
DROP = {"Id", "SyncToken", "MetaData", "TotalAmt", "Balance", "CurrencyRef", "SalesTermRef", "PaymentMethodRef",
        "domain", "sparse"}
ZERO = Decimal("0")


class ProductionRefused(qbo.QuickBooksError):
    status = 409
    code = "production_refused"


class SeedError(qbo.QuickBooksError):
    code = "seed_failed"


@dataclass
class SeedResult:
    created: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    existing: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    faults: list[str] = field(default_factory=list)
    batches: int = 0

    def summary(self) -> str:
        names = sorted(set(self.created) | set(self.existing))
        rows = [f"  {n:<14} created {self.created.get(n, 0):>5}   already there {self.existing.get(n, 0):>5}"
                for n in names]
        return "\n".join(rows + [f"  batches: {self.batches}, faults: {len(self.faults)}"])


def require_sandbox(client: qbo.LiveSource) -> None:
    """The seeder writes 1,200+ synthetic documents: never into a production company."""
    if client.environment != "sandbox" or client.base != qbo.API_BASE["sandbox"]:
        raise ProductionRefused(
            "Refusing to seed: the connected QuickBooks company is not a sandbox company. The seeder only "
            "writes the SYNTHETIC demo books into an Intuit sandbox (QBO_ENVIRONMENT=sandbox).",
            {"environment": client.environment, "realm_id": client.realm_id})


def load_demo(folder=qbo.DEMO_DIR) -> dict[str, list[dict]]:
    src = qbo.DemoSource(folder)
    return {e: src.query(e) for e in ("Item", *TRANSACTIONS)}


class Seeder:
    def __init__(self, client: qbo.LiveSource, *, interval_s: float = 1.6,
                 sleep: Callable[[float], None] | None = None, monotonic: Callable[[], float] = time.monotonic):
        require_sandbox(client)
        self.client = client
        self.interval_s = interval_s
        self.sleep = sleep or (lambda s: qbo.SLEEP(s))
        self.monotonic = monotonic
        self._last: float | None = None
        self.result = SeedResult()
        self.ids: dict[tuple[str, str], str] = {}  # (kind, name) -> Id; kind "Account", "Customer", ...

    # -- plumbing --

    def _batch(self, items: list[dict]) -> list[dict]:
        """Send items 30 at a time, paced; returns every response item."""
        out = []
        for i in range(0, len(items), qbo.BATCH_LIMIT):
            if self._last is not None and self.interval_s > 0:
                wait = self.interval_s - (self.monotonic() - self._last)
                if wait > 0:
                    self.sleep(wait)
            out += self.client.batch(items[i:i + qbo.BATCH_LIMIT])
            self._last = self.monotonic()
            self.result.batches += 1
        return out

    def _create(self, entity: str, bodies: list[tuple[str, dict]]) -> list[dict]:
        """Create `(label, body)` pairs; returns the created objects, records faults by label."""
        items = [{"bId": f"{entity[:3]}{n}", "operation": "create", entity: body} for n, (_, body) in enumerate(bodies)]
        labels = {it["bId"]: label for it, (label, _) in zip(items, bodies)}
        made = []
        for resp in self._batch(items):
            if resp.get("Fault"):
                errs = resp["Fault"].get("Error") or []
                msg = "; ".join(str(e.get("Message", "")) + (f": {e['Detail']}" if e.get("Detail") else "")
                                for e in errs) or "fault"
                self.result.faults.append(f"{entity} {labels.get(resp.get('bId'), resp.get('bId'))}: {msg}")
            elif resp.get(entity):
                made.append(resp[entity])
                self.result.created[entity] += 1
        return made

    def _ref(self, kind: str, ref: dict | None) -> dict | None:
        if not ref:
            return None
        name = str(ref.get("name") or "")
        if (kind, name) not in self.ids:
            raise SeedError(f"No {kind} named {name!r} in the sandbox company.", {"kind": kind, "name": name})
        return {"value": self.ids[(kind, name)], "name": name}

    def _index(self, entity: str, key: str) -> dict[str, dict]:
        return {str(r.get(key)): r for r in self.client.query(entity) if r.get(key) is not None}

    # -- phases --

    def accounts(self, demo: dict[str, list[dict]]) -> None:
        used: set[str] = set()

        def walk(o: Any) -> None:
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ACCOUNT_REFS and isinstance(v, dict) and v.get("name"):
                        used.add(str(v["name"]))
                    walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)

        walk(demo)
        used.add("Checking")
        have = {name.lower(): a for name, a in self._index("Account", "Name").items()}
        todo = []
        for name in sorted(used):
            if name.lower() in have:
                self.ids[("Account", name)] = str(have[name.lower()]["Id"])
                self.result.existing["Account"] += 1
            else:
                kind, sub = ACCOUNTS[name]
                todo.append((name, {"Name": name, "AccountType": kind, "AccountSubType": sub}))
        for a in self._create("Account", todo):
            self.ids[("Account", str(a["Name"]))] = str(a["Id"])

    def names(self, demo: dict[str, list[dict]]) -> None:
        customers = sorted({str(d["CustomerRef"]["name"]) for e in ("SalesReceipt", "Invoice", "Estimate")
                            for d in demo[e] if d.get("CustomerRef")})
        vendors = sorted({str(d["VendorRef"]["name"]) for e in ("PurchaseOrder", "Bill") for d in demo[e]})
        for entity, wanted in (("Customer", customers), ("Vendor", vendors)):
            have = self._index(entity, "DisplayName")
            todo = []
            for name in wanted:
                if name in have:
                    self.ids[(entity, name)] = str(have[name]["Id"])
                    self.result.existing[entity] += 1
                else:
                    todo.append((name, {"DisplayName": name, "Notes": f"SYNTHETIC demo counterparty {qbo.SEED_TAG}"}))
            for o in self._create(entity, todo):
                self.ids[(entity, str(o["DisplayName"]))] = str(o["Id"])

        have = self._index("Item", "Name")
        todo = []
        for item in demo["Item"]:
            name = str(item["Name"])
            if name in have:
                self.ids[("Item", name)] = str(have[name]["Id"])
                self.result.existing["Item"] += 1
                continue
            body: dict[str, Any] = {"Name": name, "Type": item["Type"], "Taxable": False,
                                    "IncomeAccountRef": self._ref("Account", item.get("IncomeAccountRef"))}
            if item["Type"] == "Inventory":
                body.update(Sku=item.get("Sku"), TrackQtyOnHand=True, QtyOnHand=item["QtyOnHand"],
                            InvStartDate=item["InvStartDate"], PurchaseCost=item["PurchaseCost"],
                            UnitPrice=item["UnitPrice"],
                            AssetAccountRef=self._ref("Account", item.get("AssetAccountRef")),
                            ExpenseAccountRef=self._ref("Account", item.get("ExpenseAccountRef")))
            todo.append((name, body))
        for o in self._create("Item", todo):
            self.ids[("Item", str(o["Name"]))] = str(o["Id"])

    def _doc(self, entity: str, d: dict) -> dict:
        """A demo document as a create request: read-only fields dropped, refs re-pointed by name,
        subtotal lines dropped (QBO adds its own), the seed tag on the PrivateNote."""
        body = {k: v for k, v in d.items() if k not in DROP}
        for key, kind in (("CustomerRef", "Customer"), ("VendorRef", "Vendor")):
            if key in body:
                body[key] = self._ref(kind, body[key])
        for key in ("DepositToAccountRef", "APAccountRef"):
            if key in body:
                body[key] = self._ref("Account", body[key])
        lines = []
        for ln in d.get("Line") or []:
            if ln.get("DetailType") == "SubTotalLineDetail":
                continue
            ln = {k: v for k, v in ln.items() if k not in ("Id", "LineNum")}
            if "SalesItemLineDetail" in ln:
                det = dict(ln["SalesItemLineDetail"])
                det["ItemRef"] = self._ref("Item", det.get("ItemRef"))
                det["TaxCodeRef"] = {"value": "NON"}
                ln["SalesItemLineDetail"] = det
            if "AccountBasedExpenseLineDetail" in ln:
                det = dict(ln["AccountBasedExpenseLineDetail"])
                det["AccountRef"] = self._ref("Account", det.get("AccountRef"))
                ln["AccountBasedExpenseLineDetail"] = det
            lines.append(ln)
        body["Line"] = lines
        note = str(d.get("PrivateNote") or "").strip()
        body["PrivateNote"] = f"{note} {qbo.SEED_TAG}".strip()
        return body

    def transactions(self, demo: dict[str, list[dict]]) -> None:
        for entity in TRANSACTIONS:
            have = self._index(entity, "DocNumber")
            todo = []
            for d in demo[entity]:
                if str(d["DocNumber"]) in have:
                    self.result.existing[entity] += 1
                else:
                    todo.append((str(d["DocNumber"]), self._doc(entity, d)))
            self._create(entity, todo)

    def payments(self, demo: dict[str, list[dict]]) -> None:
        """Pay each invoice and bill down to its demo Balance (only the part not yet paid)."""
        for entity, pay_entity in (("Invoice", "Payment"), ("Bill", "BillPayment")):
            current = self._index(entity, "DocNumber")
            todo = []
            for d in demo[entity]:
                live = current.get(str(d["DocNumber"]))
                if live is None:
                    continue
                due = qbo._money(live.get("Balance")) - qbo._money(d.get("Balance"))
                if due <= 0:
                    if qbo._money(d.get("Balance")) < qbo._money(d.get("TotalAmt")):
                        self.result.existing[pay_entity] += 1
                    continue
                paid_on = min(date.fromisoformat(str(d.get("DueDate") or d["TxnDate"])), LAST_DEMO_DAY)
                paid_on = max(paid_on, date.fromisoformat(str(d["TxnDate"])))
                link = [{"Amount": due, "LinkedTxn": [{"TxnId": str(live["Id"]), "TxnType": entity}]}]
                checking = {"value": self.ids[("Account", "Checking")], "name": "Checking"}
                if pay_entity == "Payment":
                    body = {"CustomerRef": {"value": str(live["CustomerRef"]["value"])}, "TotalAmt": due,
                            "TxnDate": paid_on.isoformat(), "DepositToAccountRef": checking, "Line": link,
                            "PrivateNote": f"Payment of {d['DocNumber']} {qbo.SEED_TAG}"}
                else:
                    body = {"VendorRef": {"value": str(live["VendorRef"]["value"])}, "TotalAmt": due,
                            "TxnDate": paid_on.isoformat(), "PayType": "Check",
                            "CheckPayment": {"BankAccountRef": checking}, "Line": link,
                            "PrivateNote": f"Payment of {d['DocNumber']} {qbo.SEED_TAG}"}
                todo.append((str(d["DocNumber"]), body))
            self._create(pay_entity, todo)

    def run(self, demo: dict[str, list[dict]] | None = None) -> SeedResult:
        demo = demo or load_demo()
        self.accounts(demo)
        self.names(demo)
        self.transactions(demo)
        self.payments(demo)
        return self.result


def compare_with_demo(live: qbo.QboSource, as_of: date, demo: qbo.QboSource | None = None) -> list[str]:
    """Differences between the live company and the demo company, as the desk reads them: daily
    revenue to the cent, and the commitments (inventory compared by name, since Item Ids differ).
    Empty means live research gives the demo's report."""
    demo = demo or qbo.DemoSource()
    diffs = []
    want = qbo.daily_revenue(demo.query("SalesReceipt"), demo.query("Invoice"))
    got = qbo.daily_revenue(live.query("SalesReceipt"), live.query("Invoice"))
    for d in sorted(set(want) | set(got)):
        if want.get(d) != got.get(d):
            diffs.append(f"revenue {d.isoformat()}: demo {want.get(d)}, live {got.get(d)}")
    a = qbo.build_commitments(demo, as_of).model_dump(exclude={"synthetic"})
    b = qbo.build_commitments(live, as_of).model_dump(exclude={"synthetic"})
    for part in ("purchase_orders", "bills", "estimates"):
        if a[part] != b[part]:
            diffs.append(f"{part} differ: demo {len(a[part])} lines, live {len(b[part])} lines")
    strip = lambda rows: sorted(({k: v for k, v in r.items() if k != "id"} for r in rows),  # noqa: E731
                                key=lambda r: r["name"])
    if strip(a["inventory"]) != strip(b["inventory"]):
        diffs.append("inventory differs")
    for total in ("committed_spend", "expected_revenue", "inventory_value"):
        if a[total] != b[total]:
            diffs.append(f"{total}: demo {a[total]}, live {b[total]}")
    return diffs

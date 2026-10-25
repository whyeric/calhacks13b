"""Generate the SYNTHETIC QuickBooks Online demo company, Hudson Bike Co.

Writes backend/fixtures/quickbooks_demo/*.json, each shaped exactly like a QBO query response
(`{"QueryResponse": {"<Entity>": [...], "startPosition": 1, "maxResults": N}, "time": ...}`), so
`app.integrations.quickbooks` parses demo and live data with the same code.

Revenue comes from frontend/public/samples/hudson_bike_co_daily_revenue.csv: each day's
SalesReceipt (the POS daily batch) plus any Invoices (corporate/group rentals carved out of the
same day) sum to that day's CSV revenue to the cent. The forward-looking books (open purchase
orders, unpaid bills, pending estimates, inventory) are hand-written for "today", 2026-10-25.

Deterministic (seeded RNG). Run from backend/:  .venv/bin/python scripts/gen_quickbooks_demo.py
"""

import csv
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CSV_PATH = BACKEND.parent / "frontend" / "public" / "samples" / "hudson_bike_co_daily_revenue.csv"
OUT = BACKEND / "fixtures" / "quickbooks_demo"
SEED = 20261025
TODAY = date(2026, 10, 25)
QUERY_TIME = "2026-10-25T09:00:00.000-07:00"
CENT = Decimal("0.01")
USD = {"value": "USD", "name": "United States Dollar"}

ITEMS = {  # service items the receipts and invoices reference
    "hourly": {"value": "1", "name": "Hourly rental"},
    "daypass": {"value": "2", "name": "Day pass"},
    "group": {"value": "3", "name": "Group rental package"},
    "tour": {"value": "4", "name": "Guided tour"},
}
WALKUP = {"value": "1", "name": "Walk-up customers (POS daily batch)"}
CORPORATE = [  # fictional customers
    {"value": "11", "name": "Lumen Labs (offsites)"},
    {"value": "12", "name": "Pier 62 Events LLC"},
    {"value": "13", "name": "Northbank Consulting Group"},
    {"value": "14", "name": "Greenway School Trips"},
    {"value": "15", "name": "Meridian Hotel Concierge"},
    {"value": "16", "name": "Harborline Walking Tours"},
]


def num(d: Decimal) -> float:
    """QBO sends amounts as JSON numbers. float repr of a 2-dp Decimal round-trips exactly."""
    return float(d)


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def meta(day: date, hour: int = 21) -> dict:
    stamp = f"{day.isoformat()}T{hour:02d}:05:00-07:00"
    return {"CreateTime": stamp, "LastUpdatedTime": stamp}


def query_file(entity: str, rows: list[dict]) -> dict:
    return {"QueryResponse": {entity: rows, "startPosition": 1, "maxResults": len(rows)}, "time": QUERY_TIME}


def line(n: int, amount: Decimal, item: dict, desc: str, qty: int | None = None) -> dict:
    detail: dict = {"ItemRef": item}
    if qty:
        detail |= {"Qty": qty, "UnitPrice": num((amount / qty).quantize(Decimal("0.00001")))}
    return {"Id": str(n), "LineNum": n, "Description": desc, "Amount": num(amount),
            "DetailType": "SalesItemLineDetail", "SalesItemLineDetail": detail}


def subtotal(amount: Decimal) -> dict:
    return {"Amount": num(amount), "DetailType": "SubTotalLineDetail", "SubTotalLineDetail": {}}


def read_revenue() -> list[tuple[date, Decimal]]:
    lines = [ln for ln in CSV_PATH.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    rows = list(csv.DictReader(lines))
    return [(date.fromisoformat(r["date"]), money(r["revenue"])) for r in rows]


def transactions(rng: random.Random) -> tuple[list[dict], list[dict]]:
    receipts, invoices = [], []
    inv_no = 1001
    for n, (day, total) in enumerate(read_revenue(), start=1):
        warm = 4 <= day.month <= 10
        p = (0.16 if warm else 0.06) * (1.3 if day.weekday() < 5 else 0.7)
        carved = Decimal("0")
        for _ in range(2 if rng.random() < 0.15 else 1):
            if rng.random() >= p:
                continue
            share = Decimal(str(rng.uniform(0.08, 0.30)))
            amount = (total * share / 5).quantize(Decimal("1"), ROUND_HALF_UP) * 5  # quoted in $5 steps
            if amount < 250 or total - carved - amount < total * Decimal("0.5"):
                continue
            carved += amount
            cust = rng.choice(CORPORATE)
            riders = max(4, int(amount / Decimal("85")))
            tour = rng.random() < 0.4
            due = day + timedelta(days=30)
            paid = due + timedelta(days=rng.randint(-10, 20)) < TODAY
            invoices.append({
                "Id": str(5000 + inv_no), "SyncToken": "0", "MetaData": meta(day, 10),
                "DocNumber": f"INV-{inv_no}", "TxnDate": day.isoformat(), "DueDate": due.isoformat(),
                "CurrencyRef": USD, "CustomerRef": cust,
                "SalesTermRef": {"value": "3", "name": "Net 30"},
                "Line": [line(1, amount, ITEMS["tour" if tour else "group"],
                              f"{'Guided tour' if tour else 'Group rental'}, {riders} riders", riders),
                         subtotal(amount)],
                "TotalAmt": num(amount), "Balance": 0.0 if paid else num(amount),
            })
            inv_no += 1
        walkup = total - carved
        hourly = (walkup * Decimal(str(rng.uniform(0.55, 0.75)))).quantize(CENT, ROUND_HALF_UP)
        daypass = walkup - hourly
        receipts.append({
            "Id": str(n), "SyncToken": "0", "MetaData": meta(day),
            "DocNumber": f"POS-{day.strftime('%Y%m%d')}", "TxnDate": day.isoformat(), "CurrencyRef": USD,
            "PrivateNote": "POS daily batch deposit", "CustomerRef": WALKUP,
            "PaymentMethodRef": {"value": "3", "name": "Card (POS batch)"},
            "DepositToAccountRef": {"value": "35", "name": "Checking"},
            "Line": [line(1, hourly, ITEMS["hourly"], "Walk-up hourly rentals"),
                     line(2, daypass, ITEMS["daypass"], "Walk-up day passes"), subtotal(walkup)],
            "TotalAmt": num(walkup), "Balance": 0.0,
        })
    return receipts, invoices


def vendor(i: int, name: str) -> dict:
    return {"value": str(100 + i), "name": name}


V = {
    "velo": vendor(1, "Velo Supply Wholesale"),
    "kettle": vendor(2, "Kettle Rubber Co."),
    "saferide": vendor(3, "SafeRide Helmets"),
    "ironclad": vendor(4, "Ironclad Storage Systems"),
    "harbor": vendor(5, "Harbor Lights Signage"),
    "realty": vendor(6, "Hudson Pier Realty"),
    "insure": vendor(7, "Bluestone Commercial Insurance"),
    "dock": vendor(8, "CityCycle Dock Network"),
    "power": vendor(9, "Metro Power & Gas"),
    "mech": vendor(10, "Gotham Bike Mechanics"),
}


def item_lines(items: list[tuple[str, int, str]]) -> tuple[list[dict], Decimal]:
    out, total = [], Decimal("0")
    for n, (desc, qty, cost) in enumerate(items, start=1):
        amt = money(Decimal(cost) * qty)
        total += amt
        out.append({"Id": str(n), "LineNum": n, "Description": desc, "Amount": num(amt),
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "80", "name": "Inventory Asset"},
                                                      "BillableStatus": "NotBillable",
                                                      "Qty": qty, "UnitPrice": num(Decimal(cost))}})
    return out, total


def purchase_orders() -> list[dict]:
    spec = [  # (doc, vendor, txn, due, status, memo, [(desc, qty, unit cost)])
        ("PO-2039", "kettle", "2026-09-02", "2026-09-28", "Closed", "Fall tire restock (received)",
         [("700c city tires", 60, "38.00")]),
        ("PO-2041", "velo", "2026-10-06", "2027-02-15", "Open", "Spring fleet: 6 Class 1 commuter e-bikes",
         [("Class 1 commuter e-bike", 6, "1850.00")]),
        ("PO-2042", "kettle", "2026-10-12", "2026-11-05", "Open", "Winter tires and tubes",
         [("700c studded winter tires", 80, "41.50"), ("700c inner tubes", 200, "6.25")]),
        ("PO-2043", "saferide", "2026-10-14", "2026-11-12", "Open", "Helmet replacement cycle",
         [("Adult helmet, M/L", 60, "42.00"), ("Kids helmet", 20, "31.00")]),
        ("PO-2044", "ironclad", "2026-10-16", "2026-11-18", "Open", "Winter storage racks for off-season fleet",
         [("Vertical storage rack, 10-bike", 4, "1275.00")]),
        ("PO-2045", "velo", "2026-10-19", "2026-11-08", "Open", "Chains, brake pads, cables",
         [("Chain, 8-speed", 40, "21.40"), ("Brake pads (pair)", 90, "7.80"), ("Brake cable kit", 30, "9.35")]),
        ("PO-2046", "harbor", "2026-10-21", "2026-11-15", "Open", "Winter hours and holiday-ride signage",
         [("Outdoor banner set", 1, "780.00")]),
    ]
    out = []
    for i, (doc, v, txn, due, status, memo, items) in enumerate(spec, start=1):
        lines, total = item_lines(items)
        out.append({"Id": str(7000 + i), "SyncToken": "0", "MetaData": meta(date.fromisoformat(txn), 11),
                    "DocNumber": doc, "TxnDate": txn, "DueDate": due, "POStatus": status, "Memo": memo,
                    "CurrencyRef": USD, "VendorRef": V[v],
                    "APAccountRef": {"value": "33", "name": "Accounts Payable (A/P)"},
                    "Line": lines, "TotalAmt": num(total)})
    return out


def bills() -> list[dict]:
    spec = [  # (doc, vendor, txn, due, total, balance, memo)
        ("HPR-2610", "realty", "2026-10-01", "2026-10-01", "18500.00", "0.00", "October rent, Pier 40 storefront"),
        ("HPR-2611", "realty", "2026-10-20", "2026-11-01", "18500.00", "18500.00", "November rent, Pier 40 storefront"),
        ("HPR-2612", "realty", "2026-10-20", "2026-12-01", "18500.00", "18500.00", "December rent, Pier 40 storefront"),
        ("HPR-2701", "realty", "2026-10-20", "2027-01-01", "18500.00", "18500.00", "January rent, Pier 40 storefront"),
        ("BCI-Q4-26", "insure", "2026-10-15", "2026-11-15", "6240.00", "6240.00",
         "Q4 general liability and fleet insurance"),
        ("CDN-1026", "dock", "2026-10-24", "2026-11-30", "2850.00", "2850.00",
         "Dock station access fee, 3 stations (Nov)"),
        ("VSW-88213", "velo", "2026-10-08", "2026-11-10", "2317.40", "1317.40", "Repair parts: derailleurs, spokes"),
        ("MPG-1026", "power", "2026-10-22", "2026-11-18", "1145.22", "1145.22", "Electric, e-bike charging room"),
        ("GBM-0412", "mech", "2026-10-24", "2026-12-05", "1980.00", "1980.00", "Fall fleet tune-up, 66 bikes"),
        ("KRC-55190", "kettle", "2026-10-18", "2026-12-15", "1320.00", "1320.00", "Tire restock (net 60)"),
    ]
    out = []
    for i, (doc, v, txn, due, total, bal, memo) in enumerate(spec, start=1):
        amt = Decimal(total)
        out.append({"Id": str(8000 + i), "SyncToken": "0", "MetaData": meta(date.fromisoformat(txn), 12),
                    "DocNumber": doc, "TxnDate": txn, "DueDate": due, "PrivateNote": memo, "CurrencyRef": USD,
                    "VendorRef": V[v], "APAccountRef": {"value": "33", "name": "Accounts Payable (A/P)"},
                    "Line": [{"Id": "1", "LineNum": 1, "Description": memo, "Amount": num(amt),
                              "DetailType": "AccountBasedExpenseLineDetail",
                              "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "60", "name": "Operating expenses"},
                                                                "BillableStatus": "NotBillable"}}],
                    "TotalAmt": num(amt), "Balance": num(Decimal(bal))})
    return out


def estimates() -> list[dict]:
    c = {x["name"]: x for x in CORPORATE}
    marathon = {"value": "17", "name": "Five Boroughs Run Club"}
    spec = [  # (doc, customer, txn, event (ShipDate), expires, status, desc, riders, per rider)
        ("EST-311", c["Lumen Labs (offsites)"], "2026-10-09", "2026-11-07", "2026-10-31", "Pending",
         "Team offsite ride, Hudson River Greenway", 40, "140.00"),
        ("EST-312", marathon, "2026-10-10", "2026-11-01", "2026-10-29", "Accepted",
         "Marathon weekend spectator rentals", 55, "80.00"),
        ("EST-314", c["Northbank Consulting Group"], "2026-10-15", "2026-11-14", "2026-11-07", "Pending",
         "Fall team ride and lunch stop", 25, "154.00"),
        ("EST-315", c["Greenway School Trips"], "2026-10-16", "2026-11-20", "2026-11-13", "Accepted",
         "8th-grade field trip, helmets included", 42, "70.00"),
        ("EST-317", c["Pier 62 Events LLC"], "2026-10-20", "2026-12-12", "2026-11-30", "Accepted",
         "Holiday lights night ride (private event)", 95, "150.00"),
        ("EST-318", c["Meridian Hotel Concierge"], "2026-10-22", "2026-12-19", "2026-12-05", "Pending",
         "Holiday-season guest rental block, Dec 19-31", 140, "70.00"),
        ("EST-305", c["Harborline Walking Tours"], "2026-09-12", "2026-10-03", "2026-09-26", "Closed",
         "Bike-and-walk combo tour (invoiced)", 30, "95.00"),
        ("EST-309", c["Lumen Labs (offsites)"], "2026-09-30", "2026-10-17", "2026-10-10", "Rejected",
         "Leaf-peeping day trip", 35, "180.00"),
    ]
    out = []
    for i, (doc, cust, txn, ship, exp, status, desc, riders, per) in enumerate(spec, start=1):
        amt = money(Decimal(per) * riders)
        out.append({"Id": str(9000 + i), "SyncToken": "0", "MetaData": meta(date.fromisoformat(txn), 14),
                    "DocNumber": doc, "TxnDate": txn, "ShipDate": ship, "ExpirationDate": exp,
                    "TxnStatus": status, "CustomerMemo": {"value": desc}, "CurrencyRef": USD, "CustomerRef": cust,
                    "Line": [line(1, amt, ITEMS["tour" if "tour" in desc.lower() else "group"], desc, riders),
                             subtotal(amt)],
                    "TotalAmt": num(amt)})
    return out


def items() -> list[dict]:
    services = [
        {"Id": v["value"], "Name": v["name"], "Type": "Service", "Active": True, "TrackQtyOnHand": False,
         "IncomeAccountRef": {"value": "79", "name": "Rental income"}}
        for v in ITEMS.values()
    ]
    inv = [  # (name, sku, qty on hand, purchase cost, sales price)
        ("Class 1 commuter e-bike", "EB-C1-COM", 24, "1850.00", "2899.00"),
        ("City cruiser bike", "BK-CRZ-7", 60, "420.00", "699.00"),
        ("Kids bike 20in", "BK-KID-20", 18, "260.00", "399.00"),
        ("Tandem bike", "BK-TDM", 6, "980.00", "1499.00"),
        ("Adult helmet, M/L", "HL-ADT-ML", 140, "42.00", "69.00"),
        ("Kids helmet", "HL-KID", 45, "31.00", "49.00"),
        ("700c inner tube", "PT-TUBE-700", 300, "6.25", "12.00"),
        ("700c city tire", "PT-TIRE-700", 85, "38.00", "64.00"),
        ("U-lock with cable", "AC-LOCK-U", 120, "24.50", "45.00"),
        ("Brake pads (pair)", "PT-BRK-PAD", 160, "7.80", "16.00"),
        ("Chain, 8-speed", "PT-CHN-8", 75, "21.40", "38.00"),
        ("Phone mount", "AC-PHN-MNT", 90, "12.75", "25.00"),
        ("Rain poncho (resale)", "AC-PONCHO", 400, "3.10", "10.00"),
    ]
    out = list(services)
    for i, (name, sku, qty, cost, price) in enumerate(inv, start=1):
        out.append({"Id": str(200 + i), "Name": name, "Sku": sku, "Type": "Inventory", "Active": True,
                    "TrackQtyOnHand": True, "QtyOnHand": qty, "InvStartDate": "2024-01-01",
                    "PurchaseCost": num(Decimal(cost)), "UnitPrice": num(Decimal(price)),
                    "AssetAccountRef": {"value": "80", "name": "Inventory Asset"},
                    "IncomeAccountRef": {"value": "79", "name": "Sales of product income"},
                    "ExpenseAccountRef": {"value": "81", "name": "Cost of goods sold"}})
    return out


def company() -> list[dict]:
    return [{"Id": "1", "SyncToken": "0", "CompanyName": "Hudson Bike Co. (SYNTHETIC)",
             "LegalName": "Hudson Bike Co. (SYNTHETIC demo company)", "Country": "US",
             "CompanyAddr": {"Line1": "Pier 40 (fictional storefront)", "City": "New York",
                             "CountrySubDivisionCode": "NY", "PostalCode": "10014"},
             "FiscalYearStartMonth": "January", "CompanyStartDate": "2024-01-01",
             "NameValue": [{"Name": "SyntheticDemoData", "Value": "true"}]}]


README = """# QuickBooks demo company: Hudson Bike Co. (SYNTHETIC)

**Everything in this folder is SYNTHETIC, temporary demo data.** Hudson Bike Co. is a fictional
NYC bike-rental shop; no real business, customer or vendor is described here. The folder can be
deleted and regenerated at any time:

    cd backend && .venv/bin/python scripts/gen_quickbooks_demo.py

Each file is shaped exactly like a QuickBooks Online query response
(`{"QueryResponse": {"<Entity>": [...]}, "time": ...}`), so the demo source and the live Intuit
API go through the same parsing code (`app/integrations/quickbooks.py`).

- `salesreceipt.json` + `invoice.json`: one POS daily-batch SalesReceipt per day plus occasional
  corporate/group Invoices carved out of the same day. Together they sum, to the cent, to each
  day's revenue in `frontend/public/samples/hudson_bike_co_daily_revenue.csv` (2024-01-01 to
  2026-09-30), whose weather effects were planted (about -20% rain, -28% below 40F, +10% above 80F).
- `purchaseorder.json`, `bill.json`, `estimate.json`, `item.json`: forward-looking books as of
  2026-10-25 (open POs, unpaid bills due Nov 2026 to Jan 2027, pending estimates for Nov-Dec 2026,
  inventory). Hand-written, plausible amounts; a few closed/paid/rejected rows test the filters.
- `companyinfo.json`: CompanyName "Hudson Bike Co. (SYNTHETIC)".

See docs/QUICKBOOKS.md.
"""


def main() -> None:
    rng = random.Random(SEED)
    receipts, invoices = transactions(rng)
    files = {
        "companyinfo": ("CompanyInfo", company()),
        "salesreceipt": ("SalesReceipt", receipts),
        "invoice": ("Invoice", invoices),
        "purchaseorder": ("PurchaseOrder", purchase_orders()),
        "bill": ("Bill", bills()),
        "estimate": ("Estimate", estimates()),
        "item": ("Item", items()),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, (entity, rows) in files.items():
        big = entity in ("SalesReceipt", "Invoice")
        text = json.dumps(query_file(entity, rows), separators=(",", ":") if big else None,
                          indent=None if big else 2)
        (OUT / f"{stem}.json").write_text(text + "\n")
        print(f"{stem}.json: {len(rows)} {entity}")
    (OUT / "README.md").write_text(README)


if __name__ == "__main__":
    main()

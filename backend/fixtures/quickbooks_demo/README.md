# QuickBooks demo company: Hudson Bike Co. (SYNTHETIC)

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

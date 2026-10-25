"""Copy contract examples and create explicit mock-only scenario fixtures."""
import copy
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / "backend/fixtures/examples"
dest = root / "frontend/fixtures"
def read(name):
    return json.loads((source / f"{name}.json").read_text(encoding="utf-8"))
def write(name, value):
    (dest / f"{name}.json").write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

businesses = [read("business_taxi"), read("business_restaurant")]
write("businesses", businesses)
analyze = read("analyze_response")
analyze["dropped"].append({**analyze["dropped"][0], "id": "exp_hot_dropped", "event": "hot"})
write("analyze_taxi", analyze)
restaurant = copy.deepcopy(analyze)
for row in restaurant["exposures"] + restaurant["dropped"]:
    row["business_id"] = "restaurant"
rain = restaurant["exposures"][0]
rain.update(effect_usd="-1240.00", ci90=["-1600.00", "-880.00"], direction="negative", hedge_side="yes", beta_settlement="-1265.00")
write("analyze_restaurant", restaurant)
hedges = [read("hedge_partial"), read("hedge_declined"), read("hedge_pending")]
write("hedges_mixed", hedges)
for name, original in [("hedge_proposed_rain", "hedge_partial"), ("hedge_declined_overpriced", "hedge_declined"), ("hedge_pending_over_budget", "hedge_pending")]:
    write(name, read(original))
missing = copy.deepcopy(hedges[1])
missing.update(id="hdg_no_market", ticker=None, market_title=None, market_url=None, close_time=None, match_reason=None,
    h=None, n_target=0, n_filled=0, n_unfilled=0, fills=None, avg_price=None, cost=None, fee=None, premium=None,
    fair=None, expected_cost=None, payoff=None, headline=None)
missing["decision"].update(id="dec_no_market", checks=[{"code":"no_market", "passed":False, "metric":{"n_candidates":0}}], reasons=["no_market"], summary="No open market matches this measured exposure.")
write("hedge_declined_no_market", missing)
approved = copy.deepcopy(hedges[0])
approved.update(status="approved", ledger_entry_ids=["mock_entry"], decided_by="owner", decided_at="2026-10-24T16:00:00Z")
write("hedge_approved", approved)
expired = copy.deepcopy(hedges[0]); expired["status"] = "expired_unapproved"
write("hedge_expired_unapproved", expired)
write("decisions", read("log_entry"))
longtext = copy.deepcopy(hedges)
longtext[0]["market_title"] = "A very long market question about the temperature recorded at the settlement station in New York City during the specified calendar day " * 3
longtext[0]["decision"]["summary"] = "The desk measured this exposure using the supplied data and kept the owner in control. " * 12
write("hedges_longtext", longtext)
negative = copy.deepcopy(businesses)
negative[0]["budget"].update(budget="10000.00", spent="12000.50", remaining="-2000.50", pending="0.00")
write("businesses_negative", negative)

# Precomputed mock server budget snapshots; no financial arithmetic in browser code.
from decimal import Decimal
from itertools import product
snapshots = {}
for states in product(["proposed", "approved", "rejected"], ["pending_approval", "approved", "rejected"]):
    rows = [hedges[0], hedges[2]]
    spent = sum((Decimal(row["premium"]) for row, status in zip(rows, states) if status == "approved"), Decimal(0))
    pending = sum((Decimal(row["premium"]) for row, status in zip(rows, states) if status in ("proposed", "pending_approval")), Decimal(0))
    snapshots["|".join(states)] = {"budget":"250.00", "spent":str(spent.quantize(Decimal(".01"))), "pending":str(pending.quantize(Decimal(".01"))), "remaining":str((Decimal("250")-spent-pending).quantize(Decimal(".01"))), "week_start":"2026-10-26"}
write("budget_snapshots", snapshots)

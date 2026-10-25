"""Stage the demo's bank world in an Increase sandbox, so the bank leg of reconciliation is a real
(sandbox) bank instead of the simulated CSV. See docs/INCREASE.md.

    cd backend && INCREASE_API_KEY=... .venv/bin/python -m scripts.stage_increase_sandbox
    cd backend && .venv/bin/python -m scripts.stage_increase_sandbox --dry-run      # print the plan only

For each business with settled demo hedges (taxi, restaurant) it:

1. creates or reuses an open account "Hedge Desk demo (<business>)" and an active account number;
2. funds it with an inbound ACH "OWNER CAPITAL opening_balance" (the statement's opening
   balance, so the opening transfer can clear; reconcile reports it as outside hedge activity);
3. sends the opening deposit to Kalshi as an outbound ACH ("opening_deposit to Kalshi") and
   simulates its submission;
4. simulates one inbound ACH deposit per winning settled hedge, from "KALSHI". The answer key is
   kept: taxi's hdg_s01 deposit is SHORT BY ITS ENTRY FEE ($60.00 payout, $59.11 deposited), and
   taxi's last winning deposit (hdg_s03) is left PENDING for two days (`resolve_at` = now + 2
   days), a deposit in transit that reconcile must report as timing, not error. (A business with
   a single winning hedge keeps it posted.)

Hedge ids go in the ACH addenda ("Kalshi withdrawal hdg_s01"), standing in for remittance info a
payer may pass. Kalshi wouldn't send our ids, so `--no-references` leaves them out and reconcile
falls back to amount + date matching (which needs the script run within 3 days of settlement:
sandbox transfers post today and can't be backdated).

Safe to re-run: every POST carries a deterministic `Idempotency-Key`, so a repeat replays the first
result instead of moving money twice (a 409 "key already used" means it was staged before).
Sandbox only: it always talks to sandbox.increase.com (a production key is refused there, and
the simulation endpoints exist only in the sandbox). Writes nothing locally (the demo books are rebuilt in a
throwaway database to read the settlements).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app import db
from app.books.ledger import OPENING_DEPOSIT
from app.books.seed import PLANT, seed_books
from app.integrations.increase import IncreaseClient, IncreaseError, usd_to_cents

KEY_PREFIX = "hedge-desk-demo-v1"
# A routing number in valid ABA format and a made-up account: the sandbox moves no real money.
KALSHI_ROUTING = "021000021"
KALSHI_ACCOUNT = "000123456789"
OWNER_CAPITAL = Decimal("1000.00")
TRANSIT_DAYS = 2


@dataclass
class Deposit:
    hedge_id: str
    ticker: str
    amount: Decimal
    note: str
    pending: bool = False


@dataclass
class Plan:
    business_id: str
    opening: Decimal
    deposits: list[Deposit] = field(default_factory=list)


def plans(businesses: list[str] | None = None) -> list[Plan]:
    """The bank world to stage, from the same settled demo hedges `make seed` books (answer key
    included). Built in a throwaway database; the app's db and ledgers are untouched."""
    with tempfile.TemporaryDirectory(prefix="stage_increase_") as d:
        engine = db.make_engine(f"sqlite:///{Path(d) / 'stage.db'}")
        try:
            out = Path(d) / "out"
            out.mkdir()
            ledgers = Path(d) / "ledgers"
            ledgers.mkdir()
            by_business = seed_books(engine, ledger_dir=ledgers, out_dir=out)
        finally:
            engine.dispose()
    result = []
    for business_id, recs in sorted(by_business.items()):
        if businesses and business_id not in businesses:
            continue
        plan = Plan(business_id, OPENING_DEPOSIT)
        winners = sorted((r for r in recs if r.won), key=lambda r: (r.settled_on, r.hedge_id))
        for r in winners:
            if r.hedge_id == PLANT.get(business_id):
                plan.deposits.append(Deposit(r.hedge_id, r.ticker, r.payout - r.fee,
                                             f"PLANTED: short by the {r.fee} entry fee"))
            else:
                plan.deposits.append(Deposit(r.hedge_id, r.ticker, r.payout, "payout"))
        pendable = [x for x in plan.deposits if not x.note.startswith("PLANTED")]
        if pendable and len(plan.deposits) >= 2:  # keep at least one posted deposit per business
            pendable[-1].pending = True
            pendable[-1].note += f", left pending {TRANSIT_DAYS} days (in transit)"
        result.append(plan)
    return result


def _key(*parts: str) -> str:
    return "-".join((KEY_PREFIX, *parts))


def _post(label: str, fn, *args, **kw) -> dict | None:
    """Run one idempotent POST; a 409 on the key means it was staged before."""
    try:
        out = fn(*args, **kw)
        print(f"  ok      {label}: {out.get('id', '')}")
        return out
    except IncreaseError as e:
        if e.status == 409 and (e.type or "").startswith("idempotency"):
            print(f"  exists  {label}: {e.detail.get('resource_id') or 'already staged'}")
            return None
        raise


def stage(client: IncreaseClient, plan: Plan, *, references: bool = True,
          now: datetime | None = None, program_id: str | None = None) -> str:
    """Stage one business; returns its account id."""
    now = now or datetime.now(UTC)
    b = plan.business_id
    name = f"Hedge Desk demo ({b})"
    account = next((a for a in client.list_accounts() if a.get("name") == name), None)
    if account is None:
        account = client.create_account(name, idempotency_key=_key(b, "account"), program_id=program_id)
        print(f"  ok      account {name}: {account['id']}")
    else:
        print(f"  reuse   account {name}: {account['id']}")
    numbers = client.list_account_numbers(account["id"])
    number = numbers[0] if numbers else client.create_account_number(
        account["id"], "Operating", idempotency_key=_key(b, "account-number"))
    print(f"  {'reuse' if numbers else 'ok':7} account number: {number['id']}")

    _post("owner capital (opening balance)", client.simulate_inbound_ach_transfer,
          number["id"], usd_to_cents(OWNER_CAPITAL), company_name="OWNER", company_entry_description="CAPITAL",
          addenda="OWNER CAPITAL opening_balance", idempotency_key=_key(b, "opening-balance"))
    transfer = _post("opening deposit to Kalshi", client.create_ach_transfer,
                     account["id"], usd_to_cents(plan.opening), statement_descriptor="opening_deposit to Kalshi",
                     account_number=KALSHI_ACCOUNT, routing_number=KALSHI_ROUTING, individual_name="Kalshi",
                     idempotency_key=_key(b, "opening-deposit"))
    if transfer is not None and transfer.get("status") in ("pending_approval", "pending_submission"):
        try:
            client.simulate_ach_transfer_submit(transfer["id"])
            print(f"  ok      submitted {transfer['id']}")
        except IncreaseError as e:  # already moving; not worth failing the run over
            print(f"  skip    submit {transfer['id']}: {e.message}")

    for dep in plan.deposits:
        _post(f"deposit {dep.hedge_id} ${dep.amount} ({dep.note})", client.simulate_inbound_ach_transfer,
              number["id"], usd_to_cents(dep.amount), company_name="KALSHI", company_entry_description="WITHDRAWAL",
              addenda=f"Kalshi withdrawal {dep.hedge_id}" if references else None,
              resolve_at=now + timedelta(days=TRANSIT_DAYS) if dep.pending else None,
              idempotency_key=_key(b, dep.hedge_id, "deposit"))
    return account["id"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.stage_increase_sandbox")
    parser.add_argument("--api-key", default=os.environ.get("INCREASE_API_KEY"), help="sandbox key (default: env)")
    parser.add_argument("--business", action="append", help="only this business (repeatable)")
    parser.add_argument("--program-id", help="Increase program, if your group has more than one")
    parser.add_argument("--no-references", action="store_true", help="leave hedge ids out of the ACH addenda")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; call nothing")
    args = parser.parse_args(argv)

    todo = plans(args.business)
    for p in todo:
        print(f"{p.business_id}: opening deposit ${p.opening} out to Kalshi")
        for d in p.deposits:
            print(f"  deposit {d.hedge_id} {d.ticker} ${d.amount} ({d.note})")
    if args.dry_run:
        return 0
    if not args.api_key:
        print("Set INCREASE_API_KEY (a sandbox key) or pass --api-key.", file=sys.stderr)
        return 2
    accounts = {}
    with IncreaseClient(args.api_key, "sandbox") as client:
        for p in todo:
            print(f"staging {p.business_id} in the Increase sandbox")
            accounts[p.business_id] = stage(client, p, references=not args.no_references,
                                            program_id=args.program_id)
    print("\nAdd to .env:\n  INCREASE_ENVIRONMENT=sandbox\n  INCREASE_ACCOUNT_ID="
          + ",".join(f"{b}={a}" for b, a in accounts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Push the SYNTHETIC Hudson Bike Co. books into a connected Intuit **sandbox** company.

Prerequisite: live mode (`QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, `QBO_ENVIRONMENT=sandbox`,
`DEMO_OFFLINE=0`) and a sandbox company connected through the app (`POST
/integrations/quickbooks/connect`, then Intuit's consent screen). The connection is read from the
app DB (`DATABASE_URL`), so run this with the same `.env` as the API.

    cd backend
    .venv/bin/python scripts/seed_qbo_sandbox.py            # seed (idempotent), then verify
    .venv/bin/python scripts/seed_qbo_sandbox.py --verify   # only compare the sandbox with the demo

Refuses a production company. Re-running creates nothing that is already there (documents are
matched by DocNumber, names by DisplayName/Name, payments by each document's open balance).
Logic: `app/integrations/qbo_seed.py`; docs: docs/QUICKBOOKS.md.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.integrations import qbo_seed  # noqa: E402
from app.integrations import quickbooks as qbo  # noqa: E402

AS_OF = date(2026, 10, 25)  # the demo company's "today"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="seed_qbo_sandbox.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--verify", action="store_true", help="only compare the sandbox with the demo company")
    p.add_argument("--interval", type=float, default=None,
                   help="seconds between batch requests (default QBO_SEED_BATCH_INTERVAL_S, 1.6)")
    args = p.parse_args(argv)

    settings = get_settings()
    conn = qbo.get()
    try:
        client = conn.live()
        qbo_seed.require_sandbox(client)
    except qbo.QuickBooksError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 2
    print(f"QuickBooks sandbox company {conn.company_name or ''} (realm {client.realm_id})")

    if not args.verify:
        interval = settings.qbo_seed_batch_interval_s if args.interval is None else args.interval
        result = qbo_seed.Seeder(client, interval_s=interval).run()
        print("seeded:\n" + result.summary())
        for f in result.faults[:20]:
            print(f"  fault: {f}", file=sys.stderr)
        if result.faults:
            print("Some documents failed; fix the cause and re-run (re-runs skip what exists).", file=sys.stderr)
            return 1

    diffs = qbo_seed.compare_with_demo(client, AS_OF)
    if diffs:
        print(f"The sandbox differs from the demo company in {len(diffs)} place(s):")
        for d in diffs[:30]:
            print(f"  {d}")
        return 1
    print("Verified: the sandbox's daily revenue and commitments match the demo company to the cent, "
          "so live research gives the demo's report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

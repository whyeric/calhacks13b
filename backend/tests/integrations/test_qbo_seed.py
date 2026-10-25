"""Sandbox seeder: pushes the SYNTHETIC demo company into a (fake) sandbox through /batch, paced
and backed off, idempotently, never into production; then live research on the seeded company
equals the demo's. FakeQbo; no network."""

from decimal import Decimal

import pytest

from app.integrations import qbo_seed
from app.integrations import quickbooks as qbo

from .conftest import NOW, FakeQbo, connect_live, live_settings

pytestmark = pytest.mark.usefixtures("fresh_qbo")


@pytest.fixture(scope="module")
def demo():
    return qbo_seed.load_demo()


def seeded(monkeypatch, demo, *, interval=1.6):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    clock_s = iter(range(0, 10_000))
    seeder = qbo_seed.Seeder(q.live(), interval_s=interval, monotonic=lambda: float(next(clock_s)) * 0.5)
    return fake, q, seeder.run(demo)


def test_refuses_production(monkeypatch):
    fake = FakeQbo(host="quickbooks.api.intuit.com")
    q = connect_live(fake, monkeypatch, live_settings(qbo_environment="production"))
    client = q.live()
    assert client.environment == "production"
    with pytest.raises(qbo_seed.ProductionRefused, match="not a sandbox"):
        qbo_seed.Seeder(client)
    assert not [r for r in fake.requests if r.method == "POST" and "/v3/company/" in str(r.url)]  # nothing written


def test_script_refuses_production(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    from app import config

    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_qbo_sandbox.py"
    spec = importlib.util.spec_from_file_location("seed_qbo_sandbox", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    fake = FakeQbo(host="quickbooks.api.intuit.com")
    for k, v in {"QBO_CLIENT_ID": "cid", "QBO_CLIENT_SECRET": "csecret", "DEMO_OFFLINE": "0",
                 "QBO_ENVIRONMENT": "production"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    qbo.reset()
    connect_live(fake, monkeypatch, config.get_settings())
    assert script.main([]) == 2
    assert "not a sandbox" in capsys.readouterr().err


def test_seed_matches_demo_to_the_cent(monkeypatch, demo, fresh_qbo):
    fake, q, result = seeded(monkeypatch, demo)
    assert not result.faults, result.faults[:5]
    assert all(n <= qbo.BATCH_LIMIT for n in fake.batch_sizes) and max(fake.batch_sizes) == qbo.BATCH_LIMIT
    assert result.created["SalesReceipt"] == 1004 and result.created["Invoice"] == 163
    assert result.created["PurchaseOrder"] == 7 and result.created["Bill"] == 10 and result.created["Estimate"] == 8
    paid = sum(1 for i in demo["Invoice"] if qbo._money(i["Balance"]) < qbo._money(i["TotalAmt"]))
    assert result.created["BillPayment"] == 2 and result.created["Payment"] == paid > 150
    assert result.batches == len(fake.batch_sizes)
    assert fresh_qbo and all(0 < w <= 1.6 for w in fresh_qbo)  # paced between batches
    # every created document carries the seed tag; the parser hides it
    assert all(qbo.SEED_TAG in d["PrivateNote"] for d in fake.creates("Bill"))

    live = q.live()
    assert qbo_seed.compare_with_demo(live, NOW.date()) == []
    c = q.commitments()
    partly = next(b for b in c.bills if b.id == "VSW-88213")
    assert partly.status == "Partially paid" and partly.amount == Decimal("1317.40")
    assert partly.description == "Repair parts: derailleurs, spokes"
    assert c.committed_spend == Decimal("96881.12") and c.expected_revenue == Decimal("40840.00")


def test_live_research_on_seeded_sandbox_equals_demo(monkeypatch, demo):
    from app.integrations.quickbooks import DemoSource
    from app.stats import research

    _, q, _ = seeded(monkeypatch, demo, interval=0)
    live = q.research()
    want = research.run(qbo.revenue_csv(qbo.daily_revenue(DemoSource().query("SalesReceipt"),
                                                          DemoSource().query("Invoice")), qbo.DEMO_NOTES), None)
    assert not live.synthetic and live.days == 1004
    assert live.report.hypotheses == want.hypotheses  # same fits, same verdicts, same dollars
    assert live.commitments.model_dump(exclude={"synthetic", "inventory"}) == \
        qbo.build_commitments(DemoSource(), NOW.date()).model_dump(exclude={"synthetic", "inventory"})


def test_rerun_creates_nothing(monkeypatch, demo):
    fake, q, first = seeded(monkeypatch, demo, interval=0)
    counts = {e: len(fake.creates(e)) for e in fake._entities()}
    again = qbo_seed.Seeder(q.live(), interval_s=0).run(demo)
    assert dict(again.created) == {} and not again.faults
    assert {e: len(fake.creates(e)) for e in fake._entities()} == counts
    assert again.existing["SalesReceipt"] == 1004 and again.existing["BillPayment"] == 2
    assert qbo_seed.compare_with_demo(q.live(), NOW.date()) == []


def test_partial_run_resumes(monkeypatch, demo):
    """A run that died after the receipts picks up where it stopped."""
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    s = qbo_seed.Seeder(q.live(), interval_s=0)
    s.accounts(demo)
    s.names(demo)
    half = {**demo, "Invoice": demo["Invoice"][:50]}
    s.transactions(half)
    result = qbo_seed.Seeder(q.live(), interval_s=0).run(demo)
    assert result.created["Invoice"] == 113 and result.existing["Invoice"] == 50
    assert "SalesReceipt" not in result.created
    assert qbo_seed.compare_with_demo(q.live(), NOW.date()) == []


def test_throttled_batches_back_off_and_finish(monkeypatch, demo, fresh_qbo):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    seeder = qbo_seed.Seeder(q.live(), interval_s=0)
    fake.throttle = 2  # the first two calls get 429
    result = seeder.run(demo)
    assert not result.faults and fresh_qbo[:2] == [1.0, 2.0]
    assert qbo_seed.compare_with_demo(q.live(), NOW.date()) == []


def test_faults_are_reported_not_fatal(monkeypatch, demo):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    fake.tables["Customer"] = []
    orig = fake.create

    def picky(entity, obj):
        if entity == "Estimate" and obj.get("DocNumber") == "EST-311":
            raise ValueError("Business Validation Error")
        return orig(entity, obj)

    monkeypatch.setattr(fake, "create", picky)
    result = qbo_seed.Seeder(q.live(), interval_s=0).run(demo)
    assert result.faults == ["Estimate EST-311: Business Validation Error"]
    assert result.created["Estimate"] == 7

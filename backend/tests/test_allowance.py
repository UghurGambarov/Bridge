"""T2 autonomy: allowance inside limits, holds above caps, anti-splitting (T2-003), rate limit."""
from decimal import Decimal

from sqlmodel import select

from app import payments
from app.models import FxLedgerEntry, PaymentIntent, Transfer
from app.quota import ledger
from app.sandbox import clock
from app.security.policy import PolicyContext
from app.security.ratelimit import RateLimiter
from tests.conftest import approve

ALLOWANCE = {"purpose": "allowance", "payer_id": "p_zhang_min", "payee_channel_id": "ch_li_wei_gbp",
             "amount": 1200, "currency": "GBP"}


def test_monthly_allowance_runs_autonomously(session, ctx):
    assert payments.run_due_allowances(session, ctx) == []  # October already handled
    clock.advance(session, months=1)
    results = payments.run_due_allowances(session, ctx)
    assert len(results) == 1
    r = results[0]
    assert r["intent"].tier == "T2" and r["transfer"] is not None
    assert session.get(PaymentIntent, r["intent"].id).status == "executed"
    assert r["transfer"].usd_equivalent == Decimal("1554.93")
    assert r["transfer"].receipt_pdf_path
    # Same period does not run twice.
    assert payments.run_due_allowances(session, ctx) == []


def test_extra_2000_is_held_above_cap(session, ctx):
    d, intent = payments.create_intent(session, {**ALLOWANCE, "amount": 2000}, ctx)
    assert d.outcome == "require_approval" and intent.status == "held" and intent.tier == "T3"
    assert d.rule_id == "T2-002"
    e, t = payments.execute(session, intent.id, ctx)
    assert e.rule_id == "T3-001" and t is None


def test_held_allowance_can_be_approved(session, ctx, devices):
    _, intent = payments.create_intent(session, {**ALLOWANCE, "amount": 2000}, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    approve(session, intent.id, "p_li_wei", devices)
    d, t = payments.execute(session, intent.id, ctx)
    assert d.outcome == "allow" and t is not None


def test_allowance_to_other_account_blocked(session, ctx):
    d, intent = payments.create_intent(session, {**ALLOWANCE, "payee_channel_id": "ch_northbridge_gbp"}, ctx)
    assert d.rule_id == "T2-001" and intent.status == "blocked"


def test_rolling_30_day_cap(session, ctx):
    for _ in range(2):
        payments.create_and_maybe_autoexecute(session, {**ALLOWANCE, "amount": 1000}, ctx)  # ~USD 1,296 each
    d, intent = payments.create_intent(session, {**ALLOWANCE, "amount": 1000}, ctx)
    assert intent.status == "held" and d.rule_id == "T2-002"


def test_third_payment_in_24h_escalates(session, ctx):
    for _ in range(2):
        r = payments.create_and_maybe_autoexecute(session, {**ALLOWANCE, "amount": 100}, ctx)
        assert r["transfer"] is not None
    d, intent = payments.create_intent(session, {**ALLOWANCE, "amount": 100}, ctx)
    assert intent.status == "held" and any(c.rule_id == "T2-003" for c in d.checks)


def test_explicit_split_request_escalates(session):
    split_ctx = PolicyContext(split_request=True)
    d, intent = payments.create_intent(session, {**ALLOWANCE, "amount": 300}, split_ctx)
    assert intent.status == "held" and d.rule_id == "T2-003"


def test_insufficient_quota_holds_with_documented_route(session, ctx):
    session.add(FxLedgerEntry(person_id="p_zhang_min", year=2026, usd_amount=Decimal("24500"), cny_amount=Decimal("173950"),
                              currency="USD", foreign_amount=Decimal("24500"), purpose="tuition",
                              payee_channel_id="ch_northbridge_gbp", reference="NBU-26000001",
                              created_at=clock.now(session)))
    session.commit()
    assert ledger.remaining_usd(session, "p_zhang_min") == Decimal("500.00")
    d, intent = payments.create_intent(session, ALLOWANCE, ctx)
    assert intent.status == "held" and intent.route == "above_quota_documented"
    assert any(c.rule_id == "Q-002" for c in d.checks)


def test_t2_execution_rechecks_limits(session, ctx):
    _, a = payments.create_intent(session, {**ALLOWANCE, "amount": 1500}, ctx)
    _, b = payments.create_intent(session, {**ALLOWANCE, "amount": 1500}, ctx)
    assert a.tier == b.tier == "T2"
    assert payments.execute(session, a.id, ctx)[1] is not None
    d, t = payments.execute(session, b.id, ctx)  # rolling cap now exceeded
    assert t is None and d.rule_id == "T2-002"
    assert session.get(PaymentIntent, b.id).status == "held"
    assert len(session.exec(select(Transfer)).all()) == 1


def test_rate_limiter():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    assert [rl.check("s1") for _ in range(4)] == [True, True, True, False]
    assert rl.check("s2")

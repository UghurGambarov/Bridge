"""FX maths, personal quota, routes and the demo quota story (SPEC §7)."""
from decimal import Decimal

import pytest

from app.quota import ledger, planner
from app.sandbox import clock, fx


def test_gbp_quote_matches_story():
    q = fx.quote("GBP", Decimal("13250"))
    assert q.cny_amount == Decimal("121900.00")
    assert q.usd_equivalent == Decimal("17169.01")
    assert q.fee_cny == Decimal("50.00")
    assert q.total_cny_debit == Decimal("121950.00")
    assert q.label == "simulated"


@pytest.mark.parametrize("cur,amount,cny,usd", [
    ("USD", "1000", "7100.00", "1000.00"),
    ("HKD", "10000", "9100.00", "1281.69"),
    ("GBP", "1200", "11040.00", "1554.93"),
    ("GBP", "2000", "18400.00", "2591.55"),
    ("GBP", "7800", "71760.00", "10107.04"),
    ("EUR", "100", "780.00", "109.86"),
])
def test_conversions_are_deterministic(cur, amount, cny, usd):
    assert fx.to_cny(cur, Decimal(amount)) == Decimal(cny)
    assert fx.to_usd(cur, Decimal(amount)) == Decimal(usd)
    assert fx.quote(cur, Decimal(amount)).usd_equivalent == fx.quote(cur, Decimal(amount)).usd_equivalent


def test_unsupported_currency_and_bad_amount():
    with pytest.raises(fx.UnsupportedCurrency):
        fx.rate_cny("JPY")
    with pytest.raises(ValueError):
        fx.quote("GBP", Decimal("0"))


def test_seeded_quota_is_personal(session):
    assert ledger.used_usd(session, "p_zhang_min") == Decimal("25000.00")
    assert ledger.remaining_usd(session, "p_zhang_min") == Decimal("25000.00")
    # Quotas are never pooled: the uncle's quota is separate and untouched.
    assert ledger.used_usd(session, "p_zhang_qiang") == Decimal("0.00")


def test_autumn_tuition_fits_within_quota(session):
    p = planner.plan(session, "p_zhang_min", "GBP", Decimal("13250"))
    assert p.route == planner.WITHIN
    assert p.usd_equivalent == Decimal("17169.01")
    assert p.remaining_after_usd == Decimal("7830.99")
    assert p.checklist == ["Payer's ID card (ID only — within quota)"]


def test_accommodation_above_remaining_goes_documented_route(session):
    ledger.record(session, person_id="p_zhang_min", usd_amount=Decimal("17169.01"), cny_amount=Decimal("121900"),
                  currency="GBP", foreign_amount=Decimal("13250"), purpose="tuition",
                  payee_channel_id="ch_northbridge_gbp", reference="NBU-26004217")
    ledger.record(session, person_id="p_zhang_min", usd_amount=Decimal("1554.93"), cny_amount=Decimal("11040"),
                  currency="GBP", foreign_amount=Decimal("1200"), purpose="allowance",
                  payee_channel_id="ch_li_wei_gbp", reference="ALLOWANCE-2026-11")
    session.commit()
    assert ledger.remaining_usd(session, "p_zhang_min") == Decimal("6276.06")
    p = planner.plan(session, "p_zhang_min", "GBP", Decimal("7800"))
    assert p.route == planner.ABOVE
    assert p.usd_equivalent == Decimal("10107.04")
    assert "Admission letter" in p.checklist
    assert any("relationship" in c.lower() for c in p.checklist)


def test_quota_card(session):
    card = ledger.quota_card(session, "p_zhang_min", Decimal("17169.01"))
    assert card["used_usd"] == "25000.00" and card["remaining_after_usd"] == "7830.99" and card["fits"] is True
    assert card["annual_limit_usd"] == "50000.00"


def test_no_carry_over_into_next_calendar_year(session):
    clock.advance(session, months=3)  # 2026-10-17 -> 2027-01-17
    assert clock.now(session).year == 2027
    assert ledger.used_usd(session, "p_zhang_min") == Decimal("0.00")
    assert ledger.remaining_usd(session, "p_zhang_min") == Decimal("50000.00")


def test_add_months_clamps_day():
    from datetime import datetime

    assert clock.add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)
    assert clock.add_months(datetime(2026, 11, 15), 2) == datetime(2027, 1, 15)

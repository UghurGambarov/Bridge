"""Personal FX quota ledger (rule Q-001). The quota always belongs to ONE person."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from ..config import rule_param
from ..models import FxLedgerEntry
from ..sandbox import clock
from ..sandbox.fx import q2


def annual_limit_usd() -> Decimal:
    return Decimal(str(rule_param("Q-001", "annual_limit_usd")))


def used_usd(session: Session, person_id: str, year: Optional[int] = None) -> Decimal:
    year = year or clock.now(session).year
    rows = session.exec(select(FxLedgerEntry).where(FxLedgerEntry.person_id == person_id, FxLedgerEntry.year == year))
    return q2(sum((r.usd_amount for r in rows), Decimal("0")))


def remaining_usd(session: Session, person_id: str, year: Optional[int] = None) -> Decimal:
    return max(Decimal("0.00"), q2(annual_limit_usd() - used_usd(session, person_id, year)))


def record(session: Session, *, person_id: str, usd_amount: Decimal, cny_amount: Decimal, currency: str,
           foreign_amount: Decimal, purpose: str, payee_channel_id: Optional[str], reference: Optional[str],
           intent_id: Optional[str] = None) -> FxLedgerEntry:
    now = clock.now(session)
    entry = FxLedgerEntry(
        person_id=person_id, year=now.year, usd_amount=usd_amount, cny_amount=cny_amount, currency=currency,
        foreign_amount=foreign_amount, purpose=purpose, payee_channel_id=payee_channel_id,
        reference=reference, intent_id=intent_id, created_at=now,
    )
    session.add(entry)
    return entry


def quota_card(session: Session, person_id: str, this_payment_usd: Optional[Decimal] = None) -> dict:
    """The `quota` card: used / remaining out of the annual limit, for the payer only."""
    used = used_usd(session, person_id)
    remaining = remaining_usd(session, person_id)
    card = {
        "person_id": person_id,
        "year": clock.now(session).year,
        "annual_limit_usd": f"{annual_limit_usd():.2f}",
        "used_usd": f"{used:.2f}",
        "remaining_usd": f"{remaining:.2f}",
        "rule_id": "Q-001",
    }
    if this_payment_usd is not None:
        card["this_payment_usd"] = f"{q2(this_payment_usd):.2f}"
        card["fits"] = this_payment_usd <= remaining
        card["remaining_after_usd"] = f"{max(Decimal('0'), q2(remaining - this_payment_usd)):.2f}"
        card["excess_usd"] = f"{max(Decimal('0'), q2(this_payment_usd - remaining)):.2f}"
    return card

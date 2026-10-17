"""Structuring detection: Q-003 (several purchasers, one obligation) and T2-003 (splitting)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from ..config import rule_param
from ..models import FxLedgerEntry, PaymentIntent, Transfer

# Intents that count as "funding" an obligation even before execution.
LIVE_STATUSES = ("draft", "awaiting_documents", "pending_approval", "held", "approved", "executed")


def purchasers_for(session: Session, channel_id: str, reference: str, exclude_intent_id: Optional[str] = None) -> set[str]:
    people = {
        e.person_id for e in session.exec(
            select(FxLedgerEntry).where(FxLedgerEntry.payee_channel_id == channel_id, FxLedgerEntry.reference == reference)
        )
    }
    for i in session.exec(select(PaymentIntent).where(
        PaymentIntent.payee_channel_id == channel_id, PaymentIntent.reference == reference,
    )):
        if i.status in LIVE_STATUSES and i.id != exclude_intent_id:
            people.add(i.payer_id)
    return people


def check_q003(session: Session, payer_id: str, channel_id: str, reference: Optional[str],
               exclude_intent_id: Optional[str] = None) -> tuple[bool, str]:
    """Returns (ok, detail). Blocks when >= N distinct purchasers fund the same (payee, reference)."""
    if not reference:
        return True, "No payment reference; structuring check not applicable."
    purchasers = purchasers_for(session, channel_id, reference, exclude_intent_id) | {payer_id}
    threshold = int(rule_param("Q-003", "min_distinct_purchasers", 2))
    if len(purchasers) >= threshold:
        return False, f"{len(purchasers)} different purchasers fund the same payee and reference {reference}."
    return True, "Only the payer funds this obligation."


def t2_window_stats(session: Session, channel_id: str, now: datetime, exclude_intent_id: Optional[str] = None) -> dict:
    """Executed payments to one payee: USD sum over 30 days and count within the T2-003 window."""
    window_h = int(rule_param("T2-003", "window_hours", 24))
    transfers = [
        t for t in session.exec(select(Transfer).where(Transfer.payee_channel_id == channel_id))
        if t.intent_id != exclude_intent_id
    ]
    sum_30d = sum((t.usd_equivalent for t in transfers if t.executed_at >= now - timedelta(days=30)), Decimal("0"))
    count_window = sum(1 for t in transfers if t.executed_at >= now - timedelta(hours=window_h))
    return {"sum_30d_usd": sum_30d, "count_window": count_window, "window_hours": window_h}

"""Personal FX quota (payer only) and simulated FX quotes."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..quota import ledger
from ..sandbox import fx
from ..seed import PAYER_ID
from .deps import deny, get_db

router = APIRouter(tags=["quota"])


@router.get("/quota/{person_id}")
def quota(person_id: str, db: Session = Depends(get_db)):
    if person_id != PAYER_ID:
        # Quotas are personal and never combined; the app shows only the payer's (P-004, T4-003).
        raise deny(403, "P-004", "Only the payer's own quota is shown.")
    return {"type": "quota", **ledger.quota_card(db, person_id)}


@router.get("/fx/quote")
def quote(currency: str, amount: str):
    try:
        return {"type": "fx_quote", **fx.quote(currency, Decimal(amount)).card()}
    except (fx.UnsupportedCurrency, InvalidOperation, ValueError) as e:
        raise deny(400, "SYS-003", f"Invalid quote request: {e}")

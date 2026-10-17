"""Privileged sandbox controls: freeze (SYS-001) and advance the sandbox clock (runs due allowances).

Every call is written to the audit log (known risk R-14: these controls are privileged).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import payments, state
from ..agent.orchestrator import dedupe_cards, system_message
from ..agent.tools import intent_card, receipt_card
from ..sandbox import clock
from ..security import audit
from ..security.policy import PolicyContext
from ..seed import PAYER_ID, STUDENT_ID
from .deps import get_db
from .intents import _post_to_chat

router = APIRouter(tags=["admin"])


class FreezeBody(BaseModel):
    frozen: bool


@router.post("/admin/freeze")
def freeze(body: FreezeBody, db: Session = Depends(get_db)):
    state.set_frozen(db, body.frozen)
    audit.append(db, actor="system", event="freeze_changed", rule_id="SYS-001",
                 decision="deny" if body.frozen else "allow", payload={"frozen": body.frozen})
    return {"frozen": state.is_frozen(db)}


@router.get("/admin/state")
def get_state(request: Request, db: Session = Depends(get_db)):
    return {"frozen": state.is_frozen(db), "now": clock.now(db).isoformat(), "model_label": request.app.state.model_label}


class ClockBody(BaseModel):
    months: int = Field(default=1, ge=0, le=12)
    days: int = Field(default=0, ge=0, le=60)
    minutes: int = Field(default=0, ge=0, le=1440)
    session_id: Optional[str] = None


@router.post("/admin/advance-clock")
def advance_clock(body: Optional[ClockBody] = None, db: Session = Depends(get_db)):
    body = body or ClockBody()
    now = clock.advance(db, months=body.months, days=body.days, minutes=body.minutes)
    audit.append(db, actor="system", event="clock_advanced",
                 payload={"months": body.months, "days": body.days, "minutes": body.minutes, "now": now.isoformat()})
    ctx = PolicyContext(payer_id=PAYER_ID, student_id=STUDENT_ID, actor="system")
    results, cards, lines = [], [], []
    for r in payments.run_due_allowances(db, ctx):
        intent, transfer = r["intent"], r["transfer"]
        if intent is None:
            lines.append(f"Allowance could not be prepared ({r['decision'].rule_id}).")
            continue
        if transfer is not None:
            cards += [receipt_card(transfer, intent), intent_card(db, intent, STUDENT_ID)]
            lines.append(f"Monthly allowance {intent.currency} {intent.amount:,.2f} sent automatically to Li Wei's own "
                         f"verified account (T2, within limits). Reference {transfer.bank_reference}.")
        else:
            cards.append(intent_card(db, intent, STUDENT_ID))
            lines.append(f"Monthly allowance {intent.currency} {intent.amount:,.2f} is held for approval: {intent.status_reason}")
        results.append({"intent_id": intent.id, "status": intent.status, "tier": intent.tier,
                        "transfer_id": transfer.id if transfer else None})
    out = {"messages": [system_message(" ".join(lines))] if lines else [], "cards": dedupe_cards(cards)}
    _post_to_chat(db, body.session_id, out)
    return {"now": now.isoformat(), "results": results, **out}

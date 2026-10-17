"""Payment intents: list, detail, Why trace, approval challenge/approve/reject, bank verification, receipts.

Approvals are human actions from the persona's own device (HMAC over the digest). The agent has
no route here; it only learns that approvals are complete.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import payments
from ..agent.orchestrator import system_message
from ..agent.tools import checklist_card, explanation_card, intent_card, receipt_card
from ..config import get_settings
from ..models import ChatMessage, ChatSession, PaymentIntent, Transfer
from ..sandbox import clock
from ..security import approvals
from ..security.approvals import ApprovalError
from ..seed import STUDENT_ID
from .deps import deny, get_db, require_persona

router = APIRouter(tags=["intents"])


def _intent(db: Session, intent_id: str) -> PaymentIntent:
    intent = db.get(PaymentIntent, intent_id)
    if intent is None:
        raise deny(404, "SYS-003", "Unknown intent.")
    return intent


@router.get("/intents")
def list_intents(db: Session = Depends(get_db)):
    rows = db.exec(select(PaymentIntent).order_by(PaymentIntent.created_at.desc())).all()
    return {"intents": [intent_card(db, i, STUDENT_ID) for i in rows]}


@router.get("/intents/{intent_id}")
def get_intent(intent_id: str, db: Session = Depends(get_db)):
    intent = _intent(db, intent_id)
    card = intent_card(db, intent, STUDENT_ID)
    t = db.exec(select(Transfer).where(Transfer.intent_id == intent_id)).first()
    card["receipt"] = receipt_card(t, intent) if t else None
    card["checklist"] = checklist_card(intent)
    return card


@router.get("/intents/{intent_id}/why")
def why(intent_id: str, db: Session = Depends(get_db)):
    """The Why panel: every rule check with its result, detail and source."""
    return explanation_card(db, _intent(db, intent_id))


class ChallengeBody(BaseModel):
    person_id: str
    device_id: str


@router.post("/intents/{intent_id}/challenge")
def challenge(intent_id: str, body: ChallengeBody, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    try:
        ch = approvals.issue_challenge(db, intent_id, body.person_id, body.device_id, STUDENT_ID)
    except ApprovalError as e:
        raise deny(403, e.rule_id, e.reason)
    return {**ch, "intent": intent_card(db, _intent(db, intent_id), STUDENT_ID)}


class ApproveBody(BaseModel):
    person_id: str
    device_id: str
    nonce: str = Field(max_length=64)
    mac: str = Field(max_length=128)
    session_id: Optional[str] = None


def _post_to_chat(db: Session, session_id: Optional[str], out: dict) -> None:
    if session_id and db.get(ChatSession, session_id) is not None and (out.get("messages") or out.get("cards")):
        db.add(ChatMessage(session_id=session_id, payload={}, display={"user": None, **out}, created_at=clock.now(db)))
        db.commit()


@router.post("/intents/{intent_id}/approve")
def approve(intent_id: str, body: ApproveBody, request: Request, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    try:
        status = approvals.submit_approval(db, intent_id, body.person_id, body.device_id, body.nonce, body.mac, STUDENT_ID)
    except ApprovalError as e:
        raise deny(403, e.rule_id, e.reason)
    agent = None
    if status["complete"]:
        # The backend tells the agent session; the agent calls execute_payment (through the policy engine).
        chat_id = body.session_id or _latest_chat(db)
        if chat_id:
            agent = request.app.state.orchestrator.handle_event(db, chat_id, "approvals_complete", intent_id, body.person_id)
    return {"approval_status": status, "intent": intent_card(db, _intent(db, intent_id), STUDENT_ID), "agent": agent}


def _latest_chat(db: Session) -> Optional[str]:
    cs = db.exec(select(ChatSession).order_by(ChatSession.created_at.desc())).first()
    return cs.id if cs else None


class RejectBody(BaseModel):
    person_id: str
    reason: str = Field(default="Rejected by approver", max_length=200)


@router.post("/intents/{intent_id}/reject")
def reject(intent_id: str, body: RejectBody, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    try:
        intent = approvals.reject(db, intent_id, body.person_id, body.reason, STUDENT_ID)
    except ApprovalError as e:
        raise deny(403, e.rule_id, e.reason)
    return intent_card(db, intent, STUDENT_ID)


class BankVerifyBody(BaseModel):
    officer: str = Field(default="Sandbox bank officer", max_length=60)
    session_id: Optional[str] = None


@router.post("/intents/{intent_id}/bank-verify")
def bank_verify(intent_id: str, body: Optional[BankVerifyBody] = None, db: Session = Depends(get_db)):
    """Simulated bank-counter verification of the documented (above-quota) route."""
    body = body or BankVerifyBody()
    try:
        intent = payments.bank_verify(db, intent_id, body.officer)
    except ValueError as e:
        raise deny(409, "Q-002", str(e))
    card = intent_card(db, intent, STUDENT_ID)
    _post_to_chat(db, body.session_id, {"messages": [system_message(
        "Bank officer verified the documents (simulated). The payment can now be sent for approval.")],
        "cards": [checklist_card(intent), card]})
    return card


@router.get("/receipts")
def list_receipts(db: Session = Depends(get_db)):
    rows = db.exec(select(Transfer).order_by(Transfer.executed_at.desc())).all()
    return {"receipts": [receipt_card(t, db.get(PaymentIntent, t.intent_id)) for t in rows]}


@router.get("/receipts/{transfer_id}.pdf")
def receipt_pdf(transfer_id: str, db: Session = Depends(get_db)):
    t = db.get(Transfer, transfer_id)
    if t is None or not t.receipt_pdf_path:
        raise deny(404, "SYS-003", "Unknown receipt.")
    path = Path(t.receipt_pdf_path).resolve()
    if get_settings().data_dir.resolve() not in path.parents or not path.exists():
        raise deny(404, "SYS-003", "Receipt file missing.")
    return FileResponse(path, media_type="application/pdf", filename=f"bridge_receipt_{t.bank_reference}.pdf")

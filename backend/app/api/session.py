"""Session start, device enrolment, consent, persona switch, delete-my-data (PIPL)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import privacy
from ..agent.orchestrator import new_chat_session
from ..config import rule_param
from ..models import ChatSession, Consent, Person
from ..sandbox import clock
from ..security import approvals, audit
from ..seed import PAYER_ID, STUDENT_ID
from .deps import PERSONAS, deny, get_db, require_persona

router = APIRouter(tags=["session"])


class StartBody(BaseModel):
    persona: str = PAYER_ID


def _consented(db: Session, person_id: str) -> bool:
    return db.exec(select(Consent).where(Consent.person_id == person_id, Consent.revoked_at.is_(None))).first() is not None


@router.post("/session/start")
def start(request: Request, body: Optional[StartBody] = None, db: Session = Depends(get_db)):
    body = body or StartBody()
    cs = new_chat_session(db, body.persona)
    audit.append(db, actor="user", persona=body.persona, event="session_started", payload={"session_id": cs.id})
    persons = [{"id": p.id, "full_name": p.full_name, "name_zh": p.name_zh, "role": p.role,
                "relationship": p.relationship_to_student, "persona": p.id in PERSONAS, "deleted": p.deleted_at is not None}
               for p in db.exec(select(Person))]
    return {"session_id": cs.id, "persons": persons, "devices_to_enroll": list(PERSONAS),
            "model_label": request.app.state.model_label, "sandbox": True,
            "banner": "SANDBOX — fictional institutions, simulated accounts and FX rates",
            "consent": {pid: _consented(db, pid) for pid in PERSONAS}, "now": clock.now(db).isoformat()}


class EnrollBody(BaseModel):
    person_id: str
    label: str = Field(default="Browser device", max_length=60)


@router.post("/devices/enroll")
def enroll(body: EnrollBody, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    dev, secret = approvals.enroll_device(db, body.person_id, body.label)
    return {"device_id": dev.id, "device_secret": secret, "note": "Shown once. Stored only in this browser."}


class ConsentBody(BaseModel):
    person_id: str
    purposes: list[str] = Field(default_factory=lambda: list(rule_param("P-001", "purposes", [])))


@router.post("/consent")
def consent(body: ConsentBody, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    c = privacy.grant_consent(db, body.person_id, body.purposes)
    return {"person_id": body.person_id, "purposes": c.purposes, "granted_at": c.granted_at.isoformat()}


@router.get("/consent/{person_id}")
def consent_status(person_id: str, db: Session = Depends(get_db)):
    return {"person_id": person_id, "consented": _consented(db, person_id)}


@router.delete("/persons/{person_id}/data")
def delete_data(person_id: str, db: Session = Depends(get_db)):
    try:
        summary = privacy.delete_person_data(db, person_id)
    except ValueError as e:
        raise deny(404, "SYS-003", str(e))
    return {**summary, "kept": "Masked audit entries (evidence chain, no clear-text PII) and FX ledger rows (bank record)."}


class PersonaBody(BaseModel):
    session_id: str
    person_id: str


@router.post("/session/persona")
def switch_persona(body: PersonaBody, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    cs = db.get(ChatSession, body.session_id)
    if cs is not None:
        cs.active_persona = body.person_id
        db.add(cs)
    audit.append(db, actor="user", persona=body.person_id, event="persona_switched",
                 payload={"session_id": body.session_id, "to": body.person_id})
    return {"ok": True, "persona": body.person_id, "student_id": STUDENT_ID}

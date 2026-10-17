"""Shared API dependencies and helpers."""
from __future__ import annotations

from typing import Iterator

from fastapi import HTTPException, Request
from sqlmodel import Session

from ..models import Person
from ..security.policy import PolicyContext
from ..seed import PAYER_ID, STUDENT_ID

PERSONAS = (PAYER_ID, STUDENT_ID)


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine, expire_on_commit=False) as s:
        yield s


def deny(status: int, rule_id: str, reason: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"rule_id": rule_id, "reason": reason})


def require_persona(session: Session, person_id: str) -> Person:
    p = session.get(Person, person_id)
    if p is None or person_id not in PERSONAS:
        raise deny(404, "SYS-003", "Unknown persona.")
    if p.deleted_at is not None:
        raise deny(403, "P-003", "This person's data was deleted.")
    return p


def user_ctx(person_id: str | None = None) -> PolicyContext:
    return PolicyContext(payer_id=PAYER_ID, student_id=STUDENT_ID, actor="user", actor_person_id=person_id,
                         persona=person_id)

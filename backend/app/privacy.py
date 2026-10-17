"""PIPL controls: consent (P-001) and delete-my-data (P-003)."""
from __future__ import annotations

from sqlmodel import Session, select

from .config import rule_param
from .models import Consent, Device, Document, Person
from .sandbox import clock
from .security import audit


def grant_consent(session: Session, person_id: str, purposes: list[str] | None = None) -> Consent:
    allowed = set(rule_param("P-001", "purposes", []))
    purposes = [p for p in (purposes or sorted(allowed)) if p in allowed]
    c = Consent(person_id=person_id, purposes=purposes, granted_at=clock.now(session))
    session.add(c)
    audit.append(session, actor="user", persona=person_id, event="consent_granted", rule_id="P-001",
                 decision="allow", payload={"person_id": person_id, "purposes": purposes})
    return c


def delete_person_data(session: Session, person_id: str) -> dict:
    """Delete documents, consents and devices; anonymise the person record.

    Kept: masked audit entries (the evidence chain; no clear-text PII) and FX ledger rows
    (a bank must keep FX purchase records; they reference an id only).
    """
    person = session.get(Person, person_id)
    if person is None:
        raise ValueError("Unknown person.")
    docs = list(session.exec(select(Document).where(Document.uploaded_by == person_id)))
    consents = list(session.exec(select(Consent).where(Consent.person_id == person_id)))
    devices = list(session.exec(select(Device).where(Device.person_id == person_id)))
    for row in docs + consents + devices:
        session.delete(row)
    person.full_name = "[deleted]"
    person.name_zh = ""
    person.passport_name = ""
    person.city = ""
    person.deleted_at = clock.now(session)
    session.add(person)
    summary = {"person_id": person_id, "documents": len(docs), "consents": len(consents), "devices": len(devices)}
    audit.append(session, actor="user", persona=person_id, event="personal_data_deleted", rule_id="P-003",
                 decision="allow", reason="Personal data deleted; masked audit entries kept.", payload=summary)
    return summary

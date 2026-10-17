"""Verified institution registry (loaded from registry/institutions.yaml)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from ..config import registry_data
from ..models import Institution, PaymentChannel
from ..security.masking import mask_account


def normalise_account(value: str) -> str:
    return re.sub(r"[\s-]", "", value or "").upper()


def load_into_db(session: Session) -> None:
    for inst in registry_data()["institutions"]:
        session.merge(Institution(
            id=inst["id"], name=inst["name"], country=inst["country"],
            official_domains=inst.get("official_domains", []),
            official_contact_email=inst.get("official_contact_email", ""),
            reference_regex=inst.get("reference_regex"),
            fee_ranges=inst.get("fee_ranges", {}), fees=inst.get("fees", {}),
            currency=inst["currency"], deadlines=inst.get("deadlines", []),
        ))
        for ch in inst.get("channels", []):
            session.merge(PaymentChannel(
                id=ch["id"], type="institution", institution_id=inst["id"],
                beneficiary_name=ch["beneficiary_name"], bank_name=ch["bank_name"],
                account_full=ch["account_full"], account_masked=mask_account(ch["account_full"]),
                swift=ch["swift"], currency=ch["currency"], verified_source=ch["verified_source"],
                verified_at=datetime.fromisoformat(ch["verified_at"]),
            ))
    session.commit()


def institutions(session: Session) -> list[Institution]:
    return list(session.exec(select(Institution)))


def channels(session: Session) -> list[PaymentChannel]:
    return list(session.exec(select(PaymentChannel)))


def official_domains(session: Session) -> list[str]:
    return [d for i in institutions(session) for d in i.official_domains]


def channel_by_account(session: Session, account: str) -> Optional[PaymentChannel]:
    norm = normalise_account(account)
    for ch in channels(session):
        if normalise_account(ch.account_full) == norm:
            return ch
    return None


def institution_channel(session: Session, institution_id: str) -> Optional[PaymentChannel]:
    return session.exec(
        select(PaymentChannel).where(PaymentChannel.institution_id == institution_id, PaymentChannel.type == "institution")
    ).first()


def match_institution(session: Session, *, issuer_name: str = "", beneficiary_name: str = "",
                      sender_domain: str = "", reference: str = "") -> Optional[Institution]:
    """Identify which registered institution a document claims to come from."""
    texts = [t.lower() for t in (issuer_name, beneficiary_name) if t]
    for inst in institutions(session):
        if any(inst.name.lower() in t or t in inst.name.lower() for t in texts if len(t) > 3):
            return inst
        if sender_domain and any(sender_domain.lower() == d or sender_domain.lower().endswith("." + d) for d in inst.official_domains):
            return inst
        if reference and inst.reference_regex and re.fullmatch(inst.reference_regex, reference):
            return inst
    return None

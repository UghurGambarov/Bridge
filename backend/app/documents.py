"""Document ingestion (SPEC §9.1).

1. hash + consent (P-001)  2. deterministic detectors  3. quarantined extraction (visible text only)
4. the planner later receives only {extracted fields, findings} — never the raw text.
Raw uploads are not retained (P-004); hidden spans are kept so the UI can reveal them.
"""
from __future__ import annotations

import email
import hashlib
import secrets
from email import policy as email_policy
from typing import Callable, Optional

from sqlmodel import Session, select

from . import registry
from .agent.extractor import ExtractedDocument, regex_extract
from .models import Consent, Document
from .sandbox import clock
from .security import audit, domains, injection, pdf_forensics, request_guard, risk


class ConsentRequired(Exception):
    pass


def has_consent(session: Session, person_id: str, purpose: str = "document_processing") -> bool:
    for c in session.exec(select(Consent).where(Consent.person_id == person_id, Consent.revoked_at.is_(None))):
        if purpose in (c.purposes or []):
            return True
    return False


def _kind(filename: str, data: bytes) -> str:
    low = filename.lower()
    if low.endswith(".pdf") or data[:5] == b"%PDF-":
        return "pdf"
    if low.endswith(".eml"):
        return "email"
    return "text"


def _email_text(raw: str) -> str:
    msg = email.message_from_string(raw, policy=email_policy.default)
    body = msg.get_body(preferencelist=("plain",))
    content = body.get_content() if body else ""
    return f"From: {msg.get('From', '')}\nSubject: {msg.get('Subject', '')}\n\n{content}"


def analyse(session: Session, filename: str, data: bytes) -> tuple[str, dict, str]:
    """Run the deterministic detectors. Returns (kind, findings, visible_text)."""
    kind = _kind(filename, data)
    hidden_spans: list[dict] = []
    extra_text = ""
    if kind == "pdf":
        forensic = pdf_forensics.analyze_pdf(data)
        raw_text = forensic["visible_text"]
        hidden_spans = forensic["hidden_spans"]
        extra_text = forensic["rotated_text"]
    else:
        raw_text = data.decode("utf-8", errors="replace")
        if kind == "email":
            raw_text = _email_text(raw_text)
    visible = injection.strip_invisible(raw_text)
    everything = "\n".join([raw_text, extra_text] + [s["text"] for s in hidden_spans])
    scan = injection.scan(everything)
    official = registry.official_domains(session)
    findings = {
        "hidden_spans": hidden_spans,
        "injection_hits": scan["injection_hits"],
        "bank_change_hits": scan["bank_change_hits"],
        "invisible": scan["invisible"],
        "lookalike_domains": domains.scan_text(everything, official),
        "guard_hits": [h.as_dict() for h in request_guard.screen(everything)],
    }
    return kind, findings, visible


def ingest(session: Session, *, uploaded_by: str, filename: str, data: bytes,
           extractor: Optional[Callable[[str], ExtractedDocument]] = None, persona: Optional[str] = None) -> Document:
    if not has_consent(session, uploaded_by, "document_processing"):
        audit.append(session, actor="policy", persona=persona, event="document_rejected", rule_id="P-001",
                     decision="deny", reason="No consent for document processing.", payload={"filename": filename})
        raise ConsentRequired("Consent for document processing is required (P-001).")
    sha = hashlib.sha256(data).hexdigest()
    kind, findings, visible = analyse(session, filename, data)
    extracted = regex_extract(visible)
    if extractor is not None:
        try:
            extracted = extractor(visible)
        except Exception:  # LLM failure or schema violation -> deterministic fallback
            extracted = regex_extract(visible)
    payee_check = risk.assess_document(session, extracted, findings, clock.now(session), text=visible)
    doc = Document(
        id="doc_" + secrets.token_hex(5), uploaded_by=uploaded_by, kind=kind, filename=filename[:120], sha256=sha,
        extracted_json=extracted.model_dump(mode="json"), findings_json=findings, payee_check_json=payee_check,
        raw_retained=False, created_at=clock.now(session),
    )
    session.add(doc)
    audit.append(
        session, actor="system", persona=persona, event="document_ingested",
        rule_id=payee_check.get("forbidden_rule"), decision=payee_check["verdict"],
        payload={"doc_id": doc.id, "sha256": sha, "kind": kind, "verdict": payee_check["verdict"],
                 "score": payee_check["score"], "signals": [s["code"] for s in payee_check["signals"]],
                 "hidden_spans": len(findings["hidden_spans"]), "guard_hits": [h["rule_id"] for h in findings["guard_hits"]]},
    )
    return doc

"""Document upload: hash, consent, deterministic detectors, quarantined extraction."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session

from .. import documents
from ..agent.extractor import make_extractor
from ..models import Document
from .deps import deny, get_db, require_persona

router = APIRouter(tags=["documents"])
MAX_BYTES = 5 * 1024 * 1024
ALLOWED = (".pdf", ".txt", ".eml")


def doc_summary(doc: Document) -> dict:
    pc = doc.payee_check_json or {}
    f = doc.findings_json or {}
    return {
        "doc_id": doc.id, "filename": doc.filename, "kind": doc.kind, "sha256": doc.sha256,
        "verdict": pc.get("verdict"), "forbidden_rule": pc.get("forbidden_rule"), "score": pc.get("score"),
        "level": pc.get("level"), "signals": [s["code"] for s in pc.get("signals", [])],
        "findings": {"hidden_spans": f.get("hidden_spans", []), "injection_hits": len(f.get("injection_hits", [])),
                     "bank_change_hits": len(f.get("bank_change_hits", [])), "invisible": len(f.get("invisible", [])),
                     "lookalike_domains": f.get("lookalike_domains", []),
                     "guard_rules": sorted({h["rule_id"] for h in f.get("guard_hits", [])})},
        "raw_retained": doc.raw_retained,
    }


@router.post("/documents")
async def upload(request: Request, file: UploadFile = File(...), person_id: str = Form(...),
                 db: Session = Depends(get_db)):
    require_persona(db, person_id)
    if not request.app.state.limiter.check(f"upload:{person_id}"):
        raise deny(429, "SYS-002", "Too many uploads; wait a moment.")
    name = file.filename or "upload"
    if not name.lower().endswith(ALLOWED):
        raise deny(415, "SYS-003", "Only PDF, TXT and EML files are accepted.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise deny(413, "SYS-003", "File larger than 5 MB.")
    try:
        doc = documents.ingest(db, uploaded_by=person_id, filename=name, data=data,
                               extractor=make_extractor(request.app.state.llm), persona=person_id)
    except documents.ConsentRequired as e:
        raise deny(403, "P-001", str(e))
    return doc_summary(doc)


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise deny(404, "SYS-003", "Unknown document.")
    return {**doc_summary(doc), "payee_check": doc.payee_check_json, "summary_zh": doc.summary_zh}

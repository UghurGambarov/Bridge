"""Audit log: read, verify the hash chain, tamper simulation on a copy, JSONL export."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlmodel import Session

from ..security import audit
from .deps import get_db

router = APIRouter(tags=["audit"])


@router.get("/audit")
def read_audit(after_seq: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db)):
    rows = audit.all_rows(db, after_seq=after_seq)[:limit]
    return {"entries": rows, "head_seq": audit.head_seq(db)}


@router.get("/audit/verify")
def verify(db: Session = Depends(get_db)):
    return audit.verify(db)


class TamperBody(BaseModel):
    seq: Optional[int] = None


@router.post("/audit/tamper-simulation")
def tamper(body: Optional[TamperBody] = None, db: Session = Depends(get_db)):
    return audit.tamper_simulation(db, (body or TamperBody()).seq)


@router.get("/audit/export", response_class=PlainTextResponse)
def export(db: Session = Depends(get_db)):
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in audit.all_rows(db)]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=audit_log.jsonl"})

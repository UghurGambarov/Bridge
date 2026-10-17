"""Tamper-evident audit log (SPEC §9.6).

hash = sha256(prev_hash + canonical_json(entry without hash)). Anyone can recompute the chain.
Payloads are masked before they are written (P-002), so the log can be kept after a
delete-my-data request without holding clear-text PII.
"""
from __future__ import annotations

import threading
from typing import Any, Iterable, Optional

from sqlalchemy import func
from sqlmodel import Session, create_engine, select

from ..models import AuditEntry
from ..sandbox import clock
from .digest import canonical_json, sha256_hex
from .masking import mask_payload

GENESIS_HASH = "0" * 64
_lock = threading.Lock()


def _entry_body(e: dict) -> dict:
    return {
        "seq": e["seq"],
        "ts": e["ts"],
        "actor": e["actor"],
        "persona": e.get("persona"),
        "event": e["event"],
        "rule_id": e.get("rule_id"),
        "decision": e.get("decision"),
        "reason": e.get("reason", ""),
        "payload_masked": e.get("payload_masked", {}),
        "prev_hash": e["prev_hash"],
    }


def compute_hash(e: dict) -> str:
    return sha256_hex(e["prev_hash"] + canonical_json(_entry_body(e)))


def to_dict(entry: AuditEntry) -> dict:
    return {
        "seq": entry.seq, "ts": entry.ts, "actor": entry.actor, "persona": entry.persona,
        "event": entry.event, "rule_id": entry.rule_id, "decision": entry.decision,
        "reason": entry.reason, "payload_masked": entry.payload_masked,
        "prev_hash": entry.prev_hash, "hash": entry.hash,
    }


def append(
    session: Session,
    *,
    actor: str,
    event: str,
    reason: str = "",
    persona: Optional[str] = None,
    rule_id: Optional[str] = None,
    decision: Optional[str] = None,
    payload: Optional[dict] = None,
) -> AuditEntry:
    """Append one entry and commit (the commit also persists the caller's pending changes)."""
    with _lock:
        last = session.exec(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1)).first()
        body = {
            "seq": (last.seq + 1) if last else 1,
            "ts": clock.now(session).isoformat(),
            "actor": actor,
            "persona": persona,
            "event": event,
            "rule_id": rule_id,
            "decision": decision,
            "reason": mask_payload(reason),
            # JSON round-trip so the stored payload hashes identically when re-read.
            "payload_masked": _json_roundtrip(mask_payload(payload or {})),
            "prev_hash": last.hash if last else GENESIS_HASH,
        }
        entry = AuditEntry(**body, hash=compute_hash(body))
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry


def _json_roundtrip(obj: Any) -> Any:
    import json

    return json.loads(canonical_json(obj))


def verify_rows(rows: Iterable[dict]) -> dict:
    prev = GENESIS_HASH
    count = 0
    expected_seq = 1
    for e in rows:
        count += 1
        if e["seq"] != expected_seq or e["prev_hash"] != prev or compute_hash(e) != e["hash"]:
            return {"valid": False, "broken_at_seq": e["seq"], "entries": count, "head_hash": None}
        prev = e["hash"]
        expected_seq += 1
    return {"valid": True, "broken_at_seq": None, "entries": count, "head_hash": prev if count else GENESIS_HASH}


def all_rows(session: Session, after_seq: int = 0) -> list[dict]:
    stmt = select(AuditEntry).where(AuditEntry.seq > after_seq).order_by(AuditEntry.seq)
    return [to_dict(e) for e in session.exec(stmt)]


def verify(session: Session) -> dict:
    return verify_rows(all_rows(session))


def head_seq(session: Session) -> int:
    return session.exec(select(func.max(AuditEntry.seq))).one() or 0


def tamper_simulation(session: Session, seq: Optional[int] = None) -> dict:
    """Copy the log into a throw-away in-memory DB, alter one entry there, verify the copy.

    The real log is never modified.
    """
    rows = all_rows(session)
    if not rows:
        return {"original_valid": True, "tampered_seq": None, "copy_valid": True, "broken_at_seq": None}
    target = seq if seq is not None else rows[len(rows) // 2]["seq"]
    temp = create_engine("sqlite://")
    AuditEntry.__table__.create(temp)
    with Session(temp) as copy:
        for r in rows:
            copy.add(AuditEntry(**r))
        copy.commit()
        victim = copy.get(AuditEntry, target)
        victim.reason = (victim.reason or "") + " [edited]"
        victim.payload_masked = {**(victim.payload_masked or {}), "tampered": True}
        copy.add(victim)
        copy.commit()
        copied = [to_dict(e) for e in copy.exec(select(AuditEntry).order_by(AuditEntry.seq))]
    temp.dispose()
    result = verify_rows(copied)
    return {
        "original_valid": verify_rows(rows)["valid"],
        "tampered_seq": target,
        "copy_valid": result["valid"],
        "broken_at_seq": result["broken_at_seq"],
        "note": "Tampering was simulated on a temporary copy; the real log is unchanged.",
    }

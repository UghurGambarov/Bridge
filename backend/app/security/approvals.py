"""Human approvals bound to the transaction digest (SPEC §9.5, rules T3-001..T3-004).

Flow: the server issues a nonce per (intent, approver); the approver's device computes
mac = HMAC-SHA256(key, digest + ":" + nonce) with key = SHA-256(device_secret); the server
verifies it. Nonces are single-use and expire. The agent has NO approval tool: these
functions are reachable only from the approver's own API calls.

Production note: a real deployment would use WebAuthn / passkeys (asymmetric keys on the
device) instead of a shared HMAC key.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from ..config import rule_param
from ..models import Approval, Device, PaymentIntent, Person
from ..sandbox import clock
from . import audit
from .digest import compute_digest, fingerprint

APPROVABLE_STATUSES = ("pending_approval", "held")


class ApprovalError(Exception):
    def __init__(self, rule_id: str, reason: str):
        super().__init__(reason)
        self.rule_id, self.reason = rule_id, reason


# ------------------------------------------------------------------ devices
def device_key(device_secret: str) -> bytes:
    return hashlib.sha256(device_secret.encode("utf-8")).digest()


def enroll_device(session: Session, person_id: str, label: str) -> tuple[Device, str]:
    """Returns (device, device_secret). The secret is shown ONCE and only its hash is stored."""
    if session.get(Person, person_id) is None:
        raise ApprovalError("SYS-003", "Unknown person.")
    secret = secrets.token_urlsafe(32)
    dev = Device(id="dev_" + secrets.token_hex(5), person_id=person_id, label=label,
                 secret_hash=device_key(secret).hex(), enrolled_at=clock.now(session))
    session.add(dev)
    audit.append(session, actor="system", persona=person_id, event="device_enrolled",
                 payload={"device_id": dev.id, "person_id": person_id, "label": label})
    return dev, secret


def compute_mac(device_secret: str, digest: str, nonce: str) -> str:
    """What the persona's browser computes with Web Crypto."""
    return hmac.new(device_key(device_secret), f"{digest}:{nonce}".encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ approvers
def required_roles() -> list[str]:
    return list(rule_param("T3-001", "required_approvers", ["payer", "student"]))


def required_approvers(intent: PaymentIntent, student_id: str) -> list[str]:
    ids = [intent.payer_id if r == "payer" else student_id if r == "student" else r for r in required_roles()]
    return list(dict.fromkeys(ids))


def ttl() -> timedelta:
    return timedelta(minutes=int(rule_param("T3-003", "ttl_minutes", 15)))


# ------------------------------------------------------------------ challenge / approve / status
def issue_challenge(session: Session, intent_id: str, person_id: str, device_id: str, student_id: str) -> dict:
    intent = session.get(PaymentIntent, intent_id)
    if intent is None:
        raise ApprovalError("SYS-003", "Unknown intent.")
    if intent.status not in APPROVABLE_STATUSES:
        raise ApprovalError("SYS-003", f"Intent is '{intent.status}', not awaiting approval.")
    if person_id not in required_approvers(intent, student_id):
        raise ApprovalError("T3-001", "This person is not a required approver.")
    dev = session.get(Device, device_id)
    if dev is None or dev.person_id != person_id or dev.revoked_at is not None:
        raise ApprovalError("T3-004", "Device is not enrolled for this person.")
    digest = compute_digest(intent)
    if digest != intent.digest:
        raise ApprovalError("T3-002", "Intent changed after creation: digest mismatch.")
    now = clock.now(session)
    a = Approval(intent_id=intent.id, person_id=person_id, device_id=device_id, digest=digest,
                 nonce=secrets.token_hex(16), issued_at=now, expires_at=now + ttl())
    session.add(a)
    audit.append(session, actor="approver", persona=person_id, event="approval_challenge_issued",
                 payload={"intent_id": intent.id, "device_id": device_id, "fingerprint": intent.fingerprint})
    return {"nonce": a.nonce, "digest": digest, "fingerprint": fingerprint(digest),
            "expires_at": a.expires_at.isoformat(), "intent_id": intent.id}


def submit_approval(session: Session, intent_id: str, person_id: str, device_id: str, nonce: str, mac: str,
                    student_id: str) -> dict:
    try:
        result = _verify_and_record(session, intent_id, person_id, device_id, nonce, mac, student_id)
    except ApprovalError as e:
        audit.append(session, actor="approver", persona=person_id, event="approval_denied", rule_id=e.rule_id,
                     decision="deny", reason=e.reason, payload={"intent_id": intent_id, "device_id": device_id})
        raise
    return result


def _verify_and_record(session: Session, intent_id: str, person_id: str, device_id: str, nonce: str, mac: str,
                       student_id: str) -> dict:
    a = session.exec(select(Approval).where(Approval.nonce == nonce)).first()
    if a is None or a.intent_id != intent_id:
        raise ApprovalError("T3-003", "Nonce not issued for this intent (replay on another intent is refused).")
    if a.used_at is not None:
        raise ApprovalError("T3-003", "Nonce already used: approvals are single-use.")
    now = clock.now(session)
    if now > a.expires_at:
        raise ApprovalError("T3-003", "Approval challenge expired.")
    if a.person_id != person_id or a.device_id != device_id:
        raise ApprovalError("T3-004", "Challenge was issued to a different person or device.")
    intent = session.get(PaymentIntent, intent_id)
    if intent is None or intent.status not in APPROVABLE_STATUSES:
        raise ApprovalError("SYS-003", "Intent is not awaiting approval.")
    current = compute_digest(intent)
    if current != a.digest or current != intent.digest:
        raise ApprovalError("T3-002", "The intent changed after the challenge: digest mismatch.")
    dev = session.get(Device, device_id)
    if dev is None or dev.person_id != person_id or dev.revoked_at is not None:
        raise ApprovalError("T3-004", "Device is not enrolled for this person.")
    expected = hmac.new(bytes.fromhex(dev.secret_hash), f"{a.digest}:{a.nonce}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, (mac or "").lower()):
        raise ApprovalError("T3-002", "Signature (MAC) does not match the digest.")
    others = session.exec(select(Approval).where(Approval.intent_id == intent_id, Approval.used_at.is_not(None))).all()
    for o in others:
        if o.device_id == device_id and o.person_id != person_id:
            raise ApprovalError("T3-004", "The same device already approved for another person.")
        if o.person_id == person_id and o.digest == current:
            raise ApprovalError("T3-004", "This person has already approved this intent.")
    a.used_at = now
    a.mac = mac.lower()
    session.add(a)
    audit.append(session, actor="approver", persona=person_id, event="approval_granted", rule_id="T3-001",
                 decision="allow", payload={"intent_id": intent_id, "device_id": device_id, "fingerprint": intent.fingerprint})
    status = approval_status(session, intent, student_id)
    if status["complete"]:
        intent.status = "approved"
        intent.updated_at = now
        session.add(intent)
        audit.append(session, actor="system", event="approvals_complete", rule_id="T3-001", decision="allow",
                     payload={"intent_id": intent_id, "fingerprint": intent.fingerprint})
    return status


def approval_status(session: Session, intent: PaymentIntent, student_id: str) -> dict:
    """The `approval_status` card."""
    required = required_approvers(intent, student_id)
    digest = compute_digest(intent)
    used = session.exec(select(Approval).where(Approval.intent_id == intent.id, Approval.used_at.is_not(None))).all()
    approved = {}
    for a in used:
        if a.digest == digest:
            approved[a.person_id] = a.used_at.isoformat()
    waiting = [p for p in required if p not in approved]
    return {
        "type": "approval_status", "intent_id": intent.id, "fingerprint": intent.fingerprint,
        "required": required, "approved": approved, "waiting_for": waiting, "complete": not waiting,
    }


def reject(session: Session, intent_id: str, person_id: str, reason: str, student_id: str) -> PaymentIntent:
    intent = session.get(PaymentIntent, intent_id)
    if intent is None:
        raise ApprovalError("SYS-003", "Unknown intent.")
    if person_id not in required_approvers(intent, student_id):
        raise ApprovalError("T3-001", "Only a required approver can reject.")
    if intent.status in ("executed", "blocked", "rejected"):
        raise ApprovalError("SYS-003", f"Intent is '{intent.status}'.")
    intent.status = "rejected"
    intent.status_reason = reason[:200]
    intent.updated_at = clock.now(session)
    session.add(intent)
    audit.append(session, actor="approver", persona=person_id, event="approval_rejected", decision="deny",
                 reason=reason[:200], payload={"intent_id": intent_id})
    return intent


def approvals_for(session: Session, intent_id: str) -> list[Approval]:
    return list(session.exec(select(Approval).where(Approval.intent_id == intent_id, Approval.used_at.is_not(None))))


def latest_used(session: Session, intent_id: str, person_id: str) -> Optional[Approval]:
    rows = [a for a in approvals_for(session, intent_id) if a.person_id == person_id]
    return max(rows, key=lambda a: a.used_at) if rows else None

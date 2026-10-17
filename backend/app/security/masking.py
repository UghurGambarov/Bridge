"""PII masking for logs, UI and exports (rule P-002)."""
from __future__ import annotations

import re
from typing import Any

# IBAN-like identifiers, long digit runs (cards / UnionPay, optionally with "TEST"), wallets, emails.
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}\b")
_CARD_RE = re.compile(r"\b\d{4}(?:[ -]?(?:TEST|\d{4})){2,4}\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{12,19}\b")
_WALLET_RE = re.compile(r"\b0x[a-fA-F0-9]{8,}\b")
_EMAIL_RE = re.compile(r"([\w.+-])([\w.+-]*)@([\w.-]+\.\w+)", re.UNICODE)
_PASSPORT_RE = re.compile(r"\b[EG]\d{8}\b")

_NAME_KEYS = {"full_name", "passport_name", "name_zh", "student_name", "owner_name", "person_name"}
_ACCOUNT_KEYS = {"account", "account_full", "beneficiary_account", "iban", "wallet", "card_number"}
_EMAIL_KEYS = {"email", "sender_email", "official_contact_email", "to", "from"}
_INSTITUTION_WORDS = ("UNIVERSITY", "INSTITUTE", "COLLEGE", "SCHOOL", "LTD", "LIMITED", "PLC", "BANK", "AGENCY")


def mask_account(value: str) -> str:
    compact = re.sub(r"[\s-]", "", value)
    if len(compact) <= 8:
        return "*" * len(compact)
    return f"{compact[:4]}{'*' * (len(compact) - 8)}{compact[-4:]}"


def mask_email(value: str) -> str:
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(3)}", value)


def mask_name(value: str) -> str:
    parts = value.split()
    if not parts:
        return value
    if len(parts) == 1 and len(value) <= 4 and not value.isascii():
        return value[0] + "*" * (len(value) - 1)  # 张敏 -> 张*
    return " ".join(p[0] + "*" * max(1, len(p) - 1) for p in parts)


def mask_text(text: str) -> str:
    out = _IBAN_RE.sub(lambda m: mask_account(m.group(0)), text)
    out = _CARD_RE.sub(lambda m: mask_account(m.group(0)), out)
    out = _LONG_DIGITS_RE.sub(lambda m: mask_account(m.group(0)), out)
    out = _WALLET_RE.sub(lambda m: m.group(0)[:6] + "…", out)
    out = _PASSPORT_RE.sub(lambda m: m.group(0)[0] + "********", out)
    return mask_email(out)


def _is_institution_name(value: str) -> bool:
    upper = value.upper()
    return any(w in upper for w in _INSTITUTION_WORDS)


def mask_payload(obj: Any, key: str | None = None) -> Any:
    """Recursively mask a JSON-like payload."""
    if isinstance(obj, dict):
        return {k: mask_payload(v, k) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_payload(v, key) for v in obj]
    if isinstance(obj, str):
        k = (key or "").lower()
        if k in _ACCOUNT_KEYS:
            return mask_account(obj)
        if k in _NAME_KEYS:
            return mask_name(obj)
        if k == "beneficiary_name" and not _is_institution_name(obj):
            return mask_name(obj)
        if k in _EMAIL_KEYS:
            return mask_email(obj)
        return mask_text(obj)
    return obj

"""Canonical JSON, intent digest and fingerprint (SPEC §9.5, rule T3-002)."""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

DIGEST_FIELDS = ("intent_id", "payer_id", "payee_channel_id", "amount", "currency", "purpose", "reference", "route")


def _normalise(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if isinstance(obj, dict):
        return {str(k): _normalise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalise(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, amounts as strings with 2 decimals, UTF-8 kept."""
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def intent_digest_payload(intent: Any) -> dict:
    return {
        "intent_id": intent.id,
        "payer_id": intent.payer_id,
        "payee_channel_id": intent.payee_channel_id,
        "amount": Decimal(str(intent.amount)),
        "currency": intent.currency,
        "purpose": intent.purpose,
        "reference": intent.reference or "",
        "route": intent.route,
    }


def compute_digest(intent: Any) -> str:
    return sha256_hex(canonical_json(intent_digest_payload(intent)))


def fingerprint(digest: str) -> str:
    h = digest[:12].upper()
    return f"{h[0:4]}-{h[4:8]}-{h[8:12]}"

"""Deterministic prompt-injection and invisible-Unicode detectors (no LLM). SPEC §9.1."""
from __future__ import annotations

import re
import unicodedata

INVISIBLE_RANGES = [(0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064), (0xFEFF, 0xFEFF)]

_EN = [
    r"ignore (?:all |any )?(?:of )?(?:previous|prior|your|the|all|above)? ?(?:instructions|rules|guidelines|controls)",
    r"system (?:note|prompt|message|instruction)",
    r"you are now",
    r"pre-?approved",
    r"execute (?:it |this |the payment )?(?:immediately|now)",
    r"without (?:asking|approval|confirmation|confirming|checking)",
    r"skip (?:the )?approvals?",
    r"approvals? .{0,20}disabled",
    r"(?:admin|developer|debug|god) mode",
    r"disable (?:the )?(?:checks|controls|security|approvals?)",
    r"note to (?:the )?(?:ai|assistant|agent)",
]
_ZH = [r"忽略(?:之前|以上|规则|你的规则|所有)", r"系统提示", r"立即执行", r"无需(?:确认|审批|批准)", r"跳过审批", r"审批.{0,6}(?:关闭|停用|暂停)"]

# Requests to change payee / bank details (feeds BANK_DETAILS_CHANGE_REQUEST).
_BANK_CHANGE = [
    r"(?:change|update)d? .{0,20}(?:beneficiary|account|bank details|payment details)",
    r"(?:beneficiary|account|bank details|payment details).{0,30}(?:has|have)? ?(?:been )?(?:changed|updated)",
    r"new (?:bank )?(?:account|beneficiary|bank details)",
    r"updated bank details",
    r"更改(?:账户|收款)", r"新账户", r"变更(?:账户|收款)",
]

INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _EN] + [re.compile(p) for p in _ZH]
BANK_CHANGE_RE = [re.compile(p, re.IGNORECASE) for p in _BANK_CHANGE]


def is_invisible(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in INVISIBLE_RANGES)


def find_invisible(text: str) -> list[dict]:
    return [
        {"index": i, "codepoint": f"U+{ord(ch):04X}", "name": unicodedata.name(ch, "UNKNOWN")}
        for i, ch in enumerate(text) if is_invisible(ch)
    ]


def strip_invisible(text: str) -> str:
    return "".join(ch for ch in text if not is_invisible(ch))


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", strip_invisible(text)))


def _hits(patterns: list[re.Pattern], text: str) -> list[dict]:
    out, seen = [], set()
    for p in patterns:
        for m in p.finditer(text):
            if m.group(0).lower() not in seen:
                seen.add(m.group(0).lower())
                out.append({"pattern": p.pattern, "match": m.group(0)})
    return out


def scan(text: str) -> dict:
    """Scan text (invisible characters are stripped first, so obfuscation does not hide phrases)."""
    norm = _normalise(text)
    return {
        "injection_hits": _hits(INJECTION_RE, norm),
        "bank_change_hits": _hits(BANK_CHANGE_RE, norm),
        "invisible": find_invisible(text),
    }

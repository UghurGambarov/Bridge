"""Payee verification and risk score (SPEC §9.2). Fully deterministic; weights live in config."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session

from .. import registry
from ..config import app_config, risk_weights
from ..models import Institution, PaymentChannel

EXPLANATIONS = {
    "PAYEE_NOT_IN_REGISTRY": "The payee is not in Bridge's verified registry.",
    "ACCOUNT_MISMATCH": "The account number differs from the institution's registered account.",
    "NAME_MISMATCH": "The beneficiary name differs from the registered name.",
    "PERSONAL_ACCOUNT_FOR_FEES": "Fees are requested to a personal account (a person's name, 'personal', or a UnionPay card number).",
    "REFERENCE_FORMAT_MISMATCH": "The payment reference does not match the institution's format.",
    "LOOKALIKE_DOMAIN": "A sender or link domain imitates an official domain.",
    "BANK_DETAILS_CHANGE_REQUEST": "The content asks to change the payee's bank details.",
    "HIDDEN_TEXT": "The PDF contains text a human cannot see (white, tiny or off-page).",
    "INJECTION_PHRASE": "The content contains instructions aimed at the AI (prompt injection).",
    "INVISIBLE_UNICODE": "The text hides characters using invisible Unicode.",
    "DISCOUNT_OFFER": "A 'discount' on tuition: universities do not discount fees through third parties.",
    "URGENCY": "Pressure to pay quickly.",
    "AGENCY_INTERMEDIARY": "An agency offers to pay the fees 'on your behalf' (代缴).",
    "CRYPTO_MENTION": "Payment via crypto or stablecoins.",
    "AMOUNT_OUTSIDE_FEE_RANGE": "The amount is outside the institution's published fee range.",
    "DEADLINE_MISMATCH": "The due date does not match the institution's published deadlines.",
}

# Signals that are forbidden outright, whatever the score.
FORBIDDEN_SIGNALS = {"CRYPTO_MENTION": "T4-005", "PERSONAL_ACCOUNT_FOR_FEES": "T4-001"}

_CJK_NAME = re.compile(r"^[一-鿿]{2,4}$")
_PERSON_TITLE = re.compile(r"\b(?:Mr|Ms|Mrs|Miss|Manager)\b\.?|经理|先生|女士|老师", re.I)
_PERSONAL_WORD = re.compile(r"\bpersonal\b|个人", re.I)


def thresholds() -> tuple[int, int]:
    t = app_config()["risk"]["thresholds"]
    return int(t["medium"]), int(t["high"])


def level_for(score: int) -> str:
    medium, high = thresholds()
    return "HIGH" if score >= high else "MEDIUM" if score >= medium else "LOW"


def score_signals(codes: list[str]) -> tuple[int, str]:
    weights = risk_weights()
    score = min(100, sum(int(weights.get(c, 0)) for c in dict.fromkeys(codes)))
    return score, level_for(score)


def signal(code: str, detail: str = "") -> dict:
    return {"code": code, "weight": int(risk_weights().get(code, 0)), "explanation": EXPLANATIONS.get(code, code),
            "detail": detail}


def _norm_name(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def looks_personal(beneficiary_name: str, account: str, text: str) -> bool:
    name = (beneficiary_name or "").strip()
    first = re.split(r"[\s(（]", name)[0] if name else ""
    compact = re.sub(r"[\s-]", "", account or "").upper().replace("TEST", "")
    return bool(
        (first and _CJK_NAME.match(first))
        or _PERSON_TITLE.search(name)
        or _PERSONAL_WORD.search(text or "")
        or re.fullmatch(r"62\d{14,17}", compact)
    )


def guess_purpose(text: str) -> str:
    low = (text or "").lower()
    if "accommodation" in low or "住宿" in low:
        return "accommodation"
    if "deposit" in low or "押金" in low:
        return "deposit"
    return "tuition"


def amount_in_range(inst: Institution, purpose: str, amount: Decimal, currency: str) -> tuple[bool, str]:
    rng = (inst.fee_ranges or {}).get(purpose)
    if currency and currency.upper() != inst.currency:
        return False, f"Currency {currency} differs from the institution's currency {inst.currency}."
    if not rng:
        return True, ""
    lo, hi = Decimal(str(rng[0])), Decimal(str(rng[1]))
    if lo <= amount <= hi:
        return True, ""
    return False, f"{currency} {amount:,.2f} is outside the {purpose} range {inst.currency} {lo:,.0f}–{hi:,.0f}."


def deadline_check(inst: Institution, due: str) -> tuple[bool, str]:
    if not inst.deadlines:
        return True, ""
    tol = int(app_config()["risk"]["deadline_tolerance_days"])
    d = date.fromisoformat(due)
    gaps = [abs((date.fromisoformat(x) - d).days) for x in inst.deadlines]
    if min(gaps) <= tol:
        return True, ""
    return False, f"Due date {due} is not near any published deadline ({', '.join(inst.deadlines)})."


def forbidden_rule_for(codes: set[str], level: str) -> Optional[str]:
    for code, rid in FORBIDDEN_SIGNALS.items():
        if code in codes:
            return rid
    if "BANK_DETAILS_CHANGE_REQUEST" in codes:
        return "T4-006"
    if codes & {"PAYEE_NOT_IN_REGISTRY", "ACCOUNT_MISMATCH"}:
        return "T4-002"
    if "INJECTION_PHRASE" in codes:
        return "T4-008"
    if level == "HIGH":
        return "T4-002"
    return None


def assess_document(session: Session, extracted: Any, findings: dict, today: datetime, text: str = "") -> dict:
    """Compare extracted fields with the registry and build the `payee_check` card."""
    ex = extracted if isinstance(extracted, dict) else extracted.model_dump(mode="json")
    sigs: list[dict] = []
    notices: list[str] = []
    account = ex.get("beneficiary_account") or ""
    bname = ex.get("beneficiary_name") or ""

    inst = registry.match_institution(
        session, issuer_name=ex.get("issuer_name") or "", beneficiary_name=bname,
        sender_domain=ex.get("sender_domain") or "", reference=ex.get("reference") or "",
    )
    matched: Optional[PaymentChannel] = None
    if account:
        by_acct = registry.channel_by_account(session, account)
        if by_acct and by_acct.type == "institution" and (inst is None or by_acct.institution_id == inst.id):
            matched = by_acct
            inst = inst or session.get(Institution, by_acct.institution_id)
            if bname and _norm_name(bname) != _norm_name(by_acct.beneficiary_name):
                sigs.append(signal("NAME_MISMATCH", f"Document says '{bname}', registry says '{by_acct.beneficiary_name}'."))
        elif inst is not None:
            reg = registry.institution_channel(session, inst.id)
            sigs.append(signal("ACCOUNT_MISMATCH",
                               f"Document account differs from the registered account {reg.account_masked if reg else ''} of {inst.name}."))
        else:
            sigs.append(signal("PAYEE_NOT_IN_REGISTRY", f"Beneficiary '{bname or 'unknown'}' is not a registered institution."))
    elif inst is not None and ex.get("doc_type") == "invoice":
        matched = registry.institution_channel(session, inst.id)
    elif bname and inst is None:
        sigs.append(signal("PAYEE_NOT_IN_REGISTRY", f"Beneficiary '{bname}' is not a registered institution."))

    if (account or bname) and matched is None and looks_personal(bname, account, text):
        sigs.append(signal("PERSONAL_ACCOUNT_FOR_FEES", f"Beneficiary '{bname or account}' looks like a personal account."))

    ref = ex.get("reference")
    if inst is not None and ref and inst.reference_regex and not re.fullmatch(inst.reference_regex, ref):
        sigs.append(signal("REFERENCE_FORMAT_MISMATCH", f"Reference '{ref}' does not match {inst.reference_regex}."))

    if findings.get("lookalike_domains"):
        doms = ", ".join(d["domain"] for d in findings["lookalike_domains"])
        sigs.append(signal("LOOKALIKE_DOMAIN", f"Suspicious domain(s): {doms}."))
    if findings.get("bank_change_hits"):
        sigs.append(signal("BANK_DETAILS_CHANGE_REQUEST", f"'{findings['bank_change_hits'][0]['match']}'"))
    if findings.get("hidden_spans"):
        sigs.append(signal("HIDDEN_TEXT", f"{len(findings['hidden_spans'])} hidden span(s): "
                                          + "; ".join(s["description"] for s in findings["hidden_spans"][:3])))
    if findings.get("injection_hits"):
        sigs.append(signal("INJECTION_PHRASE", f"'{findings['injection_hits'][0]['match']}'"))
    if findings.get("invisible"):
        sigs.append(signal("INVISIBLE_UNICODE", f"{len(findings['invisible'])} invisible character(s)."))
    if ex.get("mentions_discount"):
        sigs.append(signal("DISCOUNT_OFFER"))
    if ex.get("mentions_urgency"):
        sigs.append(signal("URGENCY"))
    if ex.get("mentions_agency_payment"):
        sigs.append(signal("AGENCY_INTERMEDIARY"))
    if ex.get("mentions_crypto"):
        sigs.append(signal("CRYPTO_MENTION"))

    amount = ex.get("amount")
    if inst is not None and amount is not None:
        ok, detail = amount_in_range(inst, guess_purpose(text), Decimal(str(amount)), ex.get("currency") or inst.currency)
        if not ok:
            sigs.append(signal("AMOUNT_OUTSIDE_FEE_RANGE", detail))
    due = ex.get("due_date")
    if due:
        days = (date.fromisoformat(due) - today.date()).days
        if days < 0:
            notices.append(f"The due date {due} has passed.")
        elif days <= int(app_config()["risk"]["deadline_soon_days"]):
            notices.append(f"Deadline soon: due in {days} day(s) ({due}).")
        if inst is not None:
            ok, detail = deadline_check(inst, due)
            if not ok:
                sigs.append(signal("DEADLINE_MISMATCH", detail))

    # de-duplicate by code, keep first detail
    seen: dict[str, dict] = {}
    for s in sigs:
        seen.setdefault(s["code"], s)
    sigs = list(seen.values())
    codes = {s["code"] for s in sigs}
    score, level = score_signals(list(codes))
    forbidden = forbidden_rule_for(codes, level)
    has_payment_details = bool(account or bname or amount is not None)
    if forbidden or level == "HIGH":
        verdict = "blocked"
    elif level == "MEDIUM":
        verdict = "warning"
    elif matched is not None:
        verdict = "verified"
    elif not has_payment_details:
        verdict = "no_payee"
    else:
        verdict = "unverified"
    return {
        "type": "payee_check",
        "verdict": verdict,
        "institution_id": inst.id if inst else None,
        "institution_name": inst.name if inst else None,
        "official_contact_email": inst.official_contact_email if inst else None,
        "matched_channel_id": matched.id if matched else None,
        "matched_beneficiary": matched.beneficiary_name if matched else None,
        "matched_account_masked": matched.account_masked if matched else None,
        "score": score,
        "level": level,
        "signals": sigs,
        "forbidden_rule": forbidden,
        "hidden_spans": findings.get("hidden_spans", []),
        "notices": notices,
        "purpose_guess": guess_purpose(text),
        "mentioned_institution_id": inst.id if inst else _mentioned_institution(session, text),
    }


def _mentioned_institution(session: Session, text: str) -> Optional[str]:
    """A registered institution named anywhere in the text (used only to address a verification email)."""
    low = (text or "").lower()
    for i in registry.institutions(session):
        if i.name.lower() in low:
            return i.id
    return None

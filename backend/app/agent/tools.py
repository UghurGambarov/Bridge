"""Agent tools. Every call goes through policy.authorize() (directly, or inside payments.*).

Each tool returns a ToolOutcome:
- `result`: what the planner model sees — structured, sanitized, no raw document text,
  no hidden-span text, account numbers masked;
- `cards`: what the UI renders — built from code, so every number comes from code.
There is deliberately NO approval tool.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from sqlmodel import Session, select

from .. import payments
from ..config import rule
from ..models import AllowanceSchedule, Document, Institution, PaymentChannel, PaymentIntent, Person, Transfer
from ..quota import ledger, planner
from ..sandbox import bank, fx
from ..security import approvals, policy
from ..security.masking import mask_account
from ..security.policy import Decision, PolicyContext
from ..security.request_guard import refusal_card
from ..seed import STUDENT_CHANNEL_ID
from . import summary_zh

AI_LABEL = "AI-generated · AI生成"

DESCRIPTIONS = {
    "get_family_overview": "Family, payer quota, sandbox balance, the student's verified account channel and registered institutions.",
    "read_document": "Schema-validated fields and detector findings of an uploaded document (never its raw text).",
    "summarize_in_chinese": "Deterministic Chinese summary card of a document for the mother (numbers from code).",
    "verify_payee": "Compare a document with the verified registry and score the risk; returns the matched payee_channel_id.",
    "check_quota": "The payer's personal annual FX quota (USD 50,000 per calendar year): used and remaining.",
    "get_fx_quote": "Simulated FX quote: CNY debit, USD equivalent (for the quota) and fee.",
    "create_payment_intent": "Prepare a payment (draft). Payee must be a registry payee_channel_id. Never executes.",
    "request_approval": "Ask the required humans to approve an intent on their own devices.",
    "execute_payment": "Execute an intent in the sandbox bank. The policy engine checks approvals, digest, quota and limits.",
    "get_status": "Status, approvals and fingerprint of an intent.",
    "schedule_allowance": "Propose a monthly allowance schedule to the student's own verified account (inactive until the payer activates it).",
    "build_document_list": "Document checklist for an intent (ID only within quota; documented route above quota).",
    "draft_verification_email": "Draft (never send) an email to the institution's official registry contact to verify payment details.",
    "explain_decision": "Every rule check behind an intent, with sources (the Why panel).",
    "ask_clarifying_question": "Ask the user a clarifying question when the request is vague.",
}
_DESC_ARGS = {
    "doc_id": "Document ID (doc_...)", "person_id": "Person ID (p_...)", "currency": "ISO currency code",
    "amount": "Amount in the given currency", "purpose": "tuition | accommodation | deposit | allowance",
    "payer_id": "Must be the family's payer", "payee_channel_id": "Registry channel ID (ch_...), never an account number",
    "reference": "Payment reference from the invoice", "intent_id": "Intent ID (pi_...)",
    "student_id": "Student person ID", "day_of_month": "Day of month 1-28", "institution_id": "Registry institution ID (inst_...)",
    "question": "The clarifying question",
}
_JSON_TYPES = {"str": "string", "num": "number", "int": "integer"}


def tool_schemas() -> list[dict]:
    out = []
    for name, spec in policy.TOOLS.items():
        props = {a: {"type": _JSON_TYPES[k], "description": _DESC_ARGS.get(a, a)} for a, k in spec.args.items()}
        if "purpose" in props:
            props["purpose"]["enum"] = list(policy.PURPOSES)
        out.append({"name": name, "description": DESCRIPTIONS[name], "input_schema": {
            "type": "object", "properties": props, "required": list(spec.required), "additionalProperties": False}})
    return out


@dataclass
class TurnState:
    doc_ids: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)


@dataclass
class ToolOutcome:
    result: dict
    cards: list[dict] = field(default_factory=list)
    decision: Optional[Decision] = None


# ------------------------------------------------------------------ cards
def _person_name(session: Session, pid: str) -> str:
    p = session.get(Person, pid)
    return p.full_name if p else pid


def intent_view(intent: PaymentIntent) -> dict:
    """What the model sees about an intent."""
    return {"intent_id": intent.id, "purpose": intent.purpose, "status": intent.status, "tier": intent.tier,
            "route": intent.route, "fingerprint": intent.fingerprint, "amount": f"{intent.amount:.2f}",
            "currency": intent.currency, "usd_equivalent": f"{intent.usd_equivalent:.2f}",
            "status_reason": intent.status_reason[:200]}


def intent_card(session: Session, intent: PaymentIntent, student_id: str = "p_li_wei") -> dict:
    ch = session.get(PaymentChannel, intent.payee_channel_id)
    inst = session.get(Institution, ch.institution_id) if ch and ch.institution_id else None
    status = approvals.approval_status(session, intent, student_id) if intent.tier == "T3" else None
    remaining = ledger.remaining_usd(session, intent.payer_id)
    after = remaining if intent.status == "executed" else max(Decimal("0"), remaining - intent.usd_equivalent)
    approved = status["approved"] if status else {}
    timeline = [
        {"step": "created", "done": True},
        {"step": "bank_documents_verified", "done": intent.bank_verified_at is not None, "applies": intent.route == planner.ABOVE},
        {"step": "approval_requested", "done": intent.status in ("pending_approval", "held", "approved", "executed") and intent.tier == "T3",
         "applies": intent.tier == "T3"},
        {"step": "payer_approved", "done": intent.payer_id in approved, "applies": intent.tier == "T3"},
        {"step": "student_confirmed", "done": student_id in approved,
         "applies": intent.tier == "T3" and student_id in (status or {}).get("required", [])},
        {"step": "executed", "done": intent.status == "executed"},
    ]
    return {
        "type": "intent", "intent_id": intent.id, "purpose": intent.purpose, "status": intent.status,
        "status_reason": intent.status_reason, "tier": intent.tier, "route": intent.route,
        "payer": {"person_id": intent.payer_id, "name": _person_name(session, intent.payer_id)},
        "payee": {"channel_id": ch.id if ch else intent.payee_channel_id, "beneficiary_name": ch.beneficiary_name if ch else "?",
                  "account_masked": ch.account_masked if ch else "", "institution": inst.name if inst else None,
                  "verified": ch is not None, "verified_source": ch.verified_source if ch else ""},
        "amount": f"{intent.amount:.2f}", "currency": intent.currency, "fx_rate": fx.rate_str(intent.fx_rate) if intent.fx_rate else None,
        "fx_label": "simulated", "cny_equivalent": f"{intent.cny_equivalent:.2f}", "fee_cny": f"{intent.fee_cny:.2f}",
        "total_cny": f"{intent.cny_equivalent + intent.fee_cny:.2f}", "usd_equivalent": f"{intent.usd_equivalent:.2f}",
        "quota_after_usd": f"{after:.2f}", "reference": intent.reference, "due_date": intent.due_date,
        "fingerprint": intent.fingerprint, "risk": {"score": intent.risk_score, "level": intent.risk_level,
                                                    "signals": [s["code"] for s in intent.risk_signals]},
        "approvals": status, "timeline": timeline, "rule_checks": intent.rule_checks,
    }


def receipt_card(transfer: Transfer, intent: PaymentIntent) -> dict:
    return {"type": "receipt", "transfer_id": transfer.id, "intent_id": intent.id, "bank_reference": transfer.bank_reference,
            "amount": f"{transfer.amount:.2f}", "currency": transfer.currency, "fx_rate": fx.rate_str(transfer.fx_rate),
            "cny_debit": f"{transfer.cny_debit:.2f}", "fee_cny": f"{transfer.fee_cny:.2f}",
            "total_cny": f"{transfer.cny_debit + transfer.fee_cny:.2f}", "usd_equivalent": f"{transfer.usd_equivalent:.2f}",
            "fingerprint": intent.fingerprint, "executed_at": transfer.executed_at.isoformat(), "tier": intent.tier,
            "pdf_url": f"/api/receipts/{transfer.id}.pdf", "watermark": "SANDBOX — no real money moved"}


def denial_card(d: Decision) -> dict:
    rid = d.rule_id or "SYS-003"
    card = refusal_card(rid)
    card["reason"] = d.reason
    card["tool"] = d.tool
    return card


def _denied(d: Decision, extra: Optional[dict] = None) -> ToolOutcome:
    result = {**d.error(), **(extra or {})}
    return ToolOutcome(result=result, cards=[denial_card(d)], decision=d)


def _sanitize_fields(ex: dict) -> dict:
    out = {}
    for k, v in ex.items():
        if k == "beneficiary_account" and v:
            out[k] = mask_account(v)
        elif isinstance(v, str):
            out[k] = summary_zh.safe(v, 80)
        else:
            out[k] = v
    return out


def _doc(session: Session, doc_id: str) -> Document:
    return session.get(Document, doc_id)


def _turn_payment_usd(session: Session, state: TurnState) -> Optional[Decimal]:
    for doc_id in state.doc_ids:
        doc = _doc(session, doc_id)
        ex = (doc.extracted_json if doc else {}) or {}
        if doc and doc.payee_check_json.get("verdict") in ("verified", "warning") and ex.get("amount") and ex.get("currency"):
            try:
                return fx.to_usd(ex["currency"], Decimal(str(ex["amount"])))
            except fx.UnsupportedCurrency:
                return None
    return None


def checklist_card(intent: PaymentIntent) -> dict:
    if intent.route == planner.WITHIN:
        items = ["Payer's ID card (身份证)"]
        note = "ID only — within the payer's personal quota."
    else:
        items = planner.documented_route_checklist()
        note = ("Above the payer's remaining quota: the bank buys the currency against these documents "
                "(rule Q-002). A bank officer verifies them, then the normal T3 approval follows. Never split across relatives (T4-003).")
    return {"type": "checklist", "intent_id": intent.id, "route": intent.route, "items": items, "note": note,
            "bank_verified": intent.bank_verified_at is not None}


# ------------------------------------------------------------------ dispatcher
def dispatch(session: Session, name: str, args: Any, ctx: PolicyContext, state: TurnState, provider=None) -> ToolOutcome:
    state.tools_called.append(name)
    if name == "create_payment_intent" and isinstance(args, dict):
        return _create_intent(session, args, ctx)
    if name in ("request_approval", "execute_payment") and isinstance(args, dict) and set(args) == {"intent_id"} \
            and isinstance(args["intent_id"], str):
        return (_request_approval if name == "request_approval" else _execute)(session, args["intent_id"], ctx)
    d = policy.authorize(session, name, args, ctx)
    if not d.allowed:
        return _denied(d)
    impl = _IMPLS[name]
    return impl(session, args, ctx, state, provider, d)


def _create_intent(session: Session, args: dict, ctx: PolicyContext) -> ToolOutcome:
    d, intent = payments.create_intent(session, args, ctx)
    if intent is None:
        return _denied(d)
    card = intent_card(session, intent, ctx.student_id)
    if not d.allowed:
        out = _denied(d, {"intent": intent_view(intent)})
        out.cards.insert(0, card)
        return out
    return ToolOutcome(result={"intent": intent_view(intent), "outcome": d.outcome}, cards=[card], decision=d)


def _request_approval(session: Session, intent_id: str, ctx: PolicyContext) -> ToolOutcome:
    d = payments.request_approval(session, intent_id, ctx)
    if not d.allowed:
        return _denied(d)
    intent = session.get(PaymentIntent, intent_id)
    status = approvals.approval_status(session, intent, ctx.student_id)
    status["names"] = {p: _person_name(session, p) for p in status["required"]}
    return ToolOutcome(result={"intent": intent_view(intent), "approval_status": {"waiting_for": status["waiting_for"]}},
                       cards=[intent_card(session, intent, ctx.student_id), status], decision=d)


def _execute(session: Session, intent_id: str, ctx: PolicyContext) -> ToolOutcome:
    d, transfer = payments.execute(session, intent_id, ctx)
    intent = session.get(PaymentIntent, intent_id)
    if transfer is None:
        out = _denied(d, {"executed": False})
        if intent is not None:
            out.result["intent"] = intent_view(intent)
            out.cards.append(intent_card(session, intent, ctx.student_id))
        return out
    return ToolOutcome(result={"executed": True, "bank_reference": transfer.bank_reference, "intent": intent_view(intent)},
                       cards=[receipt_card(transfer, intent), intent_card(session, intent, ctx.student_id)], decision=d)


def _family(session, args, ctx, state, provider, d) -> ToolOutcome:
    ch = session.get(PaymentChannel, STUDENT_CHANNEL_ID)
    insts = [{"institution_id": i.id, "name": i.name,
              "channel_id": (session.exec(select(PaymentChannel).where(PaymentChannel.institution_id == i.id)).first() or ch).id}
             for i in session.exec(select(Institution))]
    sched = session.exec(select(AllowanceSchedule)).first()
    q = ledger.quota_card(session, ctx.payer_id)
    result = {
        "payer_id": ctx.payer_id, "payer_name": _person_name(session, ctx.payer_id),
        "student_id": ctx.student_id, "student_name": _person_name(session, ctx.student_id),
        "student_channel_id": ch.id, "student_account_masked": ch.account_masked,
        "institutions": insts, "quota": q,
        "balance_cny": f"{bank.account_for(session, ctx.payer_id).balance:.2f}",
        "allowance": {"amount": f"{sched.amount:.2f}", "currency": sched.currency, "day_of_month": sched.day_of_month,
                      "active": sched.active} if sched else None,
    }
    return ToolOutcome(result=result, cards=[{"type": "quota", **q}], decision=d)


def _read_document(session, args, ctx, state, provider, d) -> ToolOutcome:
    doc = _doc(session, args["doc_id"])
    f = doc.findings_json or {}
    result = {
        "doc_id": doc.id, "doc_type": (doc.extracted_json or {}).get("doc_type"),
        "fields": _sanitize_fields(doc.extracted_json or {}),
        "findings": {"hidden_spans": len(f.get("hidden_spans", [])), "injection_phrases": len(f.get("injection_hits", [])),
                     "bank_change_requests": len(f.get("bank_change_hits", [])), "invisible_chars": len(f.get("invisible", [])),
                     "lookalike_domains": [x["domain"] for x in f.get("lookalike_domains", [])],
                     "request_guard_rules": sorted({h["rule_id"] for h in f.get("guard_hits", [])})},
        "note": "Raw document text is quarantined and never shown to the planner.",
    }
    return ToolOutcome(result=result, decision=d)


def _summarize(session, args, ctx, state, provider, d) -> ToolOutcome:
    doc = _doc(session, args["doc_id"])
    card = summary_zh.add_ai_note(summary_zh.build(session, doc), provider)
    doc.summary_zh = card["zh"]
    session.add(doc)
    session.commit()
    return ToolOutcome(result={"zh": card["zh"], "en": card["en"]}, cards=[card], decision=d)


def _verify(session, args, ctx, state, provider, d) -> ToolOutcome:
    doc = _doc(session, args["doc_id"])
    pc = dict(doc.payee_check_json or {})
    cards = [pc]
    if pc.get("forbidden_rule"):
        r = refusal_card(pc["forbidden_rule"])
        r["reason"] = "; ".join(s["explanation"] for s in pc.get("signals", [])[:4])
        if pc.get("official_contact_email") or pc.get("mentioned_institution_id"):
            r["lawful_alternative"] += " A verification email can go only to the registry contact."
        cards.append(r)
    result = {k: pc.get(k) for k in ("verdict", "level", "score", "forbidden_rule", "institution_id", "mentioned_institution_id",
                                      "matched_channel_id", "purpose_guess", "notices")}
    result["signals"] = [s["code"] for s in pc.get("signals", [])]
    result["hidden_spans"] = len(pc.get("hidden_spans", []))
    return ToolOutcome(result=result, cards=cards, decision=d)


def _quota(session, args, ctx, state, provider, d) -> ToolOutcome:
    card = {"type": "quota", **ledger.quota_card(session, args["person_id"], _turn_payment_usd(session, state))}
    return ToolOutcome(result={"quota": {k: v for k, v in card.items() if k != "type"}}, cards=[card], decision=d)


def _fx(session, args, ctx, state, provider, d) -> ToolOutcome:
    q = fx.quote(args["currency"], Decimal(str(args["amount"]))).card()
    return ToolOutcome(result=q, cards=[{"type": "fx_quote", **q}], decision=d)


def _status(session, args, ctx, state, provider, d) -> ToolOutcome:
    intent = session.get(PaymentIntent, args["intent_id"])
    card = intent_card(session, intent, ctx.student_id)
    return ToolOutcome(result={"intent": intent_view(intent), "approvals": card["approvals"]}, cards=[card], decision=d)


def _schedule(session, args, ctx, state, provider, d) -> ToolOutcome:
    s = AllowanceSchedule(student_id=args["student_id"], payer_id=ctx.payer_id, payee_channel_id=args["payee_channel_id"],
                          amount=fx.q2(Decimal(str(args["amount"]))), currency=args["currency"].upper(),
                          day_of_month=int(args.get("day_of_month") or 1), active=False)
    session.add(s)
    session.commit()
    card = {"type": "explanation", "title": "Allowance schedule proposed (inactive)",
            "text": f"{s.currency} {s.amount:,.2f} on day {s.day_of_month} to {mask_account(session.get(PaymentChannel, s.payee_channel_id).account_full)}. "
                    "The payer must activate it; it then runs under the T2 caps."}
    return ToolOutcome(result={"schedule_id": s.id, "active": False}, cards=[card], decision=d)


def _documents(session, args, ctx, state, provider, d) -> ToolOutcome:
    intent = session.get(PaymentIntent, args["intent_id"])
    card = checklist_card(intent)
    return ToolOutcome(result={"route": card["route"], "items": card["items"]}, cards=[card], decision=d)


def _email(session, args, ctx, state, provider, d) -> ToolOutcome:
    inst = session.get(Institution, args["institution_id"])
    doc = _doc(session, args["doc_id"]) if args.get("doc_id") else None
    ex = (doc.extracted_json if doc else {}) or {}
    pc = (doc.payee_check_json if doc else {}) or {}
    concerns = [f"- {s['explanation']}" for s in pc.get("signals", [])[:5]]
    lines = [
        f"Dear {inst.name} Finance Office,",
        "",
        "I am the mother of your student LI WEI. I received a payment request and would like to confirm it before paying.",
    ]
    if ex.get("amount") and ex.get("currency"):
        lines.append(f"It asks for {ex['currency']} {Decimal(str(ex['amount'])):,.2f}"
                     + (f" with reference {summary_zh.safe(ex.get('reference'), 30)}" if ex.get("reference") else "") + ".")
    if concerns:
        lines += ["", "Points that worry me:"] + concerns
    lines += ["", "Could you please confirm the amount due and your official bank details for tuition payments?",
              "I will only pay the account listed in your official records.", "", "Kind regards,", "Zhang Min"]
    card = {"type": "email_draft", "to": inst.official_contact_email, "to_source": "verified registry",
            "subject": f"Please confirm tuition payment details for student LI WEI",
            "body": "\n".join(lines), "label": "Drafted by AI — review before sending", "ai_generated": True, "sent": False}
    return ToolOutcome(result={"to": card["to"], "subject": card["subject"], "sent": False}, cards=[card], decision=d)


def explanation_card(session: Session, intent: PaymentIntent) -> dict:
    return {"type": "explanation", "title": f"Why: intent {intent.fingerprint} is {intent.status}",
            "intent_id": intent.id, "status": intent.status, "tier": intent.tier, "checks": intent.rule_checks,
            "status_reason": intent.status_reason}


def _explain(session, args, ctx, state, provider, d) -> ToolOutcome:
    intent = session.get(PaymentIntent, args["intent_id"])
    card = explanation_card(session, intent)
    summary = [{"rule_id": c["rule_id"], "result": c["result"]} for c in intent.rule_checks]
    return ToolOutcome(result={"status": intent.status, "checks": summary}, cards=[card], decision=d)


def _clarify(session, args, ctx, state, provider, d) -> ToolOutcome:
    q = summary_zh.safe(args["question"], 300)
    return ToolOutcome(result={"question": q}, cards=[{"type": "clarify", "question": q}], decision=d)


_IMPLS = {
    "get_family_overview": _family, "read_document": _read_document, "summarize_in_chinese": _summarize,
    "verify_payee": _verify, "check_quota": _quota, "get_fx_quote": _fx, "get_status": _status,
    "schedule_allowance": _schedule, "build_document_list": _documents, "draft_verification_email": _email,
    "explain_decision": _explain, "ask_clarifying_question": _clarify,
}


def result_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def rule_title(rule_id: str) -> str:
    return rule(rule_id)["title"]

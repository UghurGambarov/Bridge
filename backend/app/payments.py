"""Payment intents: create, request approval, bank verification, execute, allowances.

Every mutating function starts with policy.authorize(); the bank re-checks the Decision.
The agent's tools (Phase 2) and the API both go through these functions.
"""
from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from .models import AllowanceSchedule, PaymentChannel, PaymentIntent, Transfer
from .quota import planner
from .sandbox import bank, clock, fx, receipts
from .security import audit, policy
from .security.digest import compute_digest, fingerprint
from .security.policy import Decision, PolicyContext


def _now(session: Session):
    return clock.now(session)


def create_intent(session: Session, args: dict, ctx: PolicyContext) -> tuple[Decision, Optional[PaymentIntent]]:
    decision = policy.authorize(session, "create_payment_intent", args, ctx)
    data = decision.data
    if not decision.allowed and not data.get("persistable"):
        return decision, None
    intent = PaymentIntent(
        id="pi_" + secrets.token_hex(5),
        purpose=args["purpose"], payer_id=args["payer_id"], payee_channel_id=args["payee_channel_id"],
        amount=fx.q2(Decimal(str(args["amount"]))), currency=args["currency"].upper(),
        reference=(args.get("reference") or "").strip() or None,
        doc_id=args.get("doc_id"), created_by=ctx.actor, created_at=_now(session),
        rule_checks=decision.checks_dicts(), first_audit_seq=decision.audit_seq,
    )
    if "plan" in data:
        plan: planner.QuotaPlan = data["plan"]
        q = data["quote"]
        intent.route = plan.route
        intent.usd_equivalent, intent.cny_equivalent = plan.usd_equivalent, plan.cny_equivalent
        intent.fx_rate, intent.fee_cny = q.rate_cny, q.fee_cny
    intent.due_date = data.get("due_date")
    intent.risk_score = data.get("risk_score", 0)
    intent.risk_level = data.get("risk_level", "LOW")
    intent.risk_signals = data.get("risk_signals", [])
    intent.tier = decision.tier if decision.tier in ("T2", "T3") else "T3"
    if decision.allowed:
        intent.status = data.get("status", "draft")
        intent.status_reason = data.get("status_reason", "")
    else:
        intent.status = "blocked"
        intent.status_reason = f"{decision.rule_id}: {decision.reason}"
    intent.digest = compute_digest(intent)
    intent.fingerprint = fingerprint(intent.digest)
    session.add(intent)
    audit.append(session, actor=ctx.actor, persona=ctx.persona, event="intent_created", rule_id=decision.rule_id,
                 decision=decision.outcome, reason=intent.status_reason or intent.status,
                 payload={"intent_id": intent.id, "purpose": intent.purpose, "amount": f"{intent.amount:.2f}",
                          "currency": intent.currency, "payee_channel_id": intent.payee_channel_id,
                          "tier": intent.tier, "status": intent.status, "route": intent.route,
                          "fingerprint": intent.fingerprint, "risk": intent.risk_level})
    decision.intent_id = intent.id
    return decision, intent


def request_approval(session: Session, intent_id: str, ctx: PolicyContext) -> Decision:
    decision = policy.authorize(session, "request_approval", {"intent_id": intent_id}, ctx)
    if decision.allowed:
        intent = session.get(PaymentIntent, intent_id)
        if intent.status == "draft":
            intent.status = "pending_approval"
            intent.updated_at = _now(session)
            session.add(intent)
            audit.append(session, actor=ctx.actor, persona=ctx.persona, event="approval_requested", rule_id="T3-001",
                         payload={"intent_id": intent.id, "fingerprint": intent.fingerprint})
    return decision


def bank_verify(session: Session, intent_id: str, officer: str = "Sandbox bank officer") -> PaymentIntent:
    """Simulated bank-counter verification of the documented route (not an agent tool)."""
    intent = session.get(PaymentIntent, intent_id)
    if intent is None or intent.status != "awaiting_documents":
        raise ValueError("Intent is not awaiting documents.")
    intent.bank_verified_at = _now(session)
    intent.status = "draft"
    intent.updated_at = intent.bank_verified_at
    intent.rule_checks = intent.rule_checks + [policy.RuleCheck("Q-002", "pass", f"Documents verified by {officer} (simulated).").as_dict()]
    session.add(intent)
    audit.append(session, actor="system", event="bank_documents_verified", rule_id="Q-002", decision="allow",
                 reason=f"{officer} verified the documented-route checklist (simulated).",
                 payload={"intent_id": intent.id, "checklist": planner.documented_route_checklist()})
    return intent


def execute(session: Session, intent_id: str, ctx: PolicyContext) -> tuple[Decision, Optional[Transfer]]:
    decision = policy.authorize(session, "execute_payment", {"intent_id": intent_id}, ctx)
    intent = session.get(PaymentIntent, intent_id)
    if not decision.allowed:
        if intent is not None and intent.tier == "T2" and intent.status == "draft":
            # A T2 payment that no longer fits the limits is held for T3 approval, never forced through.
            intent.tier = "T3"
            intent.status = "held"
            intent.status_reason = f"{decision.rule_id}: {decision.reason}"
            intent.updated_at = _now(session)
            session.add(intent)
            audit.append(session, actor="system", event="intent_held", rule_id=decision.rule_id, decision="require_approval",
                         reason=decision.reason, payload={"intent_id": intent.id})
        return decision, None
    try:
        transfer = bank.execute_transfer(session, intent, decision)
    except bank.BankError as e:
        audit.append(session, actor="system", event="execution_failed", decision="deny", reason=str(e),
                     payload={"intent_id": intent_id})
        decision.outcome, decision.reason = policy.DENY, str(e)
        return decision, None
    intent.status = "executed"
    intent.updated_at = transfer.executed_at
    intent.rule_checks = _merge_checks(intent.rule_checks, decision.checks_dicts())
    session.add(intent)
    exec_entry = audit.append(
        session, actor="system", persona=ctx.persona, event="payment_executed", rule_id=None, decision="allow",
        reason=f"{intent.tier} execution in sandbox bank",
        payload={"intent_id": intent.id, "transfer_id": transfer.id, "bank_reference": transfer.bank_reference,
                 "amount": f"{transfer.amount:.2f}", "currency": transfer.currency, "fx_rate": f"{transfer.fx_rate}",
                 "cny_debit": f"{transfer.cny_debit:.2f}", "fee_cny": f"{transfer.fee_cny:.2f}",
                 "usd_equivalent": f"{transfer.usd_equivalent:.2f}", "fingerprint": intent.fingerprint},
    )
    data = receipts.receipt_data(session, transfer, intent, (intent.first_audit_seq or exec_entry.seq, exec_entry.seq), ctx.student_id)
    transfer.receipt_pdf_path, transfer.receipt_json_path = receipts.write_receipt(data)
    session.add(transfer)
    audit.append(session, actor="system", event="receipt_issued",
                 payload={"intent_id": intent.id, "transfer_id": transfer.id, "fingerprint": intent.fingerprint})
    return decision, transfer


def _merge_checks(before: list, after: list) -> list:
    """Why-panel trace: creation-time checks, then execution-time checks (latest result wins per rule)."""
    merged: dict[str, dict] = {}
    for c in before + after:
        merged[c["rule_id"]] = c
    return list(merged.values())


def create_and_maybe_autoexecute(session: Session, args: dict, ctx: PolicyContext) -> dict:
    """Used by the allowance scheduler: create; if T2, execute immediately; otherwise leave held."""
    decision, intent = create_intent(session, args, ctx)
    result = {"decision": decision, "intent": intent, "transfer": None}
    if intent is not None and intent.tier == "T2" and intent.status == "draft":
        d2, transfer = execute(session, intent.id, ctx)
        result.update(execute_decision=d2, transfer=transfer)
    return result


def run_due_allowances(session: Session, ctx: PolicyContext) -> list[dict]:
    now = _now(session)
    period = now.strftime("%Y-%m")
    results = []
    for sched in session.exec(select(AllowanceSchedule).where(AllowanceSchedule.active == True)):  # noqa: E712
        if sched.last_run_period == period or now.day < sched.day_of_month:
            continue
        ch = session.get(PaymentChannel, sched.payee_channel_id)
        args = {"purpose": "allowance", "payer_id": sched.payer_id, "payee_channel_id": sched.payee_channel_id,
                "amount": str(sched.amount), "currency": sched.currency, "reference": f"ALLOWANCE-{period}"}
        sys_ctx = PolicyContext(payer_id=ctx.payer_id, student_id=ctx.student_id, actor="system", persona=None)
        res = create_and_maybe_autoexecute(session, args, sys_ctx)
        sched.last_run_period = period
        session.add(sched)
        session.commit()
        res["schedule_id"] = sched.id
        res["channel"] = ch.id if ch else None
        results.append(res)
    return results

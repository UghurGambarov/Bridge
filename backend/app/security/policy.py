"""THE choke point: authorize(tool, args, ctx) -> Decision.

"The AI proposes, the policy engine decides." No tool runs without this function, and every
decision is written to the audit log. Everything here is deterministic and reads only the
database and config/rules.yaml, so the guarantees hold even if the model is fully compromised.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlmodel import Session, select

from .. import state
from ..config import load_rules, rule, rule_param
from ..models import Approval, Consent, Device, Document, Institution, PaymentChannel, PaymentIntent, Person
from ..quota import planner, structuring
from ..sandbox import clock, fx
from . import approvals, audit, risk
from .digest import compute_digest

FEE_PURPOSES = ("tuition", "accommodation", "deposit")
PURPOSES = FEE_PURPOSES + ("allowance",)
MONEY_TOOLS = ("create_payment_intent", "request_approval", "execute_payment", "schedule_allowance")

ALLOW, DENY, REQUIRE_APPROVAL = "allow", "deny", "require_approval"


# ------------------------------------------------------------------ tool allow-list + schemas
@dataclass(frozen=True)
class ToolSpec:
    tier: str
    args: dict  # name -> "str" | "num" | "int"
    required: tuple = ()


TOOLS: dict[str, ToolSpec] = {
    "get_family_overview": ToolSpec("T0", {}),
    "read_document": ToolSpec("T0", {"doc_id": "str"}, ("doc_id",)),
    "summarize_in_chinese": ToolSpec("T0", {"doc_id": "str"}, ("doc_id",)),
    "verify_payee": ToolSpec("T0", {"doc_id": "str"}, ("doc_id",)),
    "check_quota": ToolSpec("T0", {"person_id": "str"}, ("person_id",)),
    "get_fx_quote": ToolSpec("T0", {"currency": "str", "amount": "num"}, ("currency", "amount")),
    "create_payment_intent": ToolSpec(
        "T1",
        {"purpose": "str", "payer_id": "str", "payee_channel_id": "str", "amount": "num", "currency": "str",
         "reference": "str", "doc_id": "str"},
        ("purpose", "payer_id", "payee_channel_id", "amount", "currency"),
    ),
    "request_approval": ToolSpec("T1", {"intent_id": "str"}, ("intent_id",)),
    "execute_payment": ToolSpec("T2/T3", {"intent_id": "str"}, ("intent_id",)),
    "get_status": ToolSpec("T0", {"intent_id": "str"}, ("intent_id",)),
    "schedule_allowance": ToolSpec(
        "T1", {"student_id": "str", "payee_channel_id": "str", "amount": "num", "currency": "str", "day_of_month": "int"},
        ("student_id", "payee_channel_id", "amount", "currency"),
    ),
    "build_document_list": ToolSpec("T1", {"intent_id": "str"}, ("intent_id",)),
    "draft_verification_email": ToolSpec("T1", {"institution_id": "str", "doc_id": "str"}, ("institution_id",)),
    "explain_decision": ToolSpec("T0", {"intent_id": "str"}, ("intent_id",)),
}

# Raw payment identifiers the model must never supply (T4-007).
_ACCOUNT_KEY_RE = re.compile(r"account|iban|wallet|swift|bic|beneficiary|card|routing|sort_?code|address", re.I)
_IBAN_RE = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}")
_WALLET_RE = re.compile(r"0x[a-fA-F0-9]{20,}|\bbc1[a-z0-9]{20,}|\bT[1-9A-HJ-NP-Za-km-z]{33}\b")


def looks_like_account(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    compact = re.sub(r"[\s-]", "", value)
    if _IBAN_RE.search(compact) or _WALLET_RE.search(value):
        return True
    return bool(re.search(r"\d{12,}", compact.upper().replace("TEST", "")))


# ------------------------------------------------------------------ data classes
@dataclass
class RuleCheck:
    rule_id: str
    result: str  # pass | needs_approval | block | info
    detail: str = ""

    def as_dict(self) -> dict:
        r = load_rules().get(self.rule_id, {})
        return {"rule_id": self.rule_id, "title": r.get("title", self.rule_id), "result": self.result,
                "detail": self.detail, "source": r.get("source", ""), "status": r.get("status", "")}


@dataclass
class PolicyContext:
    payer_id: str = "p_zhang_min"
    student_id: str = "p_li_wei"
    actor: str = "agent"  # agent | system | user
    actor_person_id: Optional[str] = None
    persona: Optional[str] = None
    session_id: Optional[str] = None
    split_request: bool = False  # set by the request guard (T2-003)


@dataclass
class Decision:
    outcome: str
    tool: str
    rule_id: Optional[str] = None
    reason: str = ""
    checks: list = field(default_factory=list)
    tier: Optional[str] = None
    intent_id: Optional[str] = None
    digest: Optional[str] = None
    data: dict = field(default_factory=dict)
    audit_seq: Optional[int] = None

    @property
    def allowed(self) -> bool:
        return self.outcome in (ALLOW, REQUIRE_APPROVAL)

    def checks_dicts(self) -> list[dict]:
        return [c.as_dict() for c in self.checks]

    def error(self) -> dict:
        """Structured error returned to the model on denial."""
        return {"error": "denied_by_policy", "rule_id": self.rule_id,
                "title": rule(self.rule_id)["title"] if self.rule_id in load_rules() else None, "reason": self.reason}


class _Deny(Exception):
    def __init__(self, rule_id: Optional[str], reason: str):
        super().__init__(reason)
        self.rule_id, self.reason = rule_id, reason


# ------------------------------------------------------------------ public entry point
def authorize(session: Session, tool: str, args: Any, ctx: PolicyContext) -> Decision:
    checks: list[RuleCheck] = []
    scratch: dict = {}  # partial results kept on denial (e.g. so a blocked intent can be recorded)
    try:
        decision = _evaluate(session, tool, args, ctx, checks, scratch)
    except _Deny as d:
        checks.append(RuleCheck(d.rule_id or "SYS-003", "block", d.reason))
        decision = Decision(DENY, tool, d.rule_id, d.reason, checks, tier=TOOLS[tool].tier if tool in TOOLS else None,
                            data=scratch)
        if isinstance(args, dict) and isinstance(args.get("intent_id"), str):
            decision.intent_id = args["intent_id"]
    decision.checks = checks
    entry = audit.append(
        session, actor="policy", persona=ctx.persona, event="policy_decision", rule_id=decision.rule_id,
        decision=decision.outcome, reason=decision.reason,
        payload={"tool": tool, "args": args if isinstance(args, dict) else str(args), "caller": ctx.actor,
                 "tier": decision.tier, "intent_id": decision.intent_id,
                 "checks": [{"rule_id": c.rule_id, "result": c.result} for c in checks]},
    )
    decision.audit_seq = entry.seq
    return decision


def _evaluate(session: Session, tool: str, args: Any, ctx: PolicyContext, checks: list[RuleCheck],
              scratch: dict) -> Decision:
    if tool not in TOOLS:
        raise _Deny("SYS-003", f"Unknown tool '{tool}'. Only registered tools can run; there is no approval tool.")
    spec = TOOLS[tool]
    _validate_args(tool, spec, args)
    checks.append(RuleCheck("SYS-003", "pass", "Registered tool, schema-valid arguments."))
    if any(looks_like_account(v) for v in args.values()):
        raise _Deny("T4-007", "An argument contains a raw account number, IBAN or wallet address.")
    checks.append(RuleCheck("T4-007", "pass", "No raw account identifiers in arguments."))
    if tool in MONEY_TOOLS:
        if state.is_frozen(session):
            raise _Deny("SYS-001", "The system is frozen (kill switch). No payment can be created, approved or executed.")
        checks.append(RuleCheck("SYS-001", "pass", "System not frozen."))
    if tool == "create_payment_intent":
        return _create_intent(session, tool, args, ctx, checks, scratch)
    handler = _HANDLERS.get(tool, _allow_read)
    return handler(session, tool, args, ctx, checks)


def _validate_args(tool: str, spec: ToolSpec, args: Any) -> None:
    if not isinstance(args, dict):
        raise _Deny("SYS-003", "Arguments must be a JSON object.")
    extra = set(args) - set(spec.args)
    if extra:
        if any(_ACCOUNT_KEY_RE.search(k) or looks_like_account(args[k]) for k in extra):
            raise _Deny("T4-007", f"Unexpected payment-detail field(s) {sorted(extra)}: payments accept only a registry payee_channel_id.")
        raise _Deny("SYS-003", f"Unexpected field(s) {sorted(extra)} (additionalProperties: false).")
    for name in spec.required:
        if args.get(name) in (None, ""):
            raise _Deny("SYS-003", f"Missing required argument '{name}'.")
    for name, kind in spec.args.items():
        if name not in args or args[name] is None:
            continue
        v = args[name]
        if kind == "str" and not isinstance(v, str):
            raise _Deny("SYS-003", f"Argument '{name}' must be a string.")
        if kind == "int" and (not isinstance(v, int) or isinstance(v, bool)):
            raise _Deny("SYS-003", f"Argument '{name}' must be an integer.")
        if kind == "num":
            if isinstance(v, bool):
                raise _Deny("SYS-003", f"Argument '{name}' must be a number.")
            try:
                Decimal(str(v))
            except InvalidOperation:
                raise _Deny("SYS-003", f"Argument '{name}' must be a number.")


def _amount(v: Any) -> Decimal:
    a = fx.q2(Decimal(str(v)))
    if a <= 0 or a > Decimal("10000000"):
        raise _Deny("SYS-003", "Amount must be positive and realistic.")
    return a


# ------------------------------------------------------------------ handlers
def _allow_read(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    return Decision(ALLOW, tool, None, "Read-only (T0) or preparation (T1) tool.", tier=TOOLS[tool].tier)


def _has_consent(session: Session, person_id: str, purpose: str) -> bool:
    for c in session.exec(select(Consent).where(Consent.person_id == person_id, Consent.revoked_at.is_(None))):
        if purpose in (c.purposes or []):
            return True
    return False


def _doc_tool(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    doc = session.get(Document, args["doc_id"])
    if doc is None:
        raise _Deny("SYS-003", "Unknown document.")
    if not _has_consent(session, doc.uploaded_by, "document_processing"):
        raise _Deny("P-001", "The uploader has not consented to document processing.")
    checks.append(RuleCheck("P-001", "pass", "Uploader consented to document processing."))
    return Decision(ALLOW, tool, None, "Read-only document tool.", tier="T0")


def _check_quota(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    if args["person_id"] != ctx.payer_id:
        raise _Deny("P-004", "The agent reads only the payer's own quota. Quotas are personal and are never combined (T4-003).")
    checks.append(RuleCheck("P-004", "pass", "Reading the payer's own quota."))
    return Decision(ALLOW, tool, None, "Payer's quota.", tier="T0")


def _fx_quote(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    try:
        fx.rate_cny(args["currency"])
    except fx.UnsupportedCurrency:
        raise _Deny("SYS-003", f"Unsupported currency {args['currency']}.")
    _amount(args["amount"])
    return Decision(ALLOW, tool, None, "Simulated FX quote.", tier="T0")


def _intent_tool(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    intent = session.get(PaymentIntent, args["intent_id"])
    if intent is None:
        raise _Deny("SYS-003", "Unknown intent.")
    return Decision(ALLOW, tool, None, "Read or prepare on an existing intent.", tier=TOOLS[tool].tier, intent_id=intent.id)


def _draft_email(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    inst = session.get(Institution, args["institution_id"])
    if inst is None:
        raise _Deny("T4-002", "Unknown institution: verification emails go only to registry contacts.")
    checks.append(RuleCheck("T4-002", "pass", f"Recipient is the registry contact of {inst.name}."))
    return Decision(ALLOW, tool, None, "Draft only; never sent by the agent.", tier="T1",
                    data={"to": inst.official_contact_email})


def _student_channel_ok(session: Session, channel: PaymentChannel, ctx: PolicyContext) -> tuple[bool, str]:
    student = session.get(Person, ctx.student_id)
    if channel.type != "same_name_personal" or channel.owner_person_id != ctx.student_id or student is None:
        return False, "Autonomous payments go only to the student's own verified account."
    if channel.beneficiary_name.upper() != (student.passport_name or "").upper():
        return False, "Beneficiary name does not match the student's passport name."
    return True, f"Same-name verified account of the student ({channel.account_masked})."


def _schedule_allowance(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    channel = session.get(PaymentChannel, args["payee_channel_id"])
    if channel is None:
        raise _Deny("T4-002", "Unknown payee channel.")
    if args["student_id"] != ctx.student_id:
        raise _Deny("T2-001", "Allowances go only to the student.")
    ok, detail = _student_channel_ok(session, channel, ctx)
    if not ok:
        raise _Deny("T2-001", detail)
    checks.append(RuleCheck("T2-001", "pass", detail))
    return Decision(REQUIRE_APPROVAL, tool, "T3-001", "The schedule is created inactive; the payer activates it.", tier="T1")


def _create_intent(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck],
                   data: dict) -> Decision:
    purpose = args["purpose"]
    if purpose not in PURPOSES:
        raise _Deny("SYS-003", f"Unknown purpose '{purpose}'.")
    amount = _amount(args["amount"])
    currency = args["currency"].upper()
    reference = (args.get("reference") or "").strip() or None

    # T4-003: the quota belongs to one person; the payer is always the session's payer.
    if args["payer_id"] != ctx.payer_id:
        raise _Deny("T4-003", "The payer must be the family's payer. Using another person's FX quota (分拆购汇) is forbidden.")
    payer = session.get(Person, args["payer_id"])
    if payer is None or payer.deleted_at is not None:
        raise _Deny("SYS-003", "Unknown payer.")
    checks.append(RuleCheck("T4-003", "pass", "Payer's own quota only."))

    channel = session.get(PaymentChannel, args["payee_channel_id"])
    if channel is None:
        raise _Deny("T4-002", "Unknown payee_channel_id: payments go only to channels in the verified registry.")
    if channel.currency != currency:
        raise _Deny("T4-002", f"Currency {currency} does not match the registered channel currency {channel.currency}.")
    data.update({"persistable": True, "channel_id": channel.id})

    inst: Optional[Institution] = None
    sigs: list[dict] = []
    if purpose in FEE_PURPOSES:
        if channel.type != "institution":
            raise _Deny("T4-001", "Tuition, accommodation and deposits are paid only to the institution's own account.")
        checks.append(RuleCheck("T4-001", "pass", "Fees go to an institutional account."))
        inst = session.get(Institution, channel.institution_id)
        checks.append(RuleCheck("T4-002", "pass", f"Payee is the registry channel of {inst.name} ({channel.account_masked})."))
        if reference and inst.reference_regex and not re.fullmatch(inst.reference_regex, reference):
            sigs.append(risk.signal("REFERENCE_FORMAT_MISMATCH", f"Reference '{reference}' does not match {inst.reference_regex}."))
        ok, detail = risk.amount_in_range(inst, purpose, amount, currency)
        if not ok:
            sigs.append(risk.signal("AMOUNT_OUTSIDE_FEE_RANGE", detail))
    else:
        ok, detail = _student_channel_ok(session, channel, ctx)
        if not ok:
            raise _Deny("T2-001", detail)
        checks.append(RuleCheck("T2-001", "pass", detail))

    # Document-derived risk (deterministic detectors + registry comparison done at ingestion).
    doc_id = args.get("doc_id")
    due_date = None
    if doc_id:
        doc = session.get(Document, doc_id)
        if doc is None:
            raise _Deny("SYS-003", "Unknown document.")
        pc = doc.payee_check_json or {}
        if pc.get("forbidden_rule"):
            raise _Deny(pc["forbidden_rule"], f"The document failed payee verification: {', '.join(s['code'] for s in pc.get('signals', []))}. "
                                              "The registered payee stays unchanged.")
        if pc.get("matched_channel_id") and pc["matched_channel_id"] != channel.id:
            raise _Deny("T4-002", "The selected channel differs from the payee verified for this document.")
        ex = doc.extracted_json or {}
        if ex.get("amount") is not None and (Decimal(str(ex["amount"])) != amount or (ex.get("currency") or currency) != currency):
            raise _Deny("SYS-003", "Amount or currency does not match the verified document.")
        if ex.get("reference") and reference and ex["reference"] != reference:
            raise _Deny("SYS-003", "Reference does not match the verified document.")
        due_date = ex.get("due_date")
        sigs += [s for s in pc.get("signals", []) if s["code"] not in {x["code"] for x in sigs}]
    score, level = risk.score_signals([s["code"] for s in sigs])
    data.update({"risk_score": score, "risk_level": level, "risk_signals": sigs, "due_date": due_date})
    if level == "HIGH":
        raise _Deny(risk.forbidden_rule_for({s["code"] for s in sigs}, level) or "T4-002", f"Risk HIGH ({score}).")

    # Q-003 structuring.
    ok, detail = structuring.check_q003(session, ctx.payer_id, channel.id, reference)
    if not ok:
        raise _Deny("Q-003", detail)
    checks.append(RuleCheck("Q-003", "pass", detail))

    # Quota plan on the payer's personal quota.
    plan = planner.plan(session, ctx.payer_id, currency, amount)
    quote = fx.quote(currency, amount)
    data.update({"plan": plan, "quote": quote})
    checks.append(RuleCheck("Q-001", "pass" if plan.route == planner.WITHIN else "info",
                            f"USD {plan.usd_equivalent:,.2f} vs remaining USD {plan.remaining_before_usd:,.2f}."))
    if plan.route == planner.ABOVE:
        checks.append(RuleCheck("Q-002", "needs_approval", "Above the payer's remaining quota: documented route (bank verifies documents)."))

    # Tier.
    if purpose in FEE_PURPOSES:
        if level == "MEDIUM":
            checks.append(RuleCheck("T3-001", "needs_approval", f"Risk MEDIUM ({score}): approval with warning."))
        else:
            checks.append(RuleCheck("T3-001", "needs_approval", "Institutional payment: T3 approval required."))
        data["status"] = "awaiting_documents" if plan.route == planner.ABOVE else "draft"
        return Decision(REQUIRE_APPROVAL, tool, "T3-001", "T3: executes only after the required approvals.", tier="T3", data=data)

    held = _t2_hold_reasons(session, channel.id, plan, level, ctx, None)
    if held:
        for rid, detail in held:
            checks.append(RuleCheck(rid, "needs_approval", detail))
        data["status"] = "held"
        data["status_reason"] = "; ".join(d for _, d in held)
        return Decision(REQUIRE_APPROVAL, tool, held[0][0], "Held for T3 approval: " + data["status_reason"], tier="T3", data=data)
    checks.append(RuleCheck("T2-002", "pass", "Within the per-transaction and rolling 30-day caps."))
    checks.append(RuleCheck("T2-003", "pass", "No splitting pattern."))
    data["status"] = "draft"
    return Decision(ALLOW, tool, None, "T2: may execute autonomously within limits.", tier="T2", data=data)


def _t2_hold_reasons(session: Session, channel_id: str, plan: planner.QuotaPlan, level: str, ctx: PolicyContext,
                     exclude_intent_id: Optional[str]) -> list[tuple[str, str]]:
    reasons: list[tuple[str, str]] = []
    per_tx = Decimal(str(rule_param("T2-002", "per_transaction_usd")))
    rolling = Decimal(str(rule_param("T2-002", "rolling_30d_usd")))
    stats = structuring.t2_window_stats(session, channel_id, clock.now(session), exclude_intent_id)
    if plan.usd_equivalent > per_tx:
        reasons.append(("T2-002", f"USD {plan.usd_equivalent:,.2f} is above the per-transaction cap USD {per_tx:,.0f}"))
    if stats["sum_30d_usd"] + plan.usd_equivalent > rolling:
        reasons.append(("T2-002", f"Rolling 30 days would reach USD {stats['sum_30d_usd'] + plan.usd_equivalent:,.2f} (cap USD {rolling:,.0f})"))
    if stats["count_window"] >= int(rule_param("T2-003", "max_payments_in_window", 2)):
        reasons.append(("T2-003", f"{stats['count_window'] + 1} payments to the same payee within {stats['window_hours']}h"))
    if ctx.split_request:
        reasons.append(("T2-003", "Explicit request to split a payment so it needs no approval"))
    if plan.route != planner.WITHIN:
        reasons.append(("Q-002", "Not enough personal quota left: documented route required"))
    if level != "LOW":
        reasons.append(("T3-001", f"Risk {level}: autonomous execution requires LOW risk"))
    return reasons


def _request_approval(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    intent = session.get(PaymentIntent, args["intent_id"])
    if intent is None:
        raise _Deny("SYS-003", "Unknown intent.")
    if intent.status == "awaiting_documents":
        raise _Deny("Q-002", "Above-quota route: a bank officer must verify the documents before approval.")
    if intent.status not in ("draft", "pending_approval", "held"):
        raise _Deny("SYS-003", f"Intent is '{intent.status}'; approval cannot be requested.")
    if intent.tier == "T2" and intent.status == "draft":
        raise _Deny("SYS-003", "T2 intent: executes autonomously within limits, no approval needed.")
    checks.append(RuleCheck("T3-001", "needs_approval", "Approval requested from: " + ", ".join(required_approver_ids(session, intent, ctx))))
    return Decision(REQUIRE_APPROVAL, tool, "T3-001", "Approval requested.", tier="T1", intent_id=intent.id)


def required_approver_ids(session: Session, intent: PaymentIntent, ctx: PolicyContext) -> list[str]:
    return approvals.required_approvers(intent, ctx.student_id)


def _execute(session: Session, tool: str, args: dict, ctx: PolicyContext, checks: list[RuleCheck]) -> Decision:
    intent = session.get(PaymentIntent, args["intent_id"])
    if intent is None:
        raise _Deny("SYS-003", "Unknown intent.")
    if intent.status == "executed":
        raise _Deny("T3-003", "Intent already executed; execution is single-use.")
    if intent.status in ("blocked", "refused", "rejected", "expired"):
        raise _Deny("SYS-003", f"Intent is '{intent.status}'.")
    if intent.status == "awaiting_documents" or (intent.route == planner.ABOVE and intent.bank_verified_at is None):
        raise _Deny("Q-002", "Above-quota route: no execution before the bank officer verifies the documents.")

    # T3-002: recompute the digest from the CURRENT database state.
    digest = compute_digest(intent)
    if digest != intent.digest:
        raise _Deny("T3-002", "The intent changed after it was created: digest mismatch.")
    checks.append(RuleCheck("T3-002", "pass", f"Digest recomputed from current state matches ({intent.fingerprint})."))

    channel = session.get(PaymentChannel, intent.payee_channel_id)
    if channel is None:
        raise _Deny("T4-002", "Payee channel is no longer in the registry.")
    if intent.purpose in FEE_PURPOSES and channel.type != "institution":
        raise _Deny("T4-001", "Fees go only to institutional accounts.")
    if intent.risk_level == "HIGH":
        raise _Deny("T4-002", "Risk HIGH.")
    ok, detail = structuring.check_q003(session, intent.payer_id, channel.id, intent.reference, exclude_intent_id=intent.id)
    if not ok:
        raise _Deny("Q-003", detail)
    checks.append(RuleCheck("Q-003", "pass", detail))

    plan = planner.plan(session, intent.payer_id, intent.currency, intent.amount)
    if intent.route == planner.WITHIN and plan.route != planner.WITHIN:
        raise _Deny("Q-002", "Quota changed since the intent was created; the amount no longer fits. Re-plan via the documented route.")
    checks.append(RuleCheck("Q-001", "pass" if intent.route == planner.WITHIN else "info",
                            "Within the payer's quota." if intent.route == planner.WITHIN else "Documented route, bank-verified."))

    if intent.tier == "T2":
        ok, detail = _student_channel_ok(session, channel, ctx)
        if not ok:
            raise _Deny("T2-001", detail)
        checks.append(RuleCheck("T2-001", "pass", detail))
        held = _t2_hold_reasons(session, channel.id, plan, intent.risk_level, ctx, intent.id)
        if held:
            raise _Deny(held[0][0], "; ".join(d for _, d in held))
        checks.append(RuleCheck("T2-002", "pass", "Within caps."))
        checks.append(RuleCheck("T2-003", "pass", "No splitting pattern."))
        return Decision(ALLOW, tool, None, "T2 autonomous execution within limits.", tier="T2", intent_id=intent.id, digest=digest)

    # T3: approvals.
    _check_approvals(session, intent, digest, ctx, checks)
    return Decision(ALLOW, tool, None, "T3 execution: all approvals valid.", tier="T3", intent_id=intent.id, digest=digest)


def _check_approvals(session: Session, intent: PaymentIntent, digest: str, ctx: PolicyContext, checks: list[RuleCheck]) -> None:
    now = clock.now(session)
    ttl = approvals.ttl()
    used = list(session.exec(select(Approval).where(Approval.intent_id == intent.id, Approval.used_at.is_not(None))))
    required = required_approver_ids(session, intent, ctx)
    persons, devices = set(), set()
    for person_id in required:
        mine = [a for a in used if a.person_id == person_id]
        if not mine:
            raise _Deny("T3-001", f"Missing approval from {person_id}.")
        a = max(mine, key=lambda x: x.used_at)
        if a.digest != digest:
            raise _Deny("T3-002", f"Approval by {person_id} was for a different digest.")
        if now - a.used_at > ttl:
            raise _Deny("T3-003", f"Approval by {person_id} is older than {ttl.seconds // 60} minutes.")
        dev = session.get(Device, a.device_id)
        if dev is None or dev.person_id != person_id or dev.revoked_at is not None:
            raise _Deny("T3-004", "Approval device is not an enrolled device of the approver.")
        if a.device_id in devices or person_id in persons:
            raise _Deny("T3-004", "Approvals must come from distinct people on distinct devices.")
        persons.add(person_id)
        devices.add(a.device_id)
    checks.append(RuleCheck("T3-001", "pass", f"Approved by {', '.join(required)}."))
    checks.append(RuleCheck("T3-003", "pass", "Approvals single-use and fresh."))
    checks.append(RuleCheck("T3-004", "pass", "Distinct approvers on distinct devices."))


_HANDLERS = {
    "read_document": _doc_tool,
    "summarize_in_chinese": _doc_tool,
    "verify_payee": _doc_tool,
    "check_quota": _check_quota,
    "get_fx_quote": _fx_quote,
    "request_approval": _request_approval,
    "execute_payment": _execute,
    "get_status": _intent_tool,
    "build_document_list": _intent_tool,
    "explain_decision": _intent_tool,
    "schedule_allowance": _schedule_allowance,
    "draft_verification_email": _draft_email,
}

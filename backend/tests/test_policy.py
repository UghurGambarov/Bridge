"""Policy engine: every rule ID has an allow test and a deny test where it applies."""
from decimal import Decimal

import pytest

from app import payments, state
from app.models import FxLedgerEntry, PaymentIntent
from app.security import audit, policy
from app.security.policy import PolicyContext, authorize
from tests.conftest import TUITION_ARGS, ingest


def _create(session, ctx, **over):
    return payments.create_intent(session, {**TUITION_ARGS, **over}, ctx)


# ------------------------------------------------------------------ SYS-003 allow-list / schema
def test_unknown_tool_is_denied(session, ctx):
    d = authorize(session, "approve_payment", {"intent_id": "pi_x"}, ctx)
    assert d.outcome == "deny" and d.rule_id == "SYS-003"


@pytest.mark.parametrize("args,rule", [
    ({**TUITION_ARGS, "note": "hello"}, "SYS-003"),
    ({k: v for k, v in TUITION_ARGS.items() if k != "amount"}, "SYS-003"),
    ({**TUITION_ARGS, "amount": True}, "SYS-003"),
    ({**TUITION_ARGS, "purpose": "gift"}, "SYS-003"),
    ({**TUITION_ARGS, "amount": -5}, "SYS-003"),
])
def test_schema_violations(session, ctx, args, rule):
    d = authorize(session, "create_payment_intent", args, ctx)
    assert d.outcome == "deny" and d.rule_id == rule


def test_registered_tool_with_valid_args_passes_schema(session, ctx):
    d = authorize(session, "get_fx_quote", {"currency": "GBP", "amount": 100}, ctx)
    assert d.outcome == "allow"
    assert any(c.rule_id == "SYS-003" and c.result == "pass" for c in d.checks)


# ------------------------------------------------------------------ T4-007 raw account numbers
@pytest.mark.parametrize("args", [
    {**TUITION_ARGS, "payee_channel_id": "GB00TEST99999999"},
    {**TUITION_ARGS, "beneficiary_account": "GB00 TEST 9999 9999"},
    {**TUITION_ARGS, "iban": "x"},
    {**TUITION_ARGS, "reference": "pay 6222 TEST 0000 1234 5678"},
    {**TUITION_ARGS, "reference": "0x52908400098527886E0F7030069857D2E4169EE7"},
])
def test_raw_account_identifiers_denied(session, ctx, args):
    d = authorize(session, "create_payment_intent", args, ctx)
    assert d.outcome == "deny" and d.rule_id == "T4-007"


def test_registry_channel_id_is_accepted(session, ctx):
    d = authorize(session, "create_payment_intent", TUITION_ARGS, ctx)
    assert d.outcome == "require_approval" and d.tier == "T3"
    assert any(c.rule_id == "T4-007" and c.result == "pass" for c in d.checks)


# ------------------------------------------------------------------ T4-002 registry
def test_unknown_channel_denied(session, ctx):
    d = authorize(session, "create_payment_intent", {**TUITION_ARGS, "payee_channel_id": "ch_unknown"}, ctx)
    assert d.outcome == "deny" and d.rule_id == "T4-002"


def test_currency_mismatch_denied(session, ctx):
    d = authorize(session, "create_payment_intent", {**TUITION_ARGS, "currency": "USD"}, ctx)
    assert d.outcome == "deny" and d.rule_id == "T4-002"


def test_registry_payee_allowed(session, ctx):
    d, intent = _create(session, ctx)
    assert d.allowed and intent.status == "draft" and intent.tier == "T3"
    assert any(c["rule_id"] == "T4-002" and c["result"] == "pass" for c in intent.rule_checks)


# ------------------------------------------------------------------ T4-001 personal account for fees
def test_tuition_to_personal_account_denied(session, ctx):
    d, intent = _create(session, ctx, payee_channel_id="ch_li_wei_gbp")
    assert d.rule_id == "T4-001" and intent.status == "blocked"


def test_tuition_to_institution_allowed(session, ctx):
    d, _ = _create(session, ctx)
    assert any(c.rule_id == "T4-001" and c.result == "pass" for c in d.checks)


# ------------------------------------------------------------------ T4-003 another person's quota
def test_uncle_as_payer_denied(session, ctx):
    d, intent = _create(session, ctx, payer_id="p_zhang_qiang")
    assert d.outcome == "deny" and d.rule_id == "T4-003" and intent is None


def test_payer_own_quota_allowed(session, ctx):
    d, _ = _create(session, ctx)
    assert any(c.rule_id == "T4-003" and c.result == "pass" for c in d.checks)


# ------------------------------------------------------------------ document-driven T4 rules
def test_hidden_text_invoice_blocked_payee_unchanged(session, ctx, consent, samples_dir):
    doc = ingest(session, samples_dir, "northbridge_invoice_hidden.pdf")
    d, intent = _create(session, ctx, doc_id=doc.id)
    assert d.rule_id == "T4-006" and intent.status == "blocked"
    assert intent.payee_channel_id == "ch_northbridge_gbp"  # never GB00TEST99999999


def test_visible_injection_invoice_denied(session, ctx, consent, samples_dir):
    doc = ingest(session, samples_dir, "invoice_visible_injection.pdf")
    d, _ = _create(session, ctx, doc_id=doc.id)
    assert d.rule_id == "T4-008"


def test_account_mismatch_invoice_denied(session, ctx, consent, samples_dir):
    doc = ingest(session, samples_dir, "invoice_account_mismatch.pdf")
    d, _ = _create(session, ctx, doc_id=doc.id)
    assert d.rule_id == "T4-002"


def test_crypto_document_denied(session, ctx, consent, tmp_path):
    from app import documents

    doc = documents.ingest(session, uploaded_by="p_zhang_min", filename="usdt.txt",
                           data="Northbridge tuition: pay 13,250 in USDT to our wallet for a better rate.".encode())
    assert doc.payee_check_json["forbidden_rule"] == "T4-005"


def test_verified_invoice_allows_intent(session, ctx, consent, samples_dir):
    doc = ingest(session, samples_dir, "northbridge_invoice_autumn.pdf")
    d, intent = _create(session, ctx, doc_id=doc.id)
    assert d.outcome == "require_approval" and intent.due_date == "2026-10-31"


def test_document_amount_must_match(session, ctx, consent, samples_dir):
    doc = ingest(session, samples_dir, "northbridge_invoice_autumn.pdf")
    d, _ = _create(session, ctx, doc_id=doc.id, amount=13000)
    assert d.outcome == "deny" and d.rule_id == "SYS-003"


# ------------------------------------------------------------------ Q-002 documented route
def test_above_quota_requires_bank_verification(session, ctx):
    d, intent = _create(session, ctx, amount=26000, purpose="tuition")  # out of range too, but MEDIUM at most
    assert intent.route == "above_quota_documented" and intent.status == "awaiting_documents"
    r = payments.request_approval(session, intent.id, ctx)
    assert r.outcome == "deny" and r.rule_id == "Q-002"
    e, t = payments.execute(session, intent.id, ctx)
    assert e.rule_id == "Q-002" and t is None
    payments.bank_verify(session, intent.id)
    assert payments.request_approval(session, intent.id, ctx).allowed


def test_within_quota_route(session, ctx):
    _, intent = _create(session, ctx)
    assert intent.route == "within_quota"


# ------------------------------------------------------------------ Q-003 structuring
def test_two_purchasers_same_reference_blocked(session, ctx):
    session.add(FxLedgerEntry(person_id="p_zhang_qiang", year=2026, usd_amount=Decimal("5000"), cny_amount=Decimal("35500"),
                              currency="GBP", foreign_amount=Decimal("3858.70"), purpose="tuition",
                              payee_channel_id="ch_northbridge_gbp", reference="NBU-26004217",
                              created_at=__import__("datetime").datetime(2026, 10, 16)))
    session.commit()
    d, intent = _create(session, ctx)
    assert d.rule_id == "Q-003" and intent.status == "blocked"


def test_single_purchaser_passes_structuring(session, ctx):
    d, _ = _create(session, ctx)
    assert any(c.rule_id == "Q-003" and c.result == "pass" for c in d.checks)


# ------------------------------------------------------------------ SYS-001 freeze
def test_freeze_blocks_money_tools_not_reads(session, ctx):
    state.set_frozen(session, True)
    assert authorize(session, "create_payment_intent", TUITION_ARGS, ctx).rule_id == "SYS-001"
    assert authorize(session, "get_fx_quote", {"currency": "GBP", "amount": 1}, ctx).outcome == "allow"
    state.set_frozen(session, False)
    assert authorize(session, "create_payment_intent", TUITION_ARGS, ctx).allowed


def test_execute_while_frozen_denied(session, ctx):
    _, intent = _create(session, ctx)
    state.set_frozen(session, True)
    d, t = payments.execute(session, intent.id, ctx)
    assert d.rule_id == "SYS-001" and t is None


# ------------------------------------------------------------------ P-001 / P-004
def test_document_tools_require_consent(session, ctx, samples_dir):
    from app import documents, privacy

    with pytest.raises(documents.ConsentRequired):
        ingest(session, samples_dir, "northbridge_invoice_autumn.pdf")
    privacy.grant_consent(session, "p_zhang_min")
    doc = ingest(session, samples_dir, "northbridge_invoice_autumn.pdf")
    assert authorize(session, "verify_payee", {"doc_id": doc.id}, ctx).outcome == "allow"
    session.get(type(doc), doc.id).uploaded_by = "p_li_wei"  # Li Wei has not consented
    session.commit()
    d = authorize(session, "verify_payee", {"doc_id": doc.id}, ctx)
    assert d.outcome == "deny" and d.rule_id == "P-001"


def test_agent_reads_only_payer_quota(session, ctx):
    assert authorize(session, "check_quota", {"person_id": "p_zhang_min"}, ctx).outcome == "allow"
    d = authorize(session, "check_quota", {"person_id": "p_zhang_qiang"}, ctx)
    assert d.outcome == "deny" and d.rule_id == "P-004"


# ------------------------------------------------------------------ T3-001 execution needs approvals
def test_execute_without_approvals_denied(session, ctx):
    _, intent = _create(session, ctx)
    payments.request_approval(session, intent.id, ctx)
    d, t = payments.execute(session, intent.id, ctx)
    assert d.outcome == "deny" and d.rule_id == "T3-001" and t is None


def test_request_approval_moves_to_pending(session, ctx):
    _, intent = _create(session, ctx)
    d = payments.request_approval(session, intent.id, ctx)
    assert d.outcome == "require_approval"
    assert session.get(PaymentIntent, intent.id).status == "pending_approval"


# ------------------------------------------------------------------ misc
def test_verification_email_goes_to_registry_contact(session, ctx):
    d = authorize(session, "draft_verification_email", {"institution_id": "inst_northbridge"}, ctx)
    assert d.data["to"] == "finance@northbridge.ac.uk"
    assert authorize(session, "draft_verification_email", {"institution_id": "inst_fake"}, ctx).rule_id == "T4-002"


def test_every_decision_is_audited(session, ctx):
    before = audit.head_seq(session)
    authorize(session, "approve_payment", {}, ctx)
    authorize(session, "get_family_overview", {}, ctx)
    rows = audit.all_rows(session, after_seq=before)
    assert [r["event"] for r in rows] == ["policy_decision", "policy_decision"]
    assert rows[0]["decision"] == "deny" and rows[1]["decision"] == "allow"


def test_denial_returns_structured_error(session, ctx):
    d = authorize(session, "create_payment_intent", {**TUITION_ARGS, "payer_id": "p_zhang_qiang"}, ctx)
    err = d.error()
    assert err["rule_id"] == "T4-003" and err["error"] == "denied_by_policy" and err["title"]


def test_looks_like_account():
    assert policy.looks_like_account("GB00TEST12345678")
    assert policy.looks_like_account("6222 TEST 0000 1234 5678")
    assert not policy.looks_like_account("NBU-26004217")
    assert not policy.looks_like_account("ch_northbridge_gbp")
    assert not policy.looks_like_account("ALLOWANCE-2026-11")

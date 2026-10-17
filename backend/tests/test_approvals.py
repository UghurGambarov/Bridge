"""Digest, fingerprint, challenge/HMAC, replay, expiry, distinct devices, execution, receipts."""
from decimal import Decimal
from pathlib import Path

import pytest

from app import payments
from app.config import load_rules
from app.models import PaymentIntent, SandboxAccount, Transfer
from app.quota import ledger
from app.sandbox import bank, clock
from app.security import approvals
from app.security.approvals import ApprovalError
from app.security.digest import canonical_json, compute_digest, fingerprint
from tests.conftest import TUITION_ARGS, approve


def _pending(session, ctx, **over):
    _, intent = payments.create_intent(session, {**TUITION_ARGS, **over}, ctx)
    payments.request_approval(session, intent.id, ctx)
    return session.get(PaymentIntent, intent.id)


def test_canonical_json_and_digest_format(session, ctx):
    assert canonical_json({"b": 1, "a": Decimal("13250")}) == '{"a":"13250.00","b":1}'
    intent = _pending(session, ctx)
    assert intent.digest == compute_digest(intent) and len(intent.digest) == 64
    assert intent.fingerprint == fingerprint(intent.digest)
    assert len(intent.fingerprint) == 14 and intent.fingerprint.count("-") == 2


def test_full_t3_flow_executes_with_receipt(session, ctx, devices):
    intent = _pending(session, ctx)
    s1 = approve(session, intent.id, "p_zhang_min", devices)
    assert s1["waiting_for"] == ["p_li_wei"] and not s1["complete"]
    s2 = approve(session, intent.id, "p_li_wei", devices)
    assert s2["complete"]
    assert session.get(PaymentIntent, intent.id).status == "approved"
    d, t = payments.execute(session, intent.id, ctx)
    assert d.outcome == "allow" and t is not None
    assert t.bank_reference.startswith("SBX-20261017-")
    assert t.cny_debit == Decimal("121900.00") and t.fee_cny == Decimal("50.00")
    assert session.get(SandboxAccount, "acct_zhang_min_cny").balance == Decimal("478050.00")
    assert ledger.used_usd(session, "p_zhang_min") == Decimal("42169.01")
    assert ledger.remaining_usd(session, "p_zhang_min") == Decimal("7830.99")
    assert Path(t.receipt_pdf_path).exists() and Path(t.receipt_json_path).exists()
    assert Path(t.receipt_pdf_path).read_bytes()[:5] == b"%PDF-"
    intent = session.get(PaymentIntent, intent.id)
    assert intent.status == "executed"
    assert {"T3-001", "T3-002", "T3-003", "T3-004", "Q-003"} <= {c["rule_id"] for c in intent.rule_checks}
    # Execution is single-use.
    again, t2 = payments.execute(session, intent.id, ctx)
    assert again.outcome == "deny" and t2 is None


def test_receipt_contents(session, ctx, devices):
    import json

    intent = _pending(session, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    approve(session, intent.id, "p_li_wei", devices)
    _, t = payments.execute(session, intent.id, ctx)
    data = json.loads(Path(t.receipt_json_path).read_text(encoding="utf-8"))
    assert data["fingerprint"] == intent.fingerprint
    assert data["payee"]["verified"] is True and data["payee"]["account_masked"] != "GB00TEST12345678"
    assert len(data["approvals"]) == 2 and data["sandbox"] is True
    assert data["audit_seq_range"][0] < data["audit_seq_range"][1]


def test_wrong_mac_rejected(session, ctx, devices):
    intent = _pending(session, ctx)
    dev, _ = devices["p_zhang_min"]
    ch = approvals.issue_challenge(session, intent.id, "p_zhang_min", dev, "p_li_wei")
    with pytest.raises(ApprovalError) as e:
        approvals.submit_approval(session, intent.id, "p_zhang_min", dev, ch["nonce"], "00" * 32, "p_li_wei")
    assert e.value.rule_id == "T3-002"


def test_nonce_reuse_rejected(session, ctx, devices):
    intent = _pending(session, ctx)
    dev, secret = devices["p_zhang_min"]
    ch = approvals.issue_challenge(session, intent.id, "p_zhang_min", dev, "p_li_wei")
    mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
    approvals.submit_approval(session, intent.id, "p_zhang_min", dev, ch["nonce"], mac, "p_li_wei")
    with pytest.raises(ApprovalError) as e:
        approvals.submit_approval(session, intent.id, "p_zhang_min", dev, ch["nonce"], mac, "p_li_wei")
    assert e.value.rule_id == "T3-003"


def test_replay_on_another_intent_rejected(session, ctx, devices):
    a = _pending(session, ctx)
    b = _pending(session, ctx, purpose="accommodation", amount=7800, reference="NBU-26004218")
    dev, secret = devices["p_zhang_min"]
    ch = approvals.issue_challenge(session, a.id, "p_zhang_min", dev, "p_li_wei")
    mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
    with pytest.raises(ApprovalError) as e:
        approvals.submit_approval(session, b.id, "p_zhang_min", dev, ch["nonce"], mac, "p_li_wei")
    assert e.value.rule_id == "T3-003"


def test_expired_challenge_rejected(session, ctx, devices):
    intent = _pending(session, ctx)
    dev, secret = devices["p_zhang_min"]
    ch = approvals.issue_challenge(session, intent.id, "p_zhang_min", dev, "p_li_wei")
    clock.advance(session, minutes=16)
    mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
    with pytest.raises(ApprovalError) as e:
        approvals.submit_approval(session, intent.id, "p_zhang_min", dev, ch["nonce"], mac, "p_li_wei")
    assert e.value.rule_id == "T3-003"


def test_stale_approval_at_execution_denied(session, ctx, devices):
    intent = _pending(session, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    approve(session, intent.id, "p_li_wei", devices)
    clock.advance(session, minutes=16)
    d, t = payments.execute(session, intent.id, ctx)
    assert d.rule_id == "T3-003" and t is None


def test_amount_changed_after_approval_denied(session, ctx, devices):
    intent = _pending(session, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    approve(session, intent.id, "p_li_wei", devices)
    row = session.get(PaymentIntent, intent.id)
    row.amount = Decimal("13250.01")  # tampering with the DB after approval
    session.add(row)
    session.commit()
    d, t = payments.execute(session, intent.id, ctx)
    assert d.rule_id == "T3-002" and t is None


def test_same_device_cannot_sign_for_both(session, ctx, devices):
    intent = _pending(session, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    with pytest.raises(ApprovalError) as e:
        approve(session, intent.id, "p_li_wei", devices, device_override="p_zhang_min")
    assert e.value.rule_id == "T3-004"


def test_same_person_cannot_approve_twice(session, ctx, devices):
    intent = _pending(session, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    with pytest.raises(ApprovalError) as e:
        approve(session, intent.id, "p_zhang_min", devices)
    assert e.value.rule_id == "T3-004"


def test_non_approver_cannot_get_challenge(session, ctx, devices):
    uncle_dev, _ = approvals.enroll_device(session, "p_zhang_qiang", "Uncle's phone")
    intent = _pending(session, ctx)
    with pytest.raises(ApprovalError) as e:
        approvals.issue_challenge(session, intent.id, "p_zhang_qiang", uncle_dev.id, "p_li_wei")
    assert e.value.rule_id == "T3-001"


def test_reject_stops_execution(session, ctx, devices):
    intent = _pending(session, ctx)
    approvals.reject(session, intent.id, "p_li_wei", "Portal shows a different amount", "p_li_wei")
    assert session.get(PaymentIntent, intent.id).status == "rejected"
    d, t = payments.execute(session, intent.id, ctx)
    assert d.outcome == "deny" and t is None


def test_mother_only_configuration(session, ctx, devices, monkeypatch):
    params = load_rules()["T3-001"]["params"]
    monkeypatch.setitem(params, "required_approvers", ["payer"])
    intent = _pending(session, ctx)
    status = approve(session, intent.id, "p_zhang_min", devices)
    assert status["complete"] and status["required"] == ["p_zhang_min"]
    d, t = payments.execute(session, intent.id, ctx)
    assert d.outcome == "allow" and t is not None


def test_device_secret_not_stored(session, devices):
    from app.models import Device

    dev_id, secret = devices["p_zhang_min"]
    stored = session.get(Device, dev_id).secret_hash
    assert secret not in stored and len(stored) == 64


def test_bank_refuses_without_policy_decision(session, ctx):
    intent = _pending(session, ctx)
    with pytest.raises(bank.BankError):
        bank.execute_transfer(session, intent, None)
    from app.security.policy import Decision

    forged = Decision("allow", "execute_payment", intent_id=intent.id, digest="0" * 64)
    with pytest.raises(bank.BankError):
        bank.execute_transfer(session, intent, forged)
    assert session.query(Transfer).count() == 0

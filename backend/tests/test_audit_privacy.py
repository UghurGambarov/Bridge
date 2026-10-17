"""Hash-chained audit log, tamper simulation, masking in the log, PIPL delete-my-data."""
import json

from sqlmodel import select

from app import payments, privacy
from app.models import AuditEntry, Consent, Device, Document, Person
from app.security import audit
from tests.conftest import TUITION_ARGS, approve, ingest


def _activity(session, ctx, devices):
    _, intent = payments.create_intent(session, TUITION_ARGS, ctx)
    payments.request_approval(session, intent.id, ctx)
    approve(session, intent.id, "p_zhang_min", devices)
    approve(session, intent.id, "p_li_wei", devices)
    payments.execute(session, intent.id, ctx)


def test_chain_valid_after_activity(session, ctx, devices):
    _activity(session, ctx, devices)
    v = audit.verify(session)
    assert v["valid"] and v["broken_at_seq"] is None and v["entries"] > 10 and len(v["head_hash"]) == 64


def test_tamper_simulation_detects_and_leaves_real_log_intact(session, ctx, devices):
    _activity(session, ctx, devices)
    before = audit.all_rows(session)
    r = audit.tamper_simulation(session, seq=5)
    assert r["original_valid"] is True and r["copy_valid"] is False and r["broken_at_seq"] == 5
    assert audit.all_rows(session) == before
    assert audit.verify(session)["valid"]


def test_direct_db_tampering_is_detected(session, ctx, devices):
    _activity(session, ctx, devices)
    row = session.get(AuditEntry, 3)
    row.reason = "nothing to see here"
    session.add(row)
    session.commit()
    v = audit.verify(session)
    assert v["valid"] is False and v["broken_at_seq"] == 3


def test_deleting_an_entry_is_detected(session, ctx, devices):
    _activity(session, ctx, devices)
    session.delete(session.get(AuditEntry, 4))
    session.commit()
    assert audit.verify(session)["broken_at_seq"] == 5


def test_payloads_are_masked(session, ctx, consent, samples_dir):
    from app.security.policy import authorize

    authorize(session, "create_payment_intent", {**TUITION_ARGS, "beneficiary_account": "GB00TEST99999999"}, ctx)
    ingest(session, samples_dir, "agency_wechat_message.txt")
    dump = json.dumps(audit.all_rows(session), ensure_ascii=False)
    assert "GB00TEST99999999" not in dump
    assert "6222 TEST 0000 1234 5678" not in dump


def test_delete_my_data(session, ctx, consent, devices, samples_dir):
    ingest(session, samples_dir, "northbridge_invoice_autumn.pdf")
    _activity(session, ctx, devices)
    n_before = audit.head_seq(session)
    summary = privacy.delete_person_data(session, "p_zhang_min")
    assert summary["documents"] == 1 and summary["devices"] == 1
    assert session.exec(select(Document).where(Document.uploaded_by == "p_zhang_min")).first() is None
    assert session.exec(select(Consent).where(Consent.person_id == "p_zhang_min")).first() is None
    assert session.exec(select(Device).where(Device.person_id == "p_zhang_min")).first() is None
    person = session.get(Person, "p_zhang_min")
    assert person.full_name == "[deleted]" and person.deleted_at is not None
    # Masked audit kept, chain still valid, and the deletion itself is logged.
    v = audit.verify(session)
    assert v["valid"] and v["entries"] == n_before + 1
    assert "Zhang Min" not in json.dumps(audit.all_rows(session), ensure_ascii=False)

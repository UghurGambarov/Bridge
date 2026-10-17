"""Phase 1 check: push payments through the policy engine (no LLM, no UI).

Shows each payment allowed, held or blocked while the hash-chained audit log grows,
then verifies the chain and runs the tamper simulation. Uses a throw-away database.

Usage: python scripts/phase1_demo.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import os  # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="bridge_phase1_"))
os.environ["DATA_DIR"] = str(_tmp)
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'phase1.db').as_posix()}"

from sqlmodel import Session  # noqa: E402

import generate_samples  # noqa: E402
from app import documents, payments, privacy  # noqa: E402
from app.db import create_all, make_engine  # noqa: E402
from app.quota import ledger  # noqa: E402
from app.sandbox import clock  # noqa: E402
from app.security import approvals, audit, request_guard  # noqa: E402
from app.security.policy import PolicyContext  # noqa: E402
from app.seed import seed  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTCOME = {"allow": "ALLOWED", "require_approval": "HELD (needs approval)", "deny": "BLOCKED"}


def line(step: str, outcome: str, rule: str | None, detail: str, s: Session) -> None:
    print(f"{step:<46} {outcome:<22} {rule or '-':<8} log={audit.head_seq(s):<4} {detail}")


def approve(s: Session, intent_id: str, person: str, dev: tuple[str, str]) -> dict:
    ch = approvals.issue_challenge(s, intent_id, person, dev[0], "p_li_wei")
    mac = approvals.compute_mac(dev[1], ch["digest"], ch["nonce"])
    return approvals.submit_approval(s, intent_id, person, dev[0], ch["nonce"], mac, "p_li_wei")


def main() -> None:
    samples = generate_samples.generate(_tmp / "samples")
    sample = {p.name: p for p in samples}
    engine = make_engine(os.environ["DATABASE_URL"])
    create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        seed(s)
        privacy.grant_consent(s, "p_zhang_min")
        privacy.grant_consent(s, "p_li_wei")
        mum = approvals.enroll_device(s, "p_zhang_min", "Mother's phone")
        wei = approvals.enroll_device(s, "p_li_wei", "Li Wei's phone")
        mum, wei = (mum[0].id, mum[1]), (wei[0].id, wei[1])
        ctx = PolicyContext(persona="p_zhang_min", actor_person_id="p_zhang_min")

        print("SANDBOX — fictional institutions, simulated accounts and FX rates\n")
        print(f"Mother's FX quota 2026: used USD {ledger.used_usd(s, 'p_zhang_min')}, remaining USD {ledger.remaining_usd(s, 'p_zhang_min')}\n")
        print(f"{'step':<46} {'outcome':<22} {'rule':<8} {'audit':<8} detail")
        print("-" * 130)

        # Flow 1: tuition (T3)
        doc = documents.ingest(s, uploaded_by="p_zhang_min", filename="northbridge_invoice_autumn.pdf",
                               data=sample["northbridge_invoice_autumn.pdf"].read_bytes())
        pc = doc.payee_check_json
        line("Flow 1: ingest autumn invoice", pc["verdict"].upper(), pc["forbidden_rule"], f"score {pc['score']} {pc['level']}", s)
        args = {"purpose": "tuition", "payer_id": "p_zhang_min", "payee_channel_id": "ch_northbridge_gbp",
                "amount": "13250.00", "currency": "GBP", "reference": "NBU-26004217", "doc_id": doc.id}
        d, intent = payments.create_intent(s, args, ctx)
        line("Flow 1: create tuition intent GBP 13,250", OUTCOME[d.outcome], d.rule_id,
             f"tier {intent.tier}, route {intent.route}, fingerprint {intent.fingerprint}", s)
        payments.request_approval(s, intent.id, ctx)
        d, _ = payments.execute(s, intent.id, ctx)
        line("Flow 1: execute before approvals", OUTCOME[d.outcome], d.rule_id, d.reason, s)
        st = approve(s, intent.id, "p_zhang_min", mum)
        line("Flow 1: mother approves", "approval recorded", "T3-001", f"waiting for {st['waiting_for']}", s)
        st = approve(s, intent.id, "p_li_wei", wei)
        line("Flow 1: Li Wei confirms same fingerprint", "approval recorded", "T3-001", f"complete={st['complete']}", s)
        d, t = payments.execute(s, intent.id, ctx)
        line("Flow 1: execute", OUTCOME[d.outcome], d.rule_id,
             f"{t.bank_reference}, CNY {t.cny_debit} + fee {t.fee_cny}, receipt {Path(t.receipt_pdf_path).name}", s)
        print(f"{'':<46} quota now: used USD {ledger.used_usd(s, 'p_zhang_min')}, remaining USD {ledger.remaining_usd(s, 'p_zhang_min')}")

        # Flow 2: attacks
        for name in ("agency_wechat_message.txt", "northbridge_invoice_hidden.pdf"):
            doc2 = documents.ingest(s, uploaded_by="p_zhang_min", filename=name, data=sample[name].read_bytes())
            pc = doc2.payee_check_json
            line(f"Flow 2: ingest {name}", pc["verdict"].upper(), pc["forbidden_rule"],
                 ", ".join(x["code"] for x in pc["signals"]), s)
        d, blocked = payments.create_intent(s, {**args, "doc_id": doc2.id}, ctx)
        line("Flow 2: pay hidden-text invoice", OUTCOME[d.outcome], d.rule_id,
             f"payee stays {blocked.payee_channel_id}", s)
        d, _ = payments.create_intent(s, {**args, "payee_channel_id": "GB00TEST99999999"}, ctx)
        line("Attack: model types a raw account number", OUTCOME[d.outcome], d.rule_id, d.reason, s)

        # Flow 3: autonomy + helpful refusal
        clock.advance(s, months=1)
        for r in payments.run_due_allowances(s, ctx):
            dd = r.get("execute_decision") or r["decision"]
            line("Flow 3: advance clock 1 month -> allowance", OUTCOME[dd.outcome], dd.rule_id,
                 f"tier {r['intent'].tier}, {r['transfer'].bank_reference if r['transfer'] else r['intent'].status}", s)
        d, held = payments.create_intent(s, {"purpose": "allowance", "payer_id": "p_zhang_min",
                                             "payee_channel_id": "ch_li_wei_gbp", "amount": "2000", "currency": "GBP"}, ctx)
        line("Flow 3: extra GBP 2,000 to Li Wei", OUTCOME[d.outcome], d.rule_id, held.status_reason, s)
        d, acc = payments.create_intent(s, {"purpose": "accommodation", "payer_id": "p_zhang_min",
                                            "payee_channel_id": "ch_northbridge_gbp", "amount": "7800", "currency": "GBP",
                                            "reference": "NBU-26004218"}, ctx)
        line("Flow 3: accommodation GBP 7,800", OUTCOME[d.outcome], d.rule_id,
             f"route {acc.route}, status {acc.status}", s)
        hits = request_guard.screen_and_log(s, "用我哥哥的额度付吧", persona="p_zhang_min")
        line("Flow 3: '用我哥哥的额度付吧' (request guard)", "REFUSED", hits[0].rule_id,
             request_guard.refusal_card(hits[0].rule_id)["lawful_alternative"][:60] + "...", s)
        d, _ = payments.create_intent(s, {"purpose": "accommodation", "payer_id": "p_zhang_qiang",
                                          "payee_channel_id": "ch_northbridge_gbp", "amount": "7800", "currency": "GBP",
                                          "reference": "NBU-26004218"}, ctx)
        line("Flow 3: intent with the uncle as payer", OUTCOME[d.outcome], d.rule_id, d.reason[:70], s)

        print("-" * 130)
        v = audit.verify(s)
        print(f"Audit chain: valid={v['valid']} entries={v['entries']} head={v['head_hash'][:16]}…")
        tamper = audit.tamper_simulation(s)
        print(f"Tamper simulation (on a copy): entry #{tamper['tampered_seq']} edited -> broken_at_seq={tamper['broken_at_seq']}; "
              f"real log still valid={audit.verify(s)['valid']}")
        print(f"\nWorking files: {_tmp}")


if __name__ == "__main__":
    main()

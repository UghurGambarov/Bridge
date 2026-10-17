"""Receipt PDFs (+ JSON twin for the evidence pack). Watermarked "SANDBOX — no real money moved"."""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlmodel import Session

from ..config import get_settings
from ..models import Institution, PaymentChannel, PaymentIntent, Person, Transfer
from ..security import approvals
from ..security.masking import mask_name
from . import fx


def receipt_data(session: Session, transfer: Transfer, intent: PaymentIntent, audit_range: tuple[int, int],
                 student_id: str) -> dict:
    payer = session.get(Person, intent.payer_id)
    ch = session.get(PaymentChannel, intent.payee_channel_id)
    inst = session.get(Institution, ch.institution_id) if ch.institution_id else None
    appr = []
    for pid in approvals.required_approvers(intent, student_id) if intent.tier == "T3" else []:
        a = approvals.latest_used(session, intent.id, pid)
        person = session.get(Person, pid)
        if a:
            appr.append({"person_id": pid, "name": mask_name(person.full_name) if person else pid,
                         "role": person.role if person else "", "approved_at": a.used_at.isoformat(), "device_id": a.device_id})
    return {
        "sandbox": True,
        "disclaimer": "SANDBOX — no real money moved. Fictional institutions, simulated accounts and FX rates.",
        "transfer_id": transfer.id,
        "bank_reference": transfer.bank_reference,
        "executed_at": transfer.executed_at.isoformat(),
        "intent_id": intent.id,
        "purpose": intent.purpose,
        "tier": intent.tier,
        "route": intent.route,
        "payer": {"person_id": intent.payer_id, "name": mask_name(payer.full_name) if payer else intent.payer_id},
        "payee": {"channel_id": ch.id, "beneficiary_name": ch.beneficiary_name, "account_masked": ch.account_masked,
                  "swift": ch.swift, "bank_name": ch.bank_name, "verified": True, "verified_source": ch.verified_source,
                  "institution": inst.name if inst else None},
        "amount": f"{transfer.amount:.2f}",
        "currency": transfer.currency,
        "fx_rate_cny": fx.rate_str(transfer.fx_rate),
        "fx_label": "simulated",
        "cny_debit": f"{transfer.cny_debit:.2f}",
        "fee_cny": f"{transfer.fee_cny:.2f}",
        "total_cny": f"{transfer.cny_debit + transfer.fee_cny:.2f}",
        "usd_equivalent": f"{transfer.usd_equivalent:.2f}",
        "reference": intent.reference,
        "fingerprint": intent.fingerprint,
        "digest": intent.digest,
        "approvals": appr,
        "audit_seq_range": list(audit_range),
    }


def _watermark(c: canvas.Canvas, text: str) -> None:
    c.saveState()
    c.setFillColor(colors.Color(0.80, 0.80, 0.80))
    c.setFont("Helvetica-Bold", 40)
    c.translate(A4[0] / 2, A4[1] / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def write_receipt(data: dict, out_dir: Path | None = None) -> tuple[str, str]:
    out_dir = out_dir or get_settings().receipts_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{data['transfer_id']}.pdf"
    json_path = out_dir / f"{data['transfer_id']}.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    c = canvas.Canvas(str(pdf_path), pagesize=A4, invariant=1)
    c.setTitle(f"Bridge sandbox receipt {data['bank_reference']}")
    _watermark(c, "SANDBOX — no real money moved")
    w, h = A4
    y = h - 25 * mm
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, y, "Bridge — Payment receipt")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(0.6, 0.1, 0.1))
    c.drawString(20 * mm, y - 6 * mm, data["disclaimer"])
    c.setFillColor(colors.black)
    y -= 18 * mm

    def row(label: str, value: str, bold: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, y, label)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        c.drawString(70 * mm, y, value)
        y -= 6.5 * mm

    p = data["payee"]
    row("Bank reference", data["bank_reference"], True)
    row("Executed at", data["executed_at"].replace("T", " ") + " (Beijing, sandbox clock)")
    row("Payer", f"{data['payer']['name']} ({data['payer']['person_id']})")
    row("Payee", f"{p['beneficiary_name']}  [VERIFIED - registry]", True)
    row("Payee account", f"{p['account_masked']}   SWIFT {p['swift']}")
    row("Payee bank", p["bank_name"])
    row("Purpose / route", f"{data['purpose']} / {data['route']} / tier {data['tier']}")
    row("Reference", data.get("reference") or "-")
    y -= 3 * mm
    row("Amount", f"{data['currency']} {float(data['amount']):,.2f}", True)
    row("FX rate (simulated)", f"1 {data['currency']} = CNY {data['fx_rate_cny']}")
    row("CNY debit", f"CNY {float(data['cny_debit']):,.2f}")
    row("Transfer fee", f"CNY {float(data['fee_cny']):,.2f}")
    row("Total debited", f"CNY {float(data['total_cny']):,.2f}", True)
    row("USD equivalent (quota)", f"USD {float(data['usd_equivalent']):,.2f}")
    y -= 3 * mm
    row("Transaction fingerprint", data["fingerprint"], True)
    c.setFont("Courier", 7)
    c.drawString(20 * mm, y, f"digest sha256: {data['digest']}")
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Approvals")
    y -= 6 * mm
    if data["approvals"]:
        for a in data["approvals"]:
            row(f"  {a['role']}", f"{a['name']} at {a['approved_at'].replace('T', ' ')} (device {a['device_id']})")
    else:
        row("  (none)", "T2 autonomous payment within preset limits")
    y -= 3 * mm
    row("Audit log entries", f"#{data['audit_seq_range'][0]} - #{data['audit_seq_range'][1]} (hash-chained)")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, 15 * mm, "SANDBOX SAMPLE - generated by Bridge. Verify the audit chain in the Evidence Center.")
    c.showPage()
    c.save()
    return str(pdf_path), str(json_path)

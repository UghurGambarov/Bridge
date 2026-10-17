"""Quarantined extraction (SPEC §9.1 step 3).

The extractor sees only VISIBLE text and has no tools. Its output is strict JSON validated by
Pydantic (extra fields forbidden). This module holds the schema and the deterministic regex
parser, which is the fallback for the LLM extractor and the only extractor in mock mode.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: str = "unknown"  # invoice | message | email | letter | notice | unknown
    issuer_name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_domain: Optional[str] = None
    beneficiary_name: Optional[str] = None
    beneficiary_account: Optional[str] = None
    bank_name: Optional[str] = None
    swift: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    due_date: Optional[str] = None  # ISO date
    reference: Optional[str] = None
    student_name: Optional[str] = None
    mentions_discount: bool = False
    mentions_urgency: bool = False
    mentions_agency_payment: bool = False
    mentions_crypto: bool = False
    summary_en: str = Field(default="", max_length=300)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v


_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "CNY", "HK$": "HKD", "US$": "USD"}
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def _field(text: str, labels: list[str]) -> Optional[str]:
    for label in labels:
        m = re.search(rf"(?im)^\s*(?:{label})\s*[:：]\s*(.+?)\s*$", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def parse_amount(raw: str) -> tuple[Optional[Decimal], Optional[str]]:
    raw = raw.strip()
    cur = None
    m = re.search(r"\b(GBP|USD|HKD|EUR|CNY|RMB)\b", raw, re.I)
    if m:
        cur = m.group(1).upper().replace("RMB", "CNY")
    else:
        for sym in sorted(_SYMBOLS, key=len, reverse=True):
            if sym in raw:
                cur = _SYMBOLS[sym]
                break
    num = re.search(r"\d[\d,]*(?:\.\d{1,2})?", raw)
    if not num:
        return None, cur
    try:
        return Decimal(num.group(0).replace(",", "")), cur
    except InvalidOperation:
        return None, cur


def parse_date(raw: str) -> Optional[str]:
    raw = raw.strip()
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
    if m and m.group(2).lower() in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m and m.group(1).lower() in _MONTHS:
        return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    return None


_DISCOUNT = re.compile(r"\d+\s*%\s*off|discount|折扣|八折|优惠|打折", re.I)
_URGENCY = re.compile(r"within 24 hours|urgent|immediately|today only|lose (?:the|your) place|final notice|24小时|尽快|立即|马上|名额", re.I)
_AGENCY = re.compile(r"代缴|agency|代付|代理|on (?:your|the family'?s) behalf", re.I)
_CRYPTO = re.compile(r"usdt|stablecoin|bitcoin|crypto|稳定币|泰达币|虚拟货币|\b0x[a-f0-9]{8,}", re.I)


def regex_extract(text: str) -> ExtractedDocument:
    """Deterministic parser for labelled invoices, letters and chat messages."""
    t = text or ""
    lower = t.lower()
    sender = _field(t, ["From", "Sender", "发件人"]) or ""
    em = re.search(r"[\w.+-]+@((?:[\w-]+\.)+[\w-]+)", sender or t, re.UNICODE)
    sender_email = em.group(0) if em else None
    amount_raw = _field(t, ["Amount due", "Total due", "Amount", "金额", "应付金额", "学费"])
    amount, currency = parse_amount(amount_raw) if amount_raw else (None, None)
    due_raw = _field(t, ["Due date", "Payment due", "Due", "截止日期", "付款期限"])
    account = _field(t, ["Account(?: number)?", "IBAN", "Beneficiary account", "账户", "账号", "收款账号", "卡号"])
    if account:
        account = re.split(r"\s{2,}|\(|（", account)[0].strip()
    if "invoice" in lower or "发票" in t or "账单" in t:
        doc_type = "invoice"
    elif sender_email and ("subject:" in lower):
        doc_type = "email"
    elif "letter" in lower or "offer" in lower and "admission" in lower:
        doc_type = "letter"
    elif "notice" in lower or "通知" in t:
        doc_type = "notice"
    else:
        doc_type = "message"
    issuer = _field(t, ["Issuer", "Issued by", "Institution", "University"])
    if not issuer:
        first = next((ln.strip() for ln in t.splitlines() if ln.strip() and "SANDBOX" not in ln.upper()), "")
        issuer = first[:80] or None
    fields = ExtractedDocument(
        doc_type=doc_type,
        issuer_name=issuer,
        sender_email=sender_email,
        sender_domain=em.group(1).lower() if em else None,
        beneficiary_name=_field(t, ["Beneficiary(?: name)?", "Account name", "Payee", "户名", "收款人", "收款方"]),
        beneficiary_account=account,
        bank_name=_field(t, ["Bank(?: name)?", "银行", "开户行"]),
        swift=_field(t, ["SWIFT(?:/BIC)?", "BIC"]),
        amount=amount,
        currency=currency,
        due_date=parse_date(due_raw) if due_raw else None,
        reference=(_field(t, ["Reference", "Payment reference", "Invoice (?:no|number)\\.?", "参考号"]) or None),
        student_name=_field(t, ["Student(?: name)?", "Student", "学生"]),
        mentions_discount=bool(_DISCOUNT.search(t)),
        mentions_urgency=bool(_URGENCY.search(t)),
        mentions_agency_payment=bool(_AGENCY.search(t)),
        mentions_crypto=bool(_CRYPTO.search(t)),
    )
    if fields.reference:
        m = re.search(r"[A-Z]{2,5}-\d{4,10}", fields.reference)
        fields.reference = m.group(0) if m else fields.reference.split()[0]
    bits = [fields.doc_type]
    if fields.issuer_name:
        bits.append(f"from {fields.issuer_name}")
    if fields.amount is not None:
        bits.append(f"amount {fields.currency or ''} {fields.amount:,.2f}".strip())
    if fields.due_date:
        bits.append(f"due {fields.due_date}")
    fields.summary_en = (" ".join(bits))[:300]
    return fields


def days_until(due_date: Optional[str], today: datetime) -> Optional[int]:
    if not due_date:
        return None
    return (date.fromisoformat(due_date) - today.date()).days

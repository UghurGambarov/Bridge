"""Domain model (SQLModel on SQLite). See SPEC §6.

Money is stored as exact decimal text (never float). Datetimes are naive Beijing time
taken from the sandbox clock.
"""
from __future__ import annotations

from pydantic import NaiveDatetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Column, String
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


class DecimalText(TypeDecorator):
    """Stores Decimal as text with a fixed number of places (exact, portable)."""

    impl = String(40)
    cache_ok = True

    def __init__(self, places: int = 2) -> None:
        super().__init__()
        self.places = places

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        q = Decimal(1).scaleb(-self.places)
        return str(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))

    def process_result_value(self, value: Any, dialect: Any) -> Optional[Decimal]:
        return None if value is None else Decimal(value)


def money(nullable: bool = False) -> Any:
    return Field(default=None if nullable else Decimal("0"), sa_column=Column(DecimalText(2), nullable=nullable))


def rate(nullable: bool = True) -> Any:
    return Field(default=None, sa_column=Column(DecimalText(6), nullable=nullable))


def json_list() -> Any:
    return Field(default_factory=list, sa_column=Column(JSON))


def json_dict() -> Any:
    return Field(default_factory=dict, sa_column=Column(JSON))


# ------------------------------------------------------------------ people and consent
class Person(SQLModel, table=True):
    id: str = Field(primary_key=True)
    full_name: str
    name_zh: str = ""
    role: str  # parent | student | relative
    relationship_to_student: str = ""
    passport_name: str = ""
    city: str = ""
    deleted_at: Optional[NaiveDatetime] = None


class Device(SQLModel, table=True):
    id: str = Field(primary_key=True)
    person_id: str = Field(index=True)
    label: str
    # HMAC key = SHA-256(device_secret). The raw secret is returned once and never stored.
    secret_hash: str
    enrolled_at: NaiveDatetime
    revoked_at: Optional[NaiveDatetime] = None


class Consent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: str = Field(index=True)
    purposes: list = json_list()
    granted_at: NaiveDatetime
    revoked_at: Optional[NaiveDatetime] = None


# ------------------------------------------------------------------ registry
class Institution(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    country: str
    official_domains: list = json_list()
    official_contact_email: str = ""
    reference_regex: Optional[str] = None
    fee_ranges: dict = json_dict()
    fees: dict = json_dict()
    currency: str
    deadlines: list = json_list()


class PaymentChannel(SQLModel, table=True):
    id: str = Field(primary_key=True)
    type: str  # institution | same_name_personal
    institution_id: Optional[str] = None
    owner_person_id: Optional[str] = None
    beneficiary_name: str
    bank_name: str
    account_full: str
    account_masked: str
    swift: str
    currency: str
    verified_source: str
    verified_at: NaiveDatetime


# ------------------------------------------------------------------ ledger and documents
class FxLedgerEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: str = Field(index=True)
    year: int = Field(index=True)
    usd_amount: Decimal = money()
    cny_amount: Decimal = money()
    currency: str
    foreign_amount: Decimal = money()
    purpose: str
    payee_channel_id: Optional[str] = None
    reference: Optional[str] = None
    intent_id: Optional[str] = None
    created_at: NaiveDatetime


class Document(SQLModel, table=True):
    id: str = Field(primary_key=True)
    uploaded_by: str = Field(index=True)
    kind: str  # pdf | text | email
    filename: str = ""
    sha256: str
    extracted_json: dict = json_dict()
    findings_json: dict = json_dict()
    payee_check_json: dict = json_dict()
    summary_zh: Optional[str] = None
    raw_retained: bool = False
    created_at: NaiveDatetime


# ------------------------------------------------------------------ payments
INTENT_STATUSES = (
    "draft", "awaiting_documents", "pending_approval", "approved", "executed",
    "held", "blocked", "refused", "expired", "rejected",
)


class PaymentIntent(SQLModel, table=True):
    id: str = Field(primary_key=True)
    purpose: str  # tuition | accommodation | deposit | allowance
    payer_id: str = Field(index=True)
    payee_channel_id: str
    amount: Decimal = money()
    currency: str
    usd_equivalent: Decimal = money()
    cny_equivalent: Decimal = money()
    fx_rate: Optional[Decimal] = rate()
    fee_cny: Decimal = money()
    reference: Optional[str] = None
    due_date: Optional[str] = None
    route: str = "within_quota"  # within_quota | above_quota_documented
    tier: str = "T3"
    risk_score: int = 0
    risk_level: str = "LOW"
    risk_signals: list = json_list()
    rule_checks: list = json_list()
    status: str = "draft"
    status_reason: str = ""
    digest: str = ""
    fingerprint: str = ""
    doc_id: Optional[str] = None
    bank_verified_at: Optional[NaiveDatetime] = None
    first_audit_seq: Optional[int] = None
    created_by: str = "agent"
    created_at: NaiveDatetime
    updated_at: Optional[NaiveDatetime] = None


class Approval(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    intent_id: str = Field(index=True)
    person_id: str
    device_id: str
    digest: str
    nonce: str = Field(index=True, unique=True)
    mac: Optional[str] = None
    issued_at: NaiveDatetime
    expires_at: NaiveDatetime
    used_at: Optional[NaiveDatetime] = None


class AllowanceSchedule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: str
    payer_id: str
    payee_channel_id: str
    amount: Decimal = money()
    currency: str
    day_of_month: int = 1
    active: bool = True
    last_run_period: Optional[str] = None  # "YYYY-MM"


# ------------------------------------------------------------------ sandbox bank and audit
class SandboxAccount(SQLModel, table=True):
    id: str = Field(primary_key=True)
    owner_person_id: str = Field(index=True)
    currency: str
    balance: Decimal = money()


class Transfer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    intent_id: str = Field(index=True)
    from_account_id: str
    payee_channel_id: str
    amount: Decimal = money()
    currency: str
    fx_rate: Optional[Decimal] = rate()
    cny_debit: Decimal = money()
    fee_cny: Decimal = money()
    usd_equivalent: Decimal = money()
    status: str = "executed"
    bank_reference: str
    executed_at: NaiveDatetime
    receipt_pdf_path: Optional[str] = None
    receipt_json_path: Optional[str] = None


class AuditEntry(SQLModel, table=True):
    seq: int = Field(primary_key=True)
    ts: str
    actor: str  # user | agent | policy | system | approver
    persona: Optional[str] = None
    event: str
    rule_id: Optional[str] = None
    decision: Optional[str] = None
    reason: str = ""
    payload_masked: dict = json_dict()
    prev_hash: str
    hash: str = Field(sa_column=Column(String(64), nullable=False))


class SystemState(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str

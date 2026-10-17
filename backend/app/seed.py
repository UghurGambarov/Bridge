"""Fictional seed data (SPEC §7). Every person, institution and account is invented."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from . import registry, state
from .db import create_all, drop_all
from .models import AllowanceSchedule, FxLedgerEntry, PaymentChannel, Person, SandboxAccount
from .sandbox import clock
from .security import audit
from .security.masking import mask_account

PAYER_ID = "p_zhang_min"
STUDENT_ID = "p_li_wei"
UNCLE_ID = "p_zhang_qiang"
STUDENT_CHANNEL_ID = "ch_li_wei_gbp"
NORTHBRIDGE_CHANNEL_ID = "ch_northbridge_gbp"


def seed(session: Session) -> None:
    if session.get(Person, PAYER_ID) is not None:
        return
    clock.init(session)
    state.set_frozen(session, False)
    registry.load_into_db(session)

    session.add_all([
        Person(id=PAYER_ID, full_name="Zhang Min", name_zh="张敏", role="parent", relationship_to_student="mother",
               passport_name="ZHANG MIN", city="Hangzhou"),
        Person(id=STUDENT_ID, full_name="Li Wei", name_zh="李伟", role="student", relationship_to_student="self",
               passport_name="LI WEI", city="Northbridge (UK)"),
        Person(id=UNCLE_ID, full_name="Zhang Qiang", name_zh="张强", role="relative", relationship_to_student="uncle",
               passport_name="ZHANG QIANG", city="Hangzhou"),
    ])
    session.add(PaymentChannel(
        id=STUDENT_CHANNEL_ID, type="same_name_personal", owner_person_id=STUDENT_ID, beneficiary_name="LI WEI",
        bank_name="Sandbox Bank plc (fictional)", account_full="GB00TEST87654321",
        account_masked=mask_account("GB00TEST87654321"), swift="TESTGB2L", currency="GBP",
        verified_source="Same-name account: holder name matches passport (sandbox bank check)",
        verified_at=datetime(2026, 9, 5, 9, 0),
    ))
    session.add(SandboxAccount(id="acct_zhang_min_cny", owner_person_id=PAYER_ID, currency="CNY",
                               balance=Decimal("600000.00")))
    # Quota already used in 2026: USD 25,000 (deposit + pre-sessional course).
    session.add_all([
        FxLedgerEntry(person_id=PAYER_ID, year=2026, usd_amount=Decimal("12000.00"), cny_amount=Decimal("85200.00"),
                      currency="GBP", foreign_amount=Decimal("9260.87"), purpose="deposit",
                      payee_channel_id=NORTHBRIDGE_CHANNEL_ID, reference="NBU-26000981",
                      created_at=datetime(2026, 3, 12, 10, 0)),
        FxLedgerEntry(person_id=PAYER_ID, year=2026, usd_amount=Decimal("13000.00"), cny_amount=Decimal("92300.00"),
                      currency="GBP", foreign_amount=Decimal("10032.61"), purpose="pre-sessional course",
                      payee_channel_id=NORTHBRIDGE_CHANNEL_ID, reference="NBU-26001544",
                      created_at=datetime(2026, 7, 2, 10, 0)),
    ])
    session.add(AllowanceSchedule(student_id=STUDENT_ID, payer_id=PAYER_ID, payee_channel_id=STUDENT_CHANNEL_ID,
                                  amount=Decimal("1200.00"), currency="GBP", day_of_month=1, active=True,
                                  last_run_period="2026-10"))
    session.commit()
    audit.append(session, actor="system", event="sandbox_seeded",
                 reason="Fictional seed data loaded (SANDBOX — fictional institutions, simulated accounts and FX rates).",
                 payload={"persons": [PAYER_ID, STUDENT_ID, UNCLE_ID], "quota_used_usd": "25000.00"})


def reset(engine: Engine) -> None:
    drop_all(engine)
    create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        seed(s)


def persons(session: Session) -> list[Person]:
    return list(session.exec(select(Person)))

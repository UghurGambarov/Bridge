"""Sandbox bank: CNY accounts, FX purchase and outbound transfers. No real money, no real bank.

execute_transfer() refuses to run without an `allow` Decision from the policy engine for this
exact intent and digest (defence in depth behind the choke point).
"""
from __future__ import annotations

import secrets
from decimal import Decimal

from sqlmodel import Session, select

from ..models import PaymentIntent, SandboxAccount, Transfer
from ..quota import ledger
from ..security.digest import compute_digest
from . import clock, fx


class BankError(Exception):
    pass


def account_for(session: Session, person_id: str, currency: str = "CNY") -> SandboxAccount:
    acct = session.exec(select(SandboxAccount).where(
        SandboxAccount.owner_person_id == person_id, SandboxAccount.currency == currency)).first()
    if acct is None:
        raise BankError(f"No sandbox {currency} account for {person_id}.")
    return acct


def _bank_reference(session: Session) -> str:
    day = clock.now(session).strftime("%Y%m%d")
    n = len([t for t in session.exec(select(Transfer)) if t.bank_reference.startswith(f"SBX-{day}-")]) + 1
    return f"SBX-{day}-{n:04d}"


def execute_transfer(session: Session, intent: PaymentIntent, decision) -> Transfer:
    if (decision is None or decision.outcome != "allow" or decision.tool != "execute_payment"
            or decision.intent_id != intent.id or decision.digest != compute_digest(intent)):
        raise BankError("Refused: no valid policy authorization for this intent and digest.")
    q = fx.quote(intent.currency, intent.amount)
    acct = account_for(session, intent.payer_id)
    if acct.balance < q.total_cny_debit:
        raise BankError("Insufficient sandbox balance.")
    acct.balance = fx.q2(Decimal(acct.balance) - q.total_cny_debit)
    now = clock.now(session)
    t = Transfer(
        id="tr_" + secrets.token_hex(5), intent_id=intent.id, from_account_id=acct.id,
        payee_channel_id=intent.payee_channel_id, amount=intent.amount, currency=intent.currency,
        fx_rate=q.rate_cny, cny_debit=q.cny_amount, fee_cny=q.fee_cny, usd_equivalent=q.usd_equivalent,
        status="executed", bank_reference=_bank_reference(session), executed_at=now,
    )
    session.add(acct)
    session.add(t)
    ledger.record(session, person_id=intent.payer_id, usd_amount=q.usd_equivalent, cny_amount=q.cny_amount,
                  currency=intent.currency, foreign_amount=intent.amount, purpose=intent.purpose,
                  payee_channel_id=intent.payee_channel_id, reference=intent.reference, intent_id=intent.id)
    return t

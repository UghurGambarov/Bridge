"""Simulated FX rates (static, labelled "simulated"). All maths in Decimal, half-up to cents."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

from ..config import fx_rates, transfer_fee_cny

CENT = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


class UnsupportedCurrency(ValueError):
    pass


def rate_cny(currency: str) -> Decimal:
    rates = fx_rates()
    cur = currency.upper()
    if cur not in rates:
        raise UnsupportedCurrency(currency)
    return rates[cur]


def to_cny(currency: str, amount: Decimal) -> Decimal:
    return q2(Decimal(amount) * rate_cny(currency))


def to_usd(currency: str, amount: Decimal) -> Decimal:
    """USD equivalent via CNY (the quota is counted in USD)."""
    if currency.upper() == "USD":
        return q2(Decimal(amount))
    return q2(to_cny(currency, amount) / rate_cny("USD"))


@dataclass
class FxQuote:
    currency: str
    amount: Decimal
    rate_cny: Decimal
    cny_amount: Decimal
    usd_cny_rate: Decimal
    usd_equivalent: Decimal
    fee_cny: Decimal
    total_cny_debit: Decimal
    label: str = "simulated"

    def card(self) -> dict:
        d = asdict(self)
        return {k: (f"{v}" if isinstance(v, Decimal) else v) for k, v in d.items()}


def quote(currency: str, amount: Decimal) -> FxQuote:
    amount = q2(Decimal(str(amount)))
    if amount <= 0:
        raise ValueError("amount must be positive")
    cny = to_cny(currency, amount)
    fee = transfer_fee_cny()
    return FxQuote(
        currency=currency.upper(),
        amount=amount,
        rate_cny=rate_cny(currency),
        cny_amount=cny,
        usd_cny_rate=rate_cny("USD"),
        usd_equivalent=to_usd(currency, amount),
        fee_cny=fee,
        total_cny_debit=q2(cny + fee),
    )

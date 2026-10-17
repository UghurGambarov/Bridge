"""Quota planning (SPEC §9.4): the payer's personal quota only, never anyone else's."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session

from ..config import rule_param
from ..sandbox import fx
from . import ledger

WITHIN = "within_quota"
ABOVE = "above_quota_documented"


@dataclass
class QuotaPlan:
    payer_id: str
    route: str
    usd_equivalent: Decimal
    cny_equivalent: Decimal
    fx_rate: Decimal
    used_before_usd: Decimal
    remaining_before_usd: Decimal
    remaining_after_usd: Decimal
    checklist: list[str] = field(default_factory=list)

    def card(self) -> dict:
        return {
            "payer_id": self.payer_id,
            "route": self.route,
            "usd_equivalent": f"{self.usd_equivalent:.2f}",
            "cny_equivalent": f"{self.cny_equivalent:.2f}",
            "fx_rate": f"{self.fx_rate}",
            "used_before_usd": f"{self.used_before_usd:.2f}",
            "remaining_before_usd": f"{self.remaining_before_usd:.2f}",
            "remaining_after_usd": f"{self.remaining_after_usd:.2f}",
            "checklist": self.checklist,
        }


def documented_route_checklist() -> list[str]:
    return list(rule_param("Q-002", "documents", []))


def plan(session: Session, payer_id: str, currency: str, amount: Decimal) -> QuotaPlan:
    usd = fx.to_usd(currency, amount)
    used = ledger.used_usd(session, payer_id)
    remaining = ledger.remaining_usd(session, payer_id)
    if usd <= remaining:
        route, checklist, after = WITHIN, ["Payer's ID card (ID only — within quota)"], fx.q2(remaining - usd)
    else:
        # Q-002: the whole amount goes through the documented route. It is never split.
        route, checklist, after = ABOVE, documented_route_checklist(), remaining
    return QuotaPlan(
        payer_id=payer_id, route=route, usd_equivalent=usd, cny_equivalent=fx.to_cny(currency, amount),
        fx_rate=fx.rate_cny(currency), used_before_usd=used, remaining_before_usd=remaining,
        remaining_after_usd=after, checklist=checklist,
    )

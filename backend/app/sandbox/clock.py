"""Sandbox clock.

now = configured start + (real time elapsed since seeding) + offset.
The start is fixed in config/app.yaml, so dates in tests and demos are deterministic;
"Advance clock 1 month" adds to the offset.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from sqlmodel import Session

from .. import state
from ..config import app_config


def _start() -> datetime:
    return datetime.fromisoformat(app_config()["sandbox"]["start_datetime"])


def _real_now() -> datetime:
    return datetime.now().replace(microsecond=0)


def init(session: Session) -> None:
    state.put(session, "clock_anchor_real", _real_now().isoformat())
    state.put(session, "clock_offset_seconds", "0")


def now(session: Session) -> datetime:
    anchor_s = state.get(session, "clock_anchor_real")
    offset = float(state.get(session, "clock_offset_seconds", "0") or 0)
    elapsed = (_real_now() - datetime.fromisoformat(anchor_s)) if anchor_s else timedelta(0)
    return (_start() + elapsed + timedelta(seconds=offset)).replace(microsecond=0)


def add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year, month = dt.year + m // 12, m % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def advance(session: Session, *, months: int = 0, days: int = 0, minutes: int = 0) -> datetime:
    current = now(session)
    target = add_months(current, months) + timedelta(days=days, minutes=minutes)
    offset = float(state.get(session, "clock_offset_seconds", "0") or 0)
    state.put(session, "clock_offset_seconds", str(offset + (target - current).total_seconds()))
    return now(session)

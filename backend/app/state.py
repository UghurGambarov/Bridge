"""Small key/value system state: freeze switch (SYS-001) and sandbox clock offset."""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from .models import SystemState


def get(session: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    row = session.get(SystemState, key)
    return row.value if row else default


def put(session: Session, key: str, value: str) -> None:
    row = session.get(SystemState, key)
    if row:
        row.value = value
    else:
        session.add(SystemState(key=key, value=value))
    session.commit()


def is_frozen(session: Session) -> bool:
    return get(session, "frozen", "0") == "1"


def set_frozen(session: Session, frozen: bool) -> None:
    put(session, "frozen", "1" if frozen else "0")

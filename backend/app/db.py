"""Database engine and sessions.

Every service function takes an explicit Session, so the scenario suite can run each case
on its own isolated temp database without touching the demo state.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (registers tables)
from .config import get_settings

_engine: Optional[Engine] = None


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        SQLModel.metadata.create_all(_engine)
    return _engine


def set_engine(engine: Engine) -> None:
    global _engine
    _engine = engine


def create_all(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    SQLModel.metadata.drop_all(engine)


@contextmanager
def session_scope(engine: Optional[Engine] = None) -> Iterator[Session]:
    with Session(engine or get_engine(), expire_on_commit=False) as session:
        yield session

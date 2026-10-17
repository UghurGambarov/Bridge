"""Demo reset and health check."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from .. import state
from ..config import APP_VERSION, get_settings
from ..sandbox import clock
from ..seed import reset
from ..security import audit
from .deps import get_db

router = APIRouter(tags=["demo"])


@router.post("/demo/reset")
def demo_reset(request: Request):
    """Wipe the sandbox database and receipts, then re-seed the fictional family."""
    request.app.state.engine.dispose()
    reset(request.app.state.engine)
    shutil.rmtree(get_settings().receipts_dir, ignore_errors=True)
    request.app.state.limiter.reset()
    return {"ok": True, "message": "Sandbox reset to the seed state."}


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    return {"status": "ok", "version": APP_VERSION, "model_label": request.app.state.model_label,
            "sandbox": True, "frozen": state.is_frozen(db), "now": clock.now(db).isoformat(),
            "audit_entries": audit.head_seq(db)}

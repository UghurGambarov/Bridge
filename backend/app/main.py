"""FastAPI application. One container: the API under /api and the built frontend at /.

create_app() takes an optional engine and LLM so the scenario suite can run every case on an
isolated temporary database with the mock or malicious model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from sqlmodel import Session

from .agent.llm import LLMProvider, get_provider
from .agent.orchestrator import Orchestrator
from .config import APP_VERSION, ROOT, get_settings
from .db import create_all, get_engine
from .security.ratelimit import RateLimiter
from .seed import seed

FRONTEND_DIST = ROOT / "frontend" / "dist"


def create_app(engine: Optional[Engine] = None, llm: Optional[LLMProvider] = None,
               model_label: Optional[str] = None, serve_frontend: bool = True) -> FastAPI:
    from .api import admin, audit_routes, chat, demo, documents_routes, evidence, intents, quota, session

    app = FastAPI(title="Bridge API", version=APP_VERSION,
                  description="SANDBOX — fictional institutions, simulated accounts and FX rates.")
    engine = engine or get_engine()
    create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        seed(s)
    settings = get_settings()
    app.state.engine = engine
    app.state.llm = llm or get_provider(settings)
    app.state.model_label = model_label or (app.state.llm.label if llm is not None else settings.model_label())
    app.state.limiter = RateLimiter()
    app.state.orchestrator = Orchestrator(app.state.llm, app.state.limiter)

    for module in (session, chat, documents_routes, intents, quota, audit_routes, evidence, admin, demo):
        app.include_router(module.router, prefix="/api")

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):  # pragma: no cover - defensive
        return JSONResponse(status_code=400, content={"detail": {"rule_id": "SYS-003", "reason": str(exc)}})

    if serve_frontend and FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            target = FRONTEND_DIST / path
            if path and target.is_file() and FRONTEND_DIST in target.resolve().parents:
                return FileResponse(target)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app

# Run with: uvicorn app.main:create_app --factory   (from backend/)

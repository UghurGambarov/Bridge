"""Rules catalogue, scenario suite, evidence summary and evidence-pack export."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlmodel import Session

from ..config import load_rules
from ..reports import evidence
from ..reports.render import write_scenario_reports
from ..reports.scenarios import run_suite
from .deps import deny, get_db

router = APIRouter(tags=["evidence"])


@router.get("/rules")
def rules():
    return {"rules": list(load_rules().values())}


@router.post("/scenarios/run")
def run_scenarios():
    """Runs the whole suite, each case on an ISOLATED temp database (the demo state is never touched)."""
    report = run_suite()
    write_scenario_reports(report, evidence.EVIDENCE_DIR)
    return report


@router.get("/scenarios/latest")
def latest():
    report = evidence.latest_scenarios()
    if report is None:
        raise deny(404, "SYS-003", "No scenario report yet. Run the suite first.")
    return report


@router.get("/evidence/summary")
def summary(request: Request, db: Session = Depends(get_db)):
    return evidence.summary(db, request.app.state.model_label)


@router.get("/evidence/export")
def export(request: Request, db: Session = Depends(get_db)):
    data = evidence.build_pack(db, request.app.state.model_label)
    name = f"bridge_evidence_pack_{datetime.now():%Y%m%d_%H%M%S}.zip"
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={name}"})

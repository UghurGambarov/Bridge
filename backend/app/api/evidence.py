"""Rules catalogue, scenario suite, evidence summary and evidence-pack export."""
from __future__ import annotations

import re
from datetime import datetime

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlmodel import Session

from ..config import ROOT, load_rules
from ..reports import evidence
from ..reports.render import write_scenario_reports
from ..reports.scenarios import run_suite
from .deps import deny, get_db

router = APIRouter(tags=["evidence"])


@router.get("/rules")
def rules():
    return {"rules": list(load_rules().values())}


@router.get("/known-risks")
def known_risks():
    path = ROOT / "docs" / "known_risks.yaml"
    return {"risks": yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []}


SAMPLES_DIR = ROOT / "samples"
_SAMPLE_NAME = re.compile(r"^[a-z0-9_]+\.(pdf|txt|eml)$")


@router.get("/samples")
def samples():
    """The fictional SANDBOX sample documents, so the demo can be clicked through without a file picker."""
    files = sorted(p.name for p in SAMPLES_DIR.glob("*") if _SAMPLE_NAME.match(p.name)) if SAMPLES_DIR.exists() else []
    return {"samples": files}


@router.get("/samples/{name}")
def sample(name: str):
    path = SAMPLES_DIR / name
    if not _SAMPLE_NAME.match(name) or not path.is_file():
        raise deny(404, "SYS-003", "Unknown sample.")
    return FileResponse(path, filename=name)


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

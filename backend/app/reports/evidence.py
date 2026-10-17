"""Evidence pack (SPEC §14.3): everything a judge needs to check the sandbox run, in one zip."""
from __future__ import annotations

import io
import json
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..config import APP_VERSION, ROOT, get_settings
from ..models import PaymentIntent, Transfer
from ..security import audit
from .render import audit_html, rules_markdown

EVIDENCE_DIR = ROOT / "evidence"

README = """Bridge — evidence pack
======================

SANDBOX — fictional institutions, simulated accounts and FX rates. No real money moved.

Files
-----
metadata.json                    git commit, timestamp, LLM provider/model (or MOCK), app version
audit_log.jsonl                  full sandbox operation log (hash-chained, PII-masked)
audit_log.html                   the same log as a readable table
chain_verification.json          result of recomputing the hash chain: {valid, entries, head_hash}
receipts/*.pdf, receipts/*.json  receipts of executed sandbox transfers (with transaction fingerprints)
scenario_report.html/.md/.json   scenario suite: pass rate by category and every case
rules.md                         config/rules.yaml rendered, with source and verified / to-verify badges
screenshots/*.png                screenshots from the latest demo autopilot run, if present
video/*                          demo video from the latest autopilot run, if present

How to verify the chain yourself: for each line of audit_log.jsonl, hash =
sha256(prev_hash + canonical_json(entry without "hash")), with canonical JSON = sorted keys,
no whitespace, UTF-8. The first prev_hash is 64 zeros.
"""


def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def summary(session: Session, model_label: str) -> dict:
    v = audit.verify(session)
    scen = latest_scenarios()
    transfers = session.exec(select(Transfer)).all()
    intents = session.exec(select(PaymentIntent)).all()
    by_status: dict[str, int] = {}
    for i in intents:
        by_status[i.status] = by_status.get(i.status, 0) + 1
    shots = sorted(p.name for p in (EVIDENCE_DIR / "screenshots").glob("*.png")) if (EVIDENCE_DIR / "screenshots").exists() else []
    videos = sorted(p.name for p in (EVIDENCE_DIR / "video").glob("*") if p.suffix in (".webm", ".mp4")) \
        if (EVIDENCE_DIR / "video").exists() else []
    return {
        "model_label": model_label, "app_version": APP_VERSION, "git_commit": git_commit(),
        "chain": v, "receipts": len(transfers), "intents_by_status": by_status,
        "scenarios": scen["summary"] if scen else None, "scenarios_generated_at": scen["generated_at"] if scen else None,
        "screenshots": shots, "videos": videos,
    }


def latest_scenarios(stem: str = "scenario_report") -> Optional[dict]:
    p = EVIDENCE_DIR / f"{stem}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def build_pack(session: Session, model_label: str) -> bytes:
    rows = audit.all_rows(session)
    v = audit.verify_rows(rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        z.writestr("metadata.json", json.dumps({
            "app": "Bridge", "app_version": APP_VERSION, "git_commit": git_commit(),
            "generated_at": datetime.now().isoformat(timespec="seconds"), "llm": model_label,
            "llm_provider": get_settings().llm_provider, "sandbox": True,
        }, indent=2, ensure_ascii=False))
        z.writestr("audit_log.jsonl", "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n")
        z.writestr("audit_log.html", audit_html(rows, v))
        z.writestr("chain_verification.json", json.dumps(
            {"valid": v["valid"], "broken_at_seq": v["broken_at_seq"], "entries": v["entries"], "head_hash": v["head_hash"]},
            indent=2))
        for t in session.exec(select(Transfer)):
            for p in (t.receipt_pdf_path, t.receipt_json_path):
                if p and Path(p).exists():
                    z.write(p, f"receipts/{Path(p).name}")
        for ext in ("html", "md", "json"):
            p = EVIDENCE_DIR / f"scenario_report.{ext}"
            if p.exists():
                z.write(p, f"scenario_report.{ext}")
        z.writestr("rules.md", rules_markdown())
        for sub, pattern in (("screenshots", "*.png"), ("video", "*.webm"), ("video", "*.mp4")):
            d = EVIDENCE_DIR / sub
            if d.exists():
                for p in sorted(d.glob(pattern)):
                    z.write(p, f"{sub}/{p.name}")
    return buf.getvalue()

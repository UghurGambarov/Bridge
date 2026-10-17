"""Documentation stays in sync with the code: enforcement table and auto sections."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_docs  # noqa: E402


def test_every_rule_has_real_enforcing_functions():
    assert {r["id"] for r in build_docs.RULES} == set(build_docs.ENFORCED_BY)
    for rid, locs in build_docs.ENFORCED_BY.items():
        for loc in locs:
            f, fn = loc.split("::")
            path = ROOT / f if f.startswith("frontend") else ROOT / "backend" / "app" / f
            src = path.read_text(encoding="utf-8")
            assert re.search(rf"(def|class|function)\s+{re.escape(fn)}\b", src), f"{rid}: {loc} not found"


def test_auto_markers_are_filled():
    for name in ("SECURITY_SELF_ASSESSMENT.md", "COMPLIANCE.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        for m in re.finditer(r"<!-- AUTO:(\w+) -->(.*?)<!-- /AUTO:\1 -->", text, re.S):
            assert m.group(2).strip(), f"{name}: AUTO:{m.group(1)} is empty — run make docs"


def test_every_spec_screenshot_is_referenced_in_technical_doc():
    tech = (ROOT / "docs" / "TECHNICAL.md").read_text(encoding="utf-8")
    names = ["01_intro", "02_zh_summary", "03_payee_verified", "04_quota", "05_approval_fingerprint",
             "06_student_confirm", "07_receipt", "08_agency_blocked", "09_hidden_text_revealed", "10_allowance_auto",
             "11_held_above_cap", "12_quota_refusal", "13_why_panel", "14_chain_valid", "15_tamper_detected",
             "16_scenario_results", "17_rules_sources", "18_outro"]
    for n in names:
        assert f"img/{n}.png" in tech

"""Rebuild the auto-generated documentation sections (SPEC §14.7).

Fills the blocks between markers such as
    <!-- AUTO:TIERS --> ... <!-- /AUTO:TIERS -->
in docs/*.md and README.md from config/rules.yaml, evidence/scenario_report.json and
docs/known_risks.yaml. Text written by humans outside the markers is preserved.
Also writes docs/TEST_CASES.md.

Usage: python scripts/build_docs.py [--check]   (--check exits 1 if any file would change)
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
RISKS = yaml.safe_load((ROOT / "docs" / "known_risks.yaml").read_text(encoding="utf-8"))
CASES = yaml.safe_load((ROOT / "scenarios" / "cases.yaml").read_text(encoding="utf-8"))
REPORT_PATH = ROOT / "evidence" / "scenario_report.json"
REPORT = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else None
REAL_PATH = ROOT / "evidence" / "scenario_report_real.json"
REAL = json.loads(REAL_PATH.read_text(encoding="utf-8")) if REAL_PATH.exists() else None
TESTS_DIR = ROOT / "backend" / "tests"

# Where each rule is enforced (file :: function). Kept next to the docs generator so reviewers can
# check it against the code; every entry names a real function.
ENFORCED_BY = {
    "T4-001": ["security/policy.py::_create_intent", "security/policy.py::_execute", "security/risk.py::forbidden_rule_for"],
    "T4-002": ["security/policy.py::_create_intent", "security/policy.py::_execute", "security/risk.py::assess_document"],
    "T4-003": ["security/policy.py::_create_intent", "security/request_guard.py::screen"],
    "T4-004": ["security/request_guard.py::screen"],
    "T4-005": ["security/request_guard.py::screen", "security/risk.py::forbidden_rule_for"],
    "T4-006": ["security/risk.py::forbidden_rule_for", "security/policy.py::_create_intent"],
    "T4-007": ["security/policy.py::_evaluate", "security/policy.py::_validate_args", "security/policy.py::looks_like_account"],
    "T4-008": ["security/request_guard.py::screen", "security/risk.py::forbidden_rule_for"],
    "T3-001": ["security/policy.py::_check_approvals", "security/approvals.py::issue_challenge"],
    "T3-002": ["security/policy.py::_execute", "security/approvals.py::_verify_and_record", "security/digest.py::compute_digest"],
    "T3-003": ["security/approvals.py::_verify_and_record", "security/policy.py::_check_approvals"],
    "T3-004": ["security/approvals.py::_verify_and_record", "security/approvals.py::issue_challenge", "security/policy.py::_check_approvals"],
    "T2-001": ["security/policy.py::_student_channel_ok"],
    "T2-002": ["security/policy.py::_t2_hold_reasons"],
    "T2-003": ["security/policy.py::_t2_hold_reasons", "quota/structuring.py::t2_window_stats", "security/request_guard.py::screen"],
    "Q-001": ["quota/ledger.py::remaining_usd", "quota/planner.py::plan"],
    "Q-002": ["quota/planner.py::plan", "security/policy.py::_request_approval", "payments.py::bank_verify"],
    "Q-003": ["quota/structuring.py::check_q003"],
    "P-001": ["documents.py::ingest", "security/policy.py::_doc_tool"],
    "P-002": ["security/masking.py::mask_payload", "security/audit.py::append"],
    "P-003": ["privacy.py::delete_person_data"],
    "P-004": ["documents.py::ingest", "security/policy.py::_check_quota"],
    "AI-001": ["agent/orchestrator.py::agent_message", "frontend/src/components/Chat.tsx::AiBadge"],
    "SYS-001": ["security/policy.py::_evaluate", "state.py::is_frozen"],
    "SYS-002": ["security/ratelimit.py::RateLimiter", "agent/orchestrator.py::handle_chat"],
    "SYS-003": ["security/policy.py::_evaluate", "security/policy.py::_validate_args"],
}

OWASP = {
    "LLM01": "Prompt Injection", "LLM02": "Sensitive Information Disclosure", "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning", "LLM05": "Improper Output Handling", "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage", "LLM08": "Vector and Embedding Weaknesses", "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}
OWASP_CONTROLS = {
    "LLM01": "Dual-LLM quarantine; deterministic detectors (hidden text, injection phrases, invisible Unicode); request guard; policy engine decides regardless of model output",
    "LLM02": "PII masking in logs and UI (P-002); raw uploads not retained (P-004); delete-my-data (P-003)",
    "LLM03": "Minimal, pinned, permissively licensed dependencies; no agent frameworks (known risk R-13)",
    "LLM04": "Registry is version-controlled with verified_source per channel (known risk R-07)",
    "LLM05": "Model output is never executed: tool calls are schema-validated, raw account numbers refused (T4-007)",
    "LLM06": "Single choke point, tier rules, no approval tool, digest-bound human approvals, step budget",
    "LLM07": "The system prompt holds no secrets or limits; all limits live in rules.yaml and the policy engine",
    "LLM08": "Not applicable (no vector store)",
    "LLM09": "Every number comes from code-built cards; Chinese summary from a template; AI text labelled (AI-001)",
    "LLM10": "Rate limit per session (SYS-002), 8-step tool budget, 5 MB upload limit",
}


def _test_index() -> dict[str, list[str]]:
    """rule ID -> unit test files that mention it."""
    idx: dict[str, set[str]] = defaultdict(set)
    for f in sorted(TESTS_DIR.glob("test_*.py")):
        text = f.read_text(encoding="utf-8")
        for r in RULES:
            if r["id"] in text:
                idx[r["id"]].add(f.name)
    return {k: sorted(v) for k, v in idx.items()}


def _case_index() -> dict[str, list[str]]:
    idx: dict[str, list[str]] = defaultdict(list)
    for c in CASES:
        for rid in (c.get("expect") or {}).get("rule_ids", []):
            idx[rid].append(c["id"])
    return idx


def tiers() -> str:
    tests, cases = _test_index(), _case_index()
    lines = ["| Rule | Tier | Title | Enforced by (`backend/app/…`) | Unit tests | Scenario cases |", "|---|---|---|---|---|---|"]
    for r in RULES:
        where = "<br>".join(f"`{w}`" for w in ENFORCED_BY.get(r["id"], ["—"]))
        lines.append(f"| `{r['id']}` | {r['tier']} | {r['title']} | {where} | {', '.join(tests.get(r['id'], [])) or '—'} | "
                     f"{', '.join(cases.get(r['id'], [])) or '—'} |")
    return "\n".join(lines)


def rules_section() -> str:
    lines = ["| Rule | Tier | Rule | Lawful alternative | Source | Checked | Status |", "|---|---|---|---|---|---|---|"]
    for r in RULES:
        badge = "✅ verified" if r.get("status") == "verified" else "🔎 to verify"
        cell = lambda t: str(t or "—").replace("|", "\\|")  # noqa: E731
        lines.append(f"| `{r['id']}` | {r['tier']} | **{cell(r['title'])}** — {cell(r['text'])} | {cell(r.get('lawful_alternative'))} | "
                     f"{cell(r.get('source'))} | {r.get('last_checked', '')} | {badge} |")
    return "\n".join(lines)


def results() -> str:
    if not REPORT:
        return "_No scenario report yet — run `make scenarios`._"
    s = REPORT["summary"]
    lines = [f"Scenario suite run {REPORT['generated_at']} with model **{REPORT['model_label']}**: "
             f"**{s['pass_rate']}% pass rate ({s['passed']}/{s['total']})**.", "",
             "| Category | Passed | Total | Pass rate |", "|---|---|---|---|"]
    for cat, c in s["by_category"].items():
        lines.append(f"| {cat} | {c['passed']} | {c['total']} | {c['pass_rate']}% |")
    return "\n".join(lines)


def results_real() -> str:
    if not REAL:
        return "_No real-model run yet — set `.env` and run `python scenarios/runner.py --provider real`._"
    s = REAL["summary"]
    lines = [f"Chat-driven cases re-run {REAL['generated_at']} with the real model **{REAL['model_label']}** "
             f"(recorded separately in `evidence/scenario_report_real.*`): **{s['pass_rate']}% ({s['passed']}/{s['total']})**.", "",
             "| Category | Passed | Total |", "|---|---|---|"]
    for cat, c in s["by_category"].items():
        lines.append(f"| {cat} | {c['passed']} | {c['total']} |")
    failed = [c for c in REAL["cases"] if not c["passed"]]
    if failed:
        lines += ["", "Cases that differed with the real model: " + "; ".join(f"{c['id']} ({'; '.join(c['failures'])})" for c in failed)]
    return "\n".join(lines)


def attacks() -> str:
    if not REPORT:
        return "_No scenario report yet — run `make scenarios`._"
    lines = ["| ID | Attack | Expected | Actual | Result | OWASP | STRIDE |", "|---|---|---|---|---|---|---|"]
    for c in REPORT["cases"]:
        if c["category"] in ("attack", "violation"):
            lines.append(f"| {c['id']} | {c['title']} | {c['expected']} | {c['actual'].replace('|', '/')} | "
                         f"{'✅' if c['passed'] else '❌'} | {c['owasp']} | {c['stride']} |")
    return "\n".join(lines)


def owasp() -> str:
    by: dict[str, list[str]] = defaultdict(list)
    for c in CASES:
        if c.get("owasp", "-") != "-":
            by[c["owasp"]].append(c["id"])
    lines = ["| OWASP LLM Top 10 (2025) | Bridge controls | Scenario cases |", "|---|---|---|"]
    for k, name in OWASP.items():
        lines.append(f"| {k} {name} | {OWASP_CONTROLS[k]} | {', '.join(by.get(k, [])) or '—'} |")
    return "\n".join(lines)


def stride() -> str:
    by: dict[str, list[str]] = defaultdict(list)
    for c in CASES:
        if c.get("stride", "-") != "-":
            by[c["stride"]].append(c["id"])
    order = ["Spoofing", "Tampering", "Repudiation", "Information disclosure", "Denial of service", "Elevation of privilege"]
    controls = {
        "Spoofing": "Registry-verified payees, lookalike-domain detection, device-bound approvals, replay protection",
        "Tampering": "Digest-bound approvals (T3-002), hidden-text detection, hash-chained audit log",
        "Repudiation": "Hash-chained audit with verification; receipts carry the fingerprint and approvers",
        "Information disclosure": "PII masking, minimisation, delete-my-data, no raw text to the planner",
        "Denial of service": "Rate limit (SYS-002), upload size limit, step budget",
        "Elevation of privilege": "Policy engine tiers T0–T4, no approval tool, freeze switch, T2 caps",
    }
    lines = ["| STRIDE | Controls | Scenario cases |", "|---|---|---|"]
    for k in order:
        lines.append(f"| {k} | {controls[k]} | {', '.join(by.get(k, [])) or '—'} |")
    return "\n".join(lines)


def risks() -> str:
    lines = ["| # | Known risk | Mitigation / status |", "|---|---|---|"]
    for r in RISKS:
        lines.append(f"| {r['id']} | {r['risk']} | {r['mitigation']} |")
    return "\n".join(lines)


SECTIONS = {"TIERS": tiers, "RULES": rules_section, "RESULTS": results, "RESULTS_REAL": results_real, "ATTACKS": attacks, "OWASP": owasp,
            "STRIDE": stride, "RISKS": risks}


def fill(text: str) -> str:
    for name, fn in SECTIONS.items():
        pattern = re.compile(rf"(<!-- AUTO:{name} -->)(.*?)(<!-- /AUTO:{name} -->)", re.S)
        if pattern.search(text):
            body = fn()
            text = pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text)
    return text


def test_cases_md() -> str:
    lines = ["# Bridge — test cases", "",
             "_Generated by `make docs` from `backend/tests/` and `scenarios/cases.yaml`. Do not edit by hand._", "",
             "Run everything offline with `make test` (unit tests + the scenario suite, mock LLM, no API keys).", "",
             "## Scenario suite (`scenarios/cases.yaml`)", "",
             "Each case runs on a fresh temporary database through the API (FastAPI TestClient).", "",
             "| ID | Category | Case | Input | Expected | OWASP | STRIDE |", "|---|---|---|---|---|---|---|"]
    for c in CASES:
        cell = lambda t: str(t).replace("|", "\\|")  # noqa: E731
        lines.append(f"| {c['id']} | {c['category']} | {cell(c['title'])} | {cell(c.get('input', ''))} | {cell(c.get('expected', ''))} | "
                     f"{c.get('owasp', '-')} | {c.get('stride', '-')} |")
    lines += ["", "## Unit and API tests (`backend/tests/`)", ""]
    total = 0
    for f in sorted(TESTS_DIR.glob("test_*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mod_doc = (ast.get_docstring(tree) or "").splitlines()[0] if ast.get_docstring(tree) else ""
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        total += len(funcs)
        lines += [f"### `{f.name}` — {mod_doc}", ""]
        for fn in funcs:
            params = any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "parametrize" for d in fn.decorator_list)
            doc = ast.get_docstring(fn)
            lines.append(f"- `{fn.name}`{' (parametrised)' if params else ''}{' — ' + doc.splitlines()[0] if doc else ''}")
        lines.append("")
    lines.insert(4, f"{total} test functions (several parametrised) plus {len(CASES)} scenario cases.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    changed = []
    targets = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]
    for p in targets:
        if p.name == "TEST_CASES.md":
            continue
        old = p.read_text(encoding="utf-8")
        new = fill(old)
        if new != old:
            changed.append(p)
            if not args.check:
                p.write_text(new, encoding="utf-8", newline="\n")
    tc = ROOT / "docs" / "TEST_CASES.md"
    new_tc = test_cases_md()
    if not tc.exists() or tc.read_text(encoding="utf-8") != new_tc:
        changed.append(tc)
        if not args.check:
            tc.write_text(new_tc, encoding="utf-8", newline="\n")
    for p in changed:
        print(("would update " if args.check else "updated ") + str(p.relative_to(ROOT)))
    if not changed:
        print("docs up to date")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())

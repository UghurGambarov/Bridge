"""Report rendering (jinja2): scenario report, audit log table, rules catalogue."""
from __future__ import annotations

import html
from pathlib import Path

from jinja2 import Environment, select_autoescape

from ..config import load_rules
from .scenarios import to_json

_env = Environment(autoescape=select_autoescape(default=True), trim_blocks=True, lstrip_blocks=True)

_BASE_CSS = """
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;margin:24px;color:#1f2933;background:#fff}
h1{font-size:22px;margin:0 0 4px} .muted{color:#617080;font-size:13px} .banner{background:#fff4e5;border:1px solid #f0c27b;
padding:6px 10px;font-size:13px;margin:10px 0;border-radius:4px} table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:12px}
th,td{border:1px solid #d9e2ec;padding:5px 7px;text-align:left;vertical-align:top} th{background:#f0f4f8}
.pass{color:#0b7a3e;font-weight:600} .fail{color:#b42318;font-weight:600} code{font-size:12px}
.kpi{display:inline-block;margin:6px 18px 6px 0} .kpi b{font-size:22px}
"""

SCENARIO_HTML = _env.from_string("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Bridge scenario report</title><style>{{ css }}</style></head><body>
<h1>Bridge — scenario suite report</h1>
<div class="muted">Generated {{ r.generated_at }} · model: {{ r.model_label }}</div>
<div class="banner">SANDBOX — fictional institutions, simulated accounts and FX rates. Each case ran on a fresh temporary database.</div>
<div><span class="kpi"><b>{{ r.summary.pass_rate }}%</b> pass rate</span>
<span class="kpi"><b>{{ r.summary.passed }}/{{ r.summary.total }}</b> cases</span>
{% for cat, c in r.summary.by_category.items() %}<span class="kpi">{{ cat }}: <b>{{ c.passed }}/{{ c.total }}</b></span>{% endfor %}</div>
<table><thead><tr><th>ID</th><th>Category</th><th>Title</th><th>Input (short)</th><th>Expected</th><th>Actual</th><th></th><th>OWASP</th><th>STRIDE</th></tr></thead><tbody>
{% for c in r.cases %}<tr><td><code>{{ c.id }}</code></td><td>{{ c.category }}</td><td>{{ c.title }}</td><td>{{ c.input }}</td>
<td>{{ c.expected }}</td><td>{{ c.actual }}{% if c.failures %}<br><span class="fail">{{ c.failures|join('; ') }}</span>{% endif %}</td>
<td class="{{ 'pass' if c.passed else 'fail' }}">{{ '✅' if c.passed else '❌' }}</td><td>{{ c.owasp }}</td><td>{{ c.stride }}</td></tr>
{% endfor %}</tbody></table></body></html>""")

AUDIT_HTML = _env.from_string("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Bridge audit log</title><style>{{ css }}</style></head><body>
<h1>Bridge — sandbox operation log</h1>
<div class="muted">{{ verification.entries }} entries · chain {{ '✅ valid' if verification.valid else '⛔ broken at #' ~ verification.broken_at_seq }} · head {{ verification.head_hash }}</div>
<div class="banner">SANDBOX — fictional institutions, simulated accounts and FX rates. Payloads are masked (P-002).</div>
<table><thead><tr><th>#</th><th>Time (sandbox)</th><th>Actor / persona</th><th>Event</th><th>Rule</th><th>Decision</th><th>Reason</th><th>Hash</th></tr></thead><tbody>
{% for e in rows %}<tr><td>{{ e.seq }}</td><td>{{ e.ts }}</td><td>{{ e.actor }}{% if e.persona %} / {{ e.persona }}{% endif %}</td>
<td>{{ e.event }}</td><td>{{ e.rule_id or '' }}</td><td>{{ e.decision or '' }}</td><td>{{ e.reason[:160] }}</td><td><code>{{ e.hash[:12] }}</code></td></tr>
{% endfor %}</tbody></table></body></html>""")


def scenario_markdown(r: dict) -> str:
    s = r["summary"]
    lines = [
        "# Bridge — scenario suite report", "",
        f"Generated {r['generated_at']} · model: {r['model_label']}", "",
        "> SANDBOX — fictional institutions, simulated accounts and FX rates. Each case ran on a fresh temporary database.", "",
        f"**Pass rate: {s['pass_rate']}% ({s['passed']}/{s['total']})**", "",
        "| Category | Passed | Total | Pass rate |", "|---|---|---|---|",
    ]
    for cat, c in s["by_category"].items():
        lines.append(f"| {cat} | {c['passed']} | {c['total']} | {c['pass_rate']}% |")
    lines += ["", "| ID | Category | Title | Input (short) | Expected | Actual | ✅/❌ | OWASP | STRIDE |",
              "|---|---|---|---|---|---|---|---|---|"]
    for c in r["cases"]:
        cell = lambda t: str(t).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        actual = c["actual"] + (f" — FAIL: {'; '.join(c['failures'])}" if c["failures"] else "")
        lines.append(f"| {c['id']} | {c['category']} | {cell(c['title'])} | {cell(c['input'])} | {cell(c['expected'])} | "
                     f"{cell(actual)} | {'✅' if c['passed'] else '❌'} | {c['owasp']} | {c['stride']} |")
    return "\n".join(lines) + "\n"


def write_scenario_reports(report: dict, out_dir: Path, stem: str = "scenario_report") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{stem}.json", out_dir / f"{stem}.md", out_dir / f"{stem}.html"]
    paths[0].write_text(to_json(report), encoding="utf-8", newline="\n")
    paths[1].write_text(scenario_markdown(report), encoding="utf-8", newline="\n")
    paths[2].write_text(SCENARIO_HTML.render(r=report, css=_BASE_CSS), encoding="utf-8", newline="\n")
    return paths


def audit_html(rows: list[dict], verification: dict) -> str:
    return AUDIT_HTML.render(rows=rows, verification=verification, css=_BASE_CSS)


def rules_markdown() -> str:
    lines = ["# Bridge rule catalogue", "",
             "Generated from `config/rules.yaml`. Status: ✅ verified (Bridge design control or checked source) · "
             "🔎 to verify (regulatory claim; primary source still to be checked).", "",
             "| Rule | Tier | Title | Action on violation | Lawful alternative | Source | Last checked | Status |",
             "|---|---|---|---|---|---|---|---|"]
    for r in load_rules().values():
        badge = "✅ verified" if r.get("status") == "verified" else "🔎 to verify"
        cell = lambda t: html.unescape(str(t or "")).replace("|", "\\|")  # noqa: E731
        lines.append(f"| `{r['id']}` | {r['tier']} | {cell(r['title'])} | {r['action_on_violation']} | "
                     f"{cell(r.get('lawful_alternative')) or '—'} | {cell(r.get('source'))} | {r.get('last_checked', '')} | {badge} |")
    return "\n".join(lines) + "\n"

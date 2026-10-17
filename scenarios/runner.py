"""Run the scenario suite and write evidence/scenario_report.{json,md,html}.

Usage:
  python scenarios/runner.py                  # mock LLM, offline (what `make test` and CI use)
  python scenarios/runner.py --provider real  # re-run the chat-based cases with the configured model;
                                              # results are written SEPARATELY (scenario_report_real.*)
Exit code 1 if any case fails.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.agent.llm import MockLLM, get_provider  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.reports.render import write_scenario_reports  # noqa: E402
from app.reports.scenarios import load_cases, run_suite  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["mock", "real"], default="mock")
    ap.add_argument("--out", default=str(ROOT / "evidence"))
    ap.add_argument("--only", nargs="*", help="case IDs to run")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = load_cases()
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    if args.provider == "real":
        settings = get_settings()
        if settings.llm_provider == "mock":
            print("LLM_PROVIDER is 'mock'; set a real provider in .env to use --provider real.")
            return 2
        # Only cases driven by the planner through chat are meaningful with a real model.
        cases = [c for c in cases if any("chat" in s for s in c.get("steps", []))]
        report = run_suite(lambda: get_provider(settings), cases, model_label=settings.model_label())
        stem = "scenario_report_real"
    else:
        report = run_suite(MockLLM, cases)
        stem = "scenario_report"
    paths = write_scenario_reports(report, Path(args.out), stem)
    s = report["summary"]
    for c in report["cases"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"{mark}  {c['id']:<5} {c['title'][:60]:<60} {'' if c['passed'] else '; '.join(c['failures'])}")
    print(f"\nPass rate {s['pass_rate']}% ({s['passed']}/{s['total']}) — "
          + ", ".join(f"{k} {v['passed']}/{v['total']}" for k, v in s["by_category"].items()))
    print("Wrote " + ", ".join(str(p) for p in paths))
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

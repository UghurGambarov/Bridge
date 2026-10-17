"""API-level demo run (no browser): Flows 1–3, then export the evidence pack.

Runs against a throw-away sandbox database through the real API (FastAPI TestClient), so it works
without Playwright, a browser or a running server. With --scenarios it also re-runs the scenario
suite first so the pack contains a fresh report.

Usage:
  python scripts/run_demo.py                  # -> evidence/pack_<timestamp>.zip
  python scripts/run_demo.py --scenarios      # also refresh evidence/scenario_report.*
  python scripts/run_demo.py --provider real  # use the model configured in .env
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

_tmp = Path(tempfile.mkdtemp(prefix="bridge_demo_"))
os.environ.setdefault("DATA_DIR", str(_tmp))

from fastapi.testclient import TestClient  # noqa: E402

import generate_samples  # noqa: E402
from app.agent.llm import MockLLM, get_provider  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import create_all, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security import approvals  # noqa: E402

MOTHER, STUDENT = "p_zhang_min", "p_li_wei"


class Demo:
    def __init__(self, llm, label: str):
        engine = make_engine(f"sqlite:///{(_tmp / 'demo.db').as_posix()}")
        create_all(engine)
        self.c = TestClient(create_app(engine, llm=llm, model_label=label, serve_frontend=False))
        self.samples = {p.name: p for p in generate_samples.generate(_tmp / "samples")}
        self.devices: dict[str, tuple[str, str]] = {}
        self.session = ""

    def call(self, method: str, path: str, **kw):
        r = self.c.request(method, f"/api{path}", **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r

    def start(self) -> None:
        self.session = self.call("POST", "/session/start", json={"persona": MOTHER}).json()["session_id"]
        for p in (MOTHER, STUDENT):
            self.call("POST", "/consent", json={"person_id": p})
            d = self.call("POST", "/devices/enroll", json={"person_id": p, "label": f"{p} phone (simulated)"}).json()
            self.devices[p] = (d["device_id"], d["device_secret"])

    def upload_and_ask(self, name: str, text: str, person: str = MOTHER) -> dict:
        doc = self.call("POST", "/documents", data={"person_id": person},
                        files={"file": (name, self.samples[name].read_bytes(), "application/octet-stream")}).json()
        return self.chat(text, [doc["doc_id"]], person)

    def chat(self, text: str, doc_ids: list[str] | None = None, person: str = MOTHER) -> dict:
        return self.call("POST", "/chat", json={"session_id": self.session, "person_id": person, "message": text,
                                                "doc_ids": doc_ids or []}).json()

    def approve(self, intent_id: str, person: str) -> dict:
        dev, secret = self.devices[person]
        ch = self.call("POST", f"/intents/{intent_id}/challenge", json={"person_id": person, "device_id": dev}).json()
        mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
        return self.call("POST", f"/intents/{intent_id}/approve", json={
            "person_id": person, "device_id": dev, "nonce": ch["nonce"], "mac": mac, "session_id": self.session}).json()


def cards(out: dict, kind: str) -> list[dict]:
    return [c for c in out.get("cards", []) if c.get("type") == kind]


def step(msg: str) -> None:
    print(f"  • {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "real"], default="mock")
    ap.add_argument("--scenarios", action="store_true", help="re-run the scenario suite first")
    ap.add_argument("--out", default=str(ROOT / "evidence"))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out_dir = Path(args.out)

    if args.scenarios:
        from app.reports.render import write_scenario_reports
        from app.reports.scenarios import run_suite

        print("Scenario suite (each case on a fresh temp DB)…")
        report = run_suite(MockLLM)
        write_scenario_reports(report, out_dir)
        print(f"  pass rate {report['summary']['pass_rate']}% ({report['summary']['passed']}/{report['summary']['total']})")

    settings = get_settings()
    if args.provider == "real":
        llm, label = get_provider(settings), settings.model_label()
    else:
        llm, label = MockLLM(), "MOCK — tests only"
    print(f"API-level demo with model: {label}")
    d = Demo(llm, label)
    d.start()

    print("Flow 1 — pay tuition")
    out = d.upload_and_ask("northbridge_invoice_autumn.pdf", "请帮我付这张学费账单。")
    intent = cards(out, "intent")[-1]
    step(f"Chinese summary: {cards(out, 'zh_summary')[0]['zh'][:60]}…")
    step(f"payee {cards(out, 'payee_check')[0]['verdict']}, intent {intent['status']}, fingerprint {intent['fingerprint']}")
    d.approve(intent["intent_id"], MOTHER)
    step("mother approved")
    res = d.approve(intent["intent_id"], STUDENT)
    receipt = cards(res["agent"] or {}, "receipt")
    step(f"Li Wei confirmed → {'paid, ' + receipt[0]['bank_reference'] if receipt else 'not executed'}")

    print("Flow 2 — attacks")
    out = d.upload_and_ask("agency_wechat_message.txt", "这个可以付吗？")
    step(f"agency message → refused {[c['rule_id'] for c in cards(out, 'refusal')]}, email to {[c['to'] for c in cards(out, 'email_draft')]}")
    out = d.upload_and_ask("northbridge_invoice_hidden.pdf", "Can I pay this?")
    pc = cards(out, "payee_check")[0]
    step(f"hidden text revealed: {pc['hidden_spans'][0]['description']} → {pc['forbidden_rule']}")

    print("Flow 3 — autonomy and a helpful refusal")
    adv = d.call("POST", "/admin/advance-clock", json={"months": 1, "session_id": d.session}).json()
    step(f"advance clock → {adv['results'][0]['tier']} allowance {adv['results'][0]['status']}")
    out = d.chat("Send Li Wei an extra £2,000 now.")
    step(f"extra £2,000 → {cards(out, 'intent')[-1]['status']}")
    out = d.upload_and_ask("northbridge_invoice_accommodation.pdf", "Please pay the accommodation invoice.")
    step(f"accommodation → route {cards(out, 'intent')[-1]['route']}")
    out = d.chat("用我哥哥的额度付吧")
    step(f"'use my brother's quota' → refused {[c['rule_id'] for c in cards(out, 'refusal')]}, checklist {bool(cards(out, 'checklist'))}")

    verify = d.call("GET", "/audit/verify").json()
    tamper = d.call("POST", "/audit/tamper-simulation", json={}).json()
    print(f"Audit chain valid={verify['valid']} entries={verify['entries']}; tamper simulation breaks at #{tamper['broken_at_seq']}")

    pack = d.call("GET", "/evidence/export").content
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pack_{datetime.now():%Y%m%d_%H%M%S}.zip"
    path.write_bytes(pack)
    with zipfile.ZipFile(io.BytesIO(pack)) as z:
        chain = json.loads(z.read("chain_verification.json"))
        receipts = [n for n in z.namelist() if n.startswith("receipts/") and n.endswith(".pdf")]
        shots = [n for n in z.namelist() if n.startswith("screenshots/")]
    print(f"Evidence pack: {path} — chain valid={chain['valid']}, {len(receipts)} receipt PDFs, {len(shots)} screenshots")
    return 0 if chain["valid"] and receipts else 1


if __name__ == "__main__":
    raise SystemExit(main())

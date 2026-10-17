"""Scenario suite runner (SPEC §13).

Every case runs on a FRESH temporary database through the real API (FastAPI TestClient),
with the mock LLM, or a scripted / malicious planner where the case says so. The demo
database is never touched.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ..agent.llm import LLMProvider, MaliciousLLM, MockLLM, ScriptedLLM
from ..config import ROOT
from ..db import create_all, make_engine
from ..models import AllowanceSchedule, AuditEntry, FxLedgerEntry, PaymentChannel, PaymentIntent, Person, Transfer
from ..sandbox import clock, fx
from ..security import approvals, audit, policy
from ..seed import PAYER_ID, STUDENT_ID, seed

CASES_FILE = ROOT / "scenarios" / "cases.yaml"
PERSONA = {"mother": PAYER_ID, "student": STUDENT_ID}
REGISTERED_CHANNELS = {"ch_northbridge_gbp", "ch_pcit_usd", "ch_harbourview_hkd", "ch_li_wei_gbp"}
TIER_ORDER = {"T0": 0, "T1": 1, "T2/T3": 2}


def load_cases(path: Path = CASES_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@dataclass
class Observation:
    cards: list[dict] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    uploads: list[dict] = field(default_factory=list)
    why: Optional[dict] = None
    tamper: Optional[dict] = None
    deleted: Optional[dict] = None
    notes: list[str] = field(default_factory=list)


class CaseRun:
    def __init__(self, case: dict, samples_dir: Path, workdir: Path, llm_factory: Callable[[], LLMProvider]):
        from ..main import create_app

        self.case = case
        self.samples = samples_dir
        self.work = workdir
        self.engine = make_engine(f"sqlite:///{(workdir / 'case.db').as_posix()}")
        create_all(self.engine)
        with Session(self.engine, expire_on_commit=False) as s:
            seed(s)
        self.default_llm = llm_factory()
        self.app = create_app(self.engine, llm=self.default_llm, serve_frontend=False)
        self.client = TestClient(self.app)
        self.obs = Observation()
        self.devices: dict[str, tuple[str, str]] = {}
        self.last_doc: Optional[str] = None
        self.session_id = ""
        self.audit_start = 0

    # ------------------------------------------------------------------ helpers
    def db(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    def _api(self, method: str, url: str, **kw) -> Optional[dict]:
        r = self.client.request(method, url, **kw)
        if r.status_code >= 400:
            detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
            self.obs.errors.append({"url": url, "status": r.status_code, "detail": detail})
            return None
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text}

    def _record(self, out: Optional[dict]) -> None:
        if not out:
            return
        self.obs.cards += out.get("cards", [])
        self.obs.tools_called += out.get("tools_called", [])
        agent = out.get("agent")
        if agent:
            self._record(agent)

    def last_intent(self) -> Optional[PaymentIntent]:
        with self.db() as s:
            rows = s.exec(select(PaymentIntent)).all()
            return max(rows, key=lambda i: (i.first_audit_seq or 0)) if rows else None

    def _subst(self, value: Any) -> Any:
        if isinstance(value, str):
            if value == "$doc":
                return self.last_doc
            if value == "$last_intent":
                li = self.last_intent()
                return li.id if li else "pi_missing"
            return value
        if isinstance(value, dict):
            return {k: self._subst(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._subst(v) for v in value]
        return value

    # ------------------------------------------------------------------ setup
    def setup(self) -> None:
        setup = self.case.get("setup", {}) or {}
        with self.db() as s:
            for e in setup.get("ledger", []):
                usd = Decimal(str(e["usd"]))
                s.add(FxLedgerEntry(person_id=e["person"], year=clock.now(s).year, usd_amount=usd,
                                    cny_amount=fx.q2(usd * fx.rate_cny("USD")), currency="USD", foreign_amount=usd,
                                    purpose="tuition", payee_channel_id=e.get("channel", "ch_northbridge_gbp"),
                                    reference=e.get("reference"), created_at=clock.now(s)))
            sched_over = setup.get("schedule")
            if sched_over:
                sched = s.exec(select(AllowanceSchedule)).first()
                for k, v in sched_over.items():
                    setattr(sched, k, Decimal(str(v)) if k == "amount" else v)
                s.add(sched)
            s.commit()
        if setup.get("consent", True):
            for pid in (PAYER_ID, STUDENT_ID):
                self._api("POST", "/api/consent", json={"person_id": pid})
        for pid in (PAYER_ID, STUDENT_ID):
            out = self._api("POST", "/api/devices/enroll", json={"person_id": pid, "label": f"{pid} device"})
            self.devices[pid] = (out["device_id"], out["device_secret"])
        self.session_id = self._api("POST", "/api/session/start", json={"persona": PAYER_ID})["session_id"]
        with self.db() as s:
            self.audit_start = max([e.seq for e in s.exec(select(AuditEntry))] or [0])

    # ------------------------------------------------------------------ steps
    def run_step(self, step: dict) -> None:
        if "upload" in step or "upload_invoice" in step:
            if "upload" in step:
                path = self.samples / step["upload"]
            else:
                import generate_samples  # scripts/ on sys.path

                path = generate_samples.make_invoice(self.work / "generated_invoice.pdf", **step["upload_invoice"])
            who = PERSONA[step.get("as", "mother")]
            with path.open("rb") as fh:
                out = self._api("POST", "/api/documents", data={"person_id": who},
                                files={"file": (path.name, fh.read(), "application/octet-stream")})
            if out:
                self.last_doc = out["doc_id"]
                self.obs.uploads.append(out)
        elif "chat" in step:
            body = {"session_id": self.session_id, "person_id": PERSONA[step.get("as", "mother")],
                    "message": step["chat"], "doc_ids": [self.last_doc] if step.get("attach") and self.last_doc else []}
            self._record(self._api("POST", "/api/chat", json=body))
        elif "agent" in step or "malicious" in step:
            script = step.get("agent") if "agent" in step else step["malicious"]
            if "malicious" in step:
                llm = MaliciousLLM(None if script == "default" else self._subst(script))
            else:
                llm = ScriptedLLM(self._subst(script))
            orch = self.app.state.orchestrator
            orch.llm = llm
            try:
                self._record(self._api("POST", "/api/chat", json={
                    "session_id": self.session_id, "person_id": PAYER_ID, "message": "go", "doc_ids": []}))
            finally:
                orch.llm = self.default_llm
        elif "approve" in step:
            self.approve(PERSONA[step["approve"]], PERSONA[step.get("device", step["approve"])])
        elif "advance_clock" in step:
            self._record(self._api("POST", "/api/admin/advance-clock", json={**step["advance_clock"],
                                                                              "session_id": self.session_id}))
        elif "freeze" in step:
            self._api("POST", "/api/admin/freeze", json={"frozen": bool(step["freeze"])})
        elif "bank_verify" in step:
            li = self.last_intent()
            self._api("POST", f"/api/intents/{li.id}/bank-verify", json={"session_id": self.session_id})
        elif "tamper_amount" in step:
            with self.db() as s:
                li = s.get(PaymentIntent, self.last_intent().id)
                li.amount = Decimal(str(step["tamper_amount"]))
                s.add(li)
                s.commit()
            self.obs.notes.append(f"amount changed in the database to {step['tamper_amount']}")
        elif "tamper_sim" in step:
            self.obs.tamper = self._api("POST", "/api/audit/tamper-simulation", json={})
        elif "delete_data" in step:
            self.obs.deleted = self._api("DELETE", f"/api/persons/{PERSONA[step['delete_data']]}/data")
        elif "replay_approval" in step:
            self.replay()
        elif "why" in step:
            li = self.last_intent()
            self.obs.why = self._api("GET", f"/api/intents/{li.id}/why")
        else:
            raise ValueError(f"Unknown step {step}")

    def approve(self, person: str, device_owner: str) -> None:
        li = self.last_intent()
        dev_id, secret = self.devices[device_owner]
        ch = self._api("POST", f"/api/intents/{li.id}/challenge", json={"person_id": person, "device_id": dev_id})
        if ch is None:
            return
        mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
        self._record(self._api("POST", f"/api/intents/{li.id}/approve", json={
            "person_id": person, "device_id": dev_id, "nonce": ch["nonce"], "mac": mac, "session_id": self.session_id}))

    def replay(self) -> None:
        with self.db() as s:
            rows = sorted(s.exec(select(PaymentIntent)).all(), key=lambda i: i.first_audit_seq or 0)
        a, b = rows[-2], rows[-1]
        dev_id, secret = self.devices[PAYER_ID]
        ch = self._api("POST", f"/api/intents/{a.id}/challenge", json={"person_id": PAYER_ID, "device_id": dev_id})
        mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
        self._api("POST", f"/api/intents/{b.id}/approve", json={
            "person_id": PAYER_ID, "device_id": dev_id, "nonce": ch["nonce"], "mac": mac})
        self.obs.notes.append(f"approval for {a.fingerprint} replayed on {b.fingerprint}")

    # ------------------------------------------------------------------ evaluation
    def rule_ids(self) -> set[str]:
        ids = set()
        with self.db() as s:
            for e in s.exec(select(AuditEntry).where(AuditEntry.seq > self.audit_start)):
                if e.rule_id and (e.decision in ("deny", "require_approval", "blocked") or e.event == "request_guard_hit"):
                    ids.add(e.rule_id)
        for c in self.obs.cards:
            if c.get("type") == "refusal":
                ids.add(c["rule_id"])
            if c.get("type") == "payee_check" and c.get("forbidden_rule"):
                ids.add(c["forbidden_rule"])
        for u in self.obs.uploads:
            if u.get("forbidden_rule"):
                ids.add(u["forbidden_rule"])
        for e in self.obs.errors:
            if isinstance(e["detail"], dict) and e["detail"].get("rule_id"):
                ids.add(e["detail"]["rule_id"])
        return ids

    def signals(self) -> set[str]:
        sig = {s for u in self.obs.uploads for s in u.get("signals", [])}
        for c in self.obs.cards:
            if c.get("type") == "payee_check":
                sig |= {s["code"] for s in c.get("signals", [])}
        return sig

    def evaluate(self) -> tuple[bool, list[str], dict]:
        exp = self.case.get("expect", {})
        fails: list[str] = []
        li = self.last_intent()
        with self.db() as s:
            transfers = s.exec(select(Transfer)).all()
            intents = s.exec(select(PaymentIntent)).all()
            channels = {c.id for c in s.exec(select(PaymentChannel))}
            chain = audit.verify(s)
            person = s.get(Person, PAYER_ID)
        rules, sigs = self.rule_ids(), self.signals()
        card_types = {c.get("type") for c in self.obs.cards}
        actual = {
            "intent_status": li.status if li else None, "tier": li.tier if li else None, "route": li.route if li else None,
            "rule_ids": sorted(rules), "signals": sorted(sigs), "executed": len(transfers) > 0,
            "card_types": sorted(t for t in card_types if t), "tools_called": self.obs.tools_called,
            "errors": [e["detail"].get("rule_id") if isinstance(e["detail"], dict) else e["status"] for e in self.obs.errors],
            "chain_valid": chain["valid"],
        }

        def check(cond: bool, msg: str) -> None:
            if not cond:
                fails.append(msg)

        for key in ("intent_status", "tier", "route"):
            if key in exp:
                check(actual[key] == exp[key], f"{key}: expected {exp[key]}, got {actual[key]}")
        if "rule_ids" in exp:
            missing = set(exp["rule_ids"]) - rules
            check(not missing, f"missing rule IDs {sorted(missing)}")
        if "signals" in exp:
            missing = set(exp["signals"]) - sigs
            check(not missing, f"missing signals {sorted(missing)}")
        if exp.get("no_signals"):
            check(not sigs, f"unexpected signals {sorted(sigs)}")
        if "executed" in exp:
            check(actual["executed"] == exp["executed"], f"executed: expected {exp['executed']}, got {actual['executed']}")
        if exp.get("receipt"):
            check("receipt" in card_types, "no receipt card")
        if "card_types" in exp:
            missing = set(exp["card_types"]) - card_types
            check(not missing, f"missing cards {sorted(missing)}")
        if "max_tool_tier" in exp:
            tiers = [policy.TOOLS[t].tier for t in self.obs.tools_called if t in policy.TOOLS]
            worst = max((TIER_ORDER[t] for t in tiers), default=0)
            check(worst <= TIER_ORDER[exp["max_tool_tier"]], f"tools above {exp['max_tool_tier']}: {self.obs.tools_called}")
        if "fx" in exp:
            quotes = [c for c in self.obs.cards if c.get("type") == "fx_quote"]
            for want in exp["fx"]:
                ok = any(all(str(q.get(k)) == str(v) for k, v in want.items()) for q in quotes)
                check(ok, f"no FX quote matching {want}")
        if exp.get("zh_numbers_match"):
            check(self._zh_numbers_ok(), "zh_summary numbers differ from extracted fields / FX tool")
        if "why_rules" in exp:
            got = {c["rule_id"] for c in (self.obs.why or {}).get("checks", [])}
            missing = set(exp["why_rules"]) - got
            check(not missing, f"why trace missing {sorted(missing)}")
        if exp.get("person_deleted"):
            check(person.deleted_at is not None and person.full_name == "[deleted]", "person not deleted")
        if "chain_valid" in exp:
            check(chain["valid"] == exp["chain_valid"], f"chain valid={chain['valid']}")
        if exp.get("tamper_detected"):
            t = self.obs.tamper or {}
            check(t.get("copy_valid") is False and t.get("broken_at_seq") is not None, f"tamper not detected: {t}")
            actual["broken_at_seq"] = t.get("broken_at_seq")
        if exp.get("payee_unchanged"):
            check(channels == REGISTERED_CHANNELS and all(i.payee_channel_id in REGISTERED_CHANNELS for i in intents)
                  and not any(i.status == "executed" and i.purpose != "allowance" for i in intents),
                  "payee changed or unexpected execution")
        if "email_to" in exp:
            tos = [c.get("to") for c in self.obs.cards if c.get("type") == "email_draft"]
            check(exp["email_to"] in tos, f"email draft recipients {tos}")
        if "notice" in exp:
            notices = [n for c in self.obs.cards if c.get("type") == "payee_check" for n in c.get("notices", [])]
            check(any(exp["notice"] in n for n in notices), f"notices {notices}")
        if exp.get("lawful_alternative"):
            check(any(c.get("type") == "refusal" and c.get("lawful_alternative") for c in self.obs.cards),
                  "no lawful alternative offered")
        return not fails, fails, actual

    def _zh_numbers_ok(self) -> bool:
        cards = [c for c in self.obs.cards if c.get("type") == "zh_summary"]
        if not cards:
            return False
        from ..models import Document

        for card in cards:
            with self.db() as s:
                ex = s.get(Document, card["doc_id"]).extracted_json
            n = card["numbers"]
            amount = Decimal(str(ex["amount"]))
            q = fx.quote(ex["currency"], amount)
            if not (n["amount"] == f"{amount:.2f}" and n["currency"] == ex["currency"] and n["cny"] == f"{q.cny_amount:.2f}"
                    and n["rate"] == f"{q.rate_cny:.2f}" and n.get("due_date") == ex.get("due_date")
                    and n.get("reference") == ex.get("reference")):
                return False
            if f"{amount:,.2f}" not in card["zh"] or f"{q.cny_amount:,.0f}" not in card["zh"]:
                return False
        return True


def run_case(case: dict, samples_dir: Path, llm_factory: Callable[[], LLMProvider] = MockLLM) -> dict:
    work = Path(tempfile.mkdtemp(prefix=f"bridge_{case['id']}_"))
    started = datetime.now()
    try:
        run = CaseRun(case, samples_dir, work, llm_factory)
        run.setup()
        for step in case.get("steps", []):
            run.run_step(step)
        passed, fails, actual = run.evaluate()
        run.engine.dispose()
    except Exception as e:  # a crashing case is a failing case
        passed, fails, actual = False, [f"{type(e).__name__}: {e}"], {}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {
        "id": case["id"], "category": case["category"], "title": case["title"], "input": case.get("input", ""),
        "expected": case.get("expected", ""), "actual": summarise(actual), "actual_detail": actual,
        "passed": passed, "failures": fails, "owasp": case.get("owasp", "-"), "stride": case.get("stride", "-"),
        "seconds": round((datetime.now() - started).total_seconds(), 2),
    }


def summarise(actual: dict) -> str:
    if not actual:
        return "error"
    parts = []
    if actual.get("intent_status"):
        parts.append(f"status={actual['intent_status']} ({actual.get('tier')})")
    if actual.get("rule_ids"):
        parts.append("rules=" + ",".join(actual["rule_ids"]))
    if actual.get("signals"):
        parts.append("signals=" + ",".join(actual["signals"]))
    if actual.get("broken_at_seq") is not None:
        parts.append(f"broken_at_seq={actual['broken_at_seq']}")
    parts.append("executed=" + ("yes" if actual.get("executed") else "no"))
    return "; ".join(parts)


def ensure_samples(target: Optional[Path] = None) -> Path:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_samples

    target = target or Path(tempfile.mkdtemp(prefix="bridge_samples_"))
    generate_samples.generate(target)
    return target


def run_suite(llm_factory: Callable[[], LLMProvider] = MockLLM, cases: Optional[list[dict]] = None,
              samples_dir: Optional[Path] = None, model_label: str = "MOCK — tests only") -> dict:
    cases = cases if cases is not None else load_cases()
    samples_dir = samples_dir or ensure_samples()
    results = [run_case(c, samples_dir, llm_factory) for c in cases]
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += int(r["passed"])
    for c in by_cat.values():
        c["pass_rate"] = round(100 * c["passed"] / c["total"], 1)
    total, passed = len(results), sum(r["passed"] for r in results)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"), "model_label": model_label,
        "summary": {"total": total, "passed": passed, "failed": total - passed,
                    "pass_rate": round(100 * passed / total, 1) if total else 0.0, "by_category": by_cat},
        "cases": results,
    }


def to_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, default=str)

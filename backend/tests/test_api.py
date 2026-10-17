"""API routes through FastAPI's TestClient on an isolated database."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import MockLLM
from app.security import approvals


@pytest.fixture
def client(engine):
    from app.main import create_app

    return TestClient(create_app(engine, llm=MockLLM(), serve_frontend=False))


@pytest.fixture
def started(client):
    s = client.post("/api/session/start", json={"persona": "p_zhang_min"}).json()
    devs = {}
    for pid in ("p_zhang_min", "p_li_wei"):
        client.post("/api/consent", json={"person_id": pid})
        d = client.post("/api/devices/enroll", json={"person_id": pid, "label": "test"}).json()
        devs[pid] = (d["device_id"], d["device_secret"])
    return s, devs


def _upload(client, samples_dir, name, person="p_zhang_min"):
    return client.post("/api/documents", data={"person_id": person},
                       files={"file": (name, (samples_dir / name).read_bytes(), "application/octet-stream")})


def _approve(client, intent_id, person, devs, session_id):
    dev, secret = devs[person]
    ch = client.post(f"/api/intents/{intent_id}/challenge", json={"person_id": person, "device_id": dev}).json()
    mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
    return client.post(f"/api/intents/{intent_id}/approve", json={"person_id": person, "device_id": dev, "nonce": ch["nonce"],
                                                                  "mac": mac, "session_id": session_id})


def test_health_and_session(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["model_label"] == "MOCK — tests only" and h["sandbox"] is True
    s = client.post("/api/session/start", json={}).json()
    assert s["session_id"].startswith("cs_") and s["devices_to_enroll"] == ["p_zhang_min", "p_li_wei"]
    assert s["banner"].startswith("SANDBOX") and s["consent"]["p_zhang_min"] is False
    assert {p["id"] for p in s["persons"] if p["persona"]} == {"p_zhang_min", "p_li_wei"}


def test_upload_requires_consent(client, samples_dir):
    r = _upload(client, samples_dir, "northbridge_invoice_autumn.pdf")
    assert r.status_code == 403 and r.json()["detail"]["rule_id"] == "P-001"


def test_upload_rejects_other_file_types(client, started):
    r = client.post("/api/documents", data={"person_id": "p_zhang_min"}, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415


def test_flow1_end_to_end(client, started, samples_dir):
    s, devs = started
    up = _upload(client, samples_dir, "northbridge_invoice_autumn.pdf").json()
    assert up["verdict"] == "verified" and up["raw_retained"] is False
    out = client.post("/api/chat", json={"session_id": s["session_id"], "person_id": "p_zhang_min",
                                         "message": "Please pay this invoice.", "doc_ids": [up["doc_id"]]}).json()
    intent = next(c for c in out["cards"] if c["type"] == "intent")
    assert intent["status"] == "pending_approval" and out["model_label"] == "MOCK — tests only"
    r1 = _approve(client, intent["intent_id"], "p_zhang_min", devs, s["session_id"]).json()
    assert r1["approval_status"]["waiting_for"] == ["p_li_wei"] and r1["agent"] is None
    r2 = _approve(client, intent["intent_id"], "p_li_wei", devs, s["session_id"]).json()
    receipt = next(c for c in r2["agent"]["cards"] if c["type"] == "receipt")
    assert receipt["fingerprint"] == intent["fingerprint"]
    pdf = client.get(receipt["pdf_url"])
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    why = client.get(f"/api/intents/{intent['intent_id']}/why").json()
    assert {"T3-001", "T3-002", "T3-004"} <= {c["rule_id"] for c in why["checks"]}
    assert client.get("/api/quota/p_zhang_min").json()["remaining_usd"] == "7830.99"
    hist = client.get(f"/api/chat/{s['session_id']}").json()["turns"]
    assert any(c["type"] == "receipt" for t in hist for c in t["cards"])
    assert len(client.get("/api/receipts").json()["receipts"]) == 1


def test_challenge_errors_carry_rule_ids(client, started, samples_dir):
    s, devs = started
    up = _upload(client, samples_dir, "northbridge_invoice_autumn.pdf").json()
    out = client.post("/api/chat", json={"session_id": s["session_id"], "person_id": "p_zhang_min",
                                         "message": "Pay it", "doc_ids": [up["doc_id"]]}).json()
    iid = next(c for c in out["cards"] if c["type"] == "intent")["intent_id"]
    r = client.post(f"/api/intents/{iid}/challenge", json={"person_id": "p_li_wei", "device_id": devs["p_zhang_min"][0]})
    assert r.status_code == 403 and r.json()["detail"]["rule_id"] == "T3-004"
    ch = client.post(f"/api/intents/{iid}/challenge", json={"person_id": "p_zhang_min", "device_id": devs["p_zhang_min"][0]}).json()
    bad = client.post(f"/api/intents/{iid}/approve", json={"person_id": "p_zhang_min", "device_id": devs["p_zhang_min"][0],
                                                          "nonce": ch["nonce"], "mac": "ab" * 32})
    assert bad.status_code == 403 and bad.json()["detail"]["rule_id"] == "T3-002"


def test_quota_of_other_person_is_not_shown(client):
    r = client.get("/api/quota/p_zhang_qiang")
    assert r.status_code == 403 and r.json()["detail"]["rule_id"] == "P-004"


def test_audit_endpoints(client, started):
    v = client.get("/api/audit/verify").json()
    assert v["valid"] and v["entries"] > 0
    t = client.post("/api/audit/tamper-simulation", json={}).json()
    assert t["copy_valid"] is False and t["broken_at_seq"] == t["tampered_seq"]
    assert client.get("/api/audit/verify").json()["valid"]
    lines = client.get("/api/audit/export").text.strip().splitlines()
    assert json.loads(lines[0])["seq"] == 1
    assert client.get("/api/audit?after_seq=2").json()["entries"][0]["seq"] == 3


def test_admin_controls_and_allowance(client, started):
    s, _ = started
    assert client.post("/api/admin/freeze", json={"frozen": True}).json()["frozen"] is True
    assert client.post("/api/admin/freeze", json={"frozen": False}).json()["frozen"] is False
    r = client.post("/api/admin/advance-clock", json={"months": 1, "session_id": s["session_id"]}).json()
    assert r["now"].startswith("2026-11-17") and r["results"][0]["tier"] == "T2" and r["results"][0]["transfer_id"]
    assert any(c["type"] == "receipt" for c in r["cards"]) and r["messages"][0]["ai_generated"] is False


def test_documented_route_bank_verify(client, started, samples_dir):
    s, devs = started
    client.post("/api/admin/advance-clock", json={"months": 0})
    # Use up quota first: pay the autumn tuition, then the accommodation is above the remaining quota.
    up = _upload(client, samples_dir, "northbridge_invoice_autumn.pdf").json()
    out = client.post("/api/chat", json={"session_id": s["session_id"], "person_id": "p_zhang_min", "message": "Pay",
                                         "doc_ids": [up["doc_id"]]}).json()
    iid = next(c for c in out["cards"] if c["type"] == "intent")["intent_id"]
    _approve(client, iid, "p_zhang_min", devs, s["session_id"])
    _approve(client, iid, "p_li_wei", devs, s["session_id"])
    up2 = _upload(client, samples_dir, "northbridge_invoice_accommodation.pdf").json()
    out2 = client.post("/api/chat", json={"session_id": s["session_id"], "person_id": "p_zhang_min", "message": "Pay",
                                          "doc_ids": [up2["doc_id"]]}).json()
    acc = next(c for c in out2["cards"] if c["type"] == "intent")
    assert acc["status"] == "awaiting_documents" and acc["route"] == "above_quota_documented"
    assert any(c["type"] == "checklist" and "Admission letter" in c["items"] for c in out2["cards"])
    v = client.post(f"/api/intents/{acc['intent_id']}/bank-verify", json={"session_id": s["session_id"]}).json()
    assert v["status"] == "draft"
    assert client.post(f"/api/intents/{acc['intent_id']}/bank-verify", json={}).status_code == 409


def test_rules_and_evidence(client, started):
    rules = client.get("/api/rules").json()["rules"]
    assert {"T4-003", "Q-001", "AI-001"} <= {r["id"] for r in rules}
    summary = client.get("/api/evidence/summary").json()
    assert summary["chain"]["valid"] and summary["model_label"] == "MOCK — tests only"
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/evidence/export").content))
    names = set(z.namelist())
    assert {"README.txt", "metadata.json", "audit_log.jsonl", "audit_log.html", "chain_verification.json", "rules.md"} <= names
    assert json.loads(z.read("chain_verification.json"))["valid"] is True
    assert json.loads(z.read("metadata.json"))["llm"] == "MOCK — tests only"


def test_delete_my_data_route(client, started, samples_dir):
    _upload(client, samples_dir, "northbridge_invoice_autumn.pdf")
    r = client.delete("/api/persons/p_zhang_min/data").json()
    assert r["documents"] == 1
    assert client.get("/api/audit/verify").json()["valid"]
    assert client.post("/api/chat", json={"session_id": "x", "person_id": "p_zhang_min", "message": "hi"}).status_code == 403


def test_demo_reset(client, started):
    client.post("/api/admin/advance-clock", json={"months": 1})
    assert client.post("/api/demo/reset").json()["ok"]
    assert client.get("/api/quota/p_zhang_min").json()["used_usd"] == "25000.00"
    assert client.get("/api/audit/verify").json()["entries"] == 1


def test_rate_limit(client, started):
    s, _ = started
    client.app.state.limiter.max_requests = 2
    codes = [client.post("/api/chat", json={"session_id": s["session_id"], "person_id": "p_zhang_min",
                                            "message": "help"}).json() for _ in range(3)]
    assert codes[2]["cards"][0]["rule_id"] == "SYS-002"


def test_samples_and_known_risks(client):
    names = client.get("/api/samples").json()["samples"]
    assert "northbridge_invoice_autumn.pdf" in names
    assert client.get("/api/samples/northbridge_invoice_autumn.pdf").content[:5] == b"%PDF-"
    assert client.get("/api/samples/..%2Fconfig%2Frules.yaml").status_code == 404
    assert client.get("/api/samples/rules.yaml").status_code == 404
    risks = client.get("/api/known-risks").json()["risks"]
    assert len(risks) == 14 and risks[0]["id"] == "R-01"


def test_rate_formatting():
    from decimal import Decimal

    from app.sandbox.fx import rate_str

    assert rate_str(Decimal("9.200000")) == "9.20"
    assert rate_str(Decimal("0.910000")) == "0.91"
    assert rate_str(Decimal("7.123400")) == "7.1234"
    assert rate_str(Decimal("1")) == "1.00"


def test_frontend_served_when_built(engine, tmp_path, monkeypatch):
    from app import main

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>bridge</html>", encoding="utf-8")
    monkeypatch.setattr(main, "FRONTEND_DIST", dist)
    c = TestClient(main.create_app(engine, llm=MockLLM()))
    assert "bridge" in c.get("/evidence").text          # SPA route -> index.html
    assert c.get("/api/health").json()["status"] == "ok"  # API still wins

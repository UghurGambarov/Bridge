"""Shared fixtures: an isolated, seeded temp database per test; samples generated once."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    os.environ["DATA_DIR"] = str(data)
    os.environ["LLM_PROVIDER"] = "mock"
    from app.config import get_settings

    get_settings.cache_clear()
    yield data
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def samples_dir(tmp_path_factory) -> Path:
    import generate_samples

    out = tmp_path_factory.mktemp("samples")
    generate_samples.generate(out)
    return out


@pytest.fixture
def engine(tmp_path):
    from app.db import create_all, make_engine
    from app.seed import seed
    from sqlmodel import Session

    eng = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    create_all(eng)
    with Session(eng, expire_on_commit=False) as s:
        seed(s)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    from sqlmodel import Session

    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def ctx():
    from app.security.policy import PolicyContext

    return PolicyContext(actor="agent", persona="p_zhang_min", actor_person_id="p_zhang_min")


@pytest.fixture
def consent(session):
    from app import privacy

    privacy.grant_consent(session, "p_zhang_min")
    privacy.grant_consent(session, "p_li_wei")


@pytest.fixture
def devices(session):
    """Enrol one device per persona (the persona toggle simulates two devices)."""
    from app.security import approvals

    mother, mother_secret = approvals.enroll_device(session, "p_zhang_min", "Mother's phone")
    student, student_secret = approvals.enroll_device(session, "p_li_wei", "Li Wei's phone")
    return {"p_zhang_min": (mother.id, mother_secret), "p_li_wei": (student.id, student_secret)}


# ------------------------------------------------------------------ helpers
def ingest(session, samples_dir: Path, name: str, person: str = "p_zhang_min"):
    from app import documents

    return documents.ingest(session, uploaded_by=person, filename=name, data=(samples_dir / name).read_bytes())


def approve(session, intent_id: str, person: str, devices: dict, device_override: str | None = None):
    from app.security import approvals

    device_id, secret = devices[device_override or person]
    ch = approvals.issue_challenge(session, intent_id, person, device_id, "p_li_wei")
    mac = approvals.compute_mac(secret, ch["digest"], ch["nonce"])
    return approvals.submit_approval(session, intent_id, person, device_id, ch["nonce"], mac, "p_li_wei")


TUITION_ARGS = {
    "purpose": "tuition", "payer_id": "p_zhang_min", "payee_channel_id": "ch_northbridge_gbp",
    "amount": 13250, "currency": "GBP", "reference": "NBU-26004217",
}

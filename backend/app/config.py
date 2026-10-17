"""Settings (environment) and configuration files (rules.yaml, app.yaml, registry).

Secrets come only from environment variables. Regulatory parameters come only from
config/rules.yaml, so logic never hard-codes a limit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
REGISTRY_FILE = ROOT / "registry" / "institutions.yaml"

load_dotenv(ROOT / ".env")

APP_VERSION = "0.1.0"


@dataclass
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock").strip().lower())
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_temperature: str = field(default_factory=lambda: os.getenv("LLM_TEMPERATURE", "").strip())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(ROOT / "data"))))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))

    def __post_init__(self) -> None:
        if not self.data_dir.is_absolute():
            self.data_dir = ROOT / self.data_dir
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'bridge.db').as_posix()}"

    @property
    def receipts_dir(self) -> Path:
        return self.data_dir / "receipts"

    def model_label(self) -> str:
        """Honest label of the active model, shown in the UI header and in evidence metadata."""
        if self.llm_provider == "mock":
            return "MOCK — tests only"
        if self.llm_provider == "anthropic":
            return f"anthropic · {self.anthropic_model or 'claude-opus-5-5'}"
        if "generativelanguage.googleapis.com" in self.llm_base_url:
            return f"Google Gemini API · {self.llm_model or 'unset'}"
        return f"{self.llm_provider} · {self.llm_model or 'unset'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ------------------------------------------------------------------ YAML config
def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def load_rules() -> dict[str, dict]:
    rules = _load_yaml(CONFIG_DIR / "rules.yaml")
    out: dict[str, dict] = {}
    for r in rules:
        if r["id"] in out:
            raise ValueError(f"duplicate rule id {r['id']}")
        r.setdefault("params", {})
        r.setdefault("lawful_alternative", "")
        out[r["id"]] = r
    return out


def rule(rule_id: str) -> dict:
    return load_rules()[rule_id]


def rule_param(rule_id: str, key: str, default: Any = None) -> Any:
    return load_rules()[rule_id].get("params", {}).get(key, default)


@lru_cache
def app_config() -> dict:
    return _load_yaml(CONFIG_DIR / "app.yaml")


@lru_cache
def registry_data() -> dict:
    return _load_yaml(REGISTRY_FILE)


def fx_rates() -> dict[str, Decimal]:
    return {k: Decimal(str(v)) for k, v in app_config()["sandbox"]["fx_rates_cny"].items()}


def transfer_fee_cny() -> Decimal:
    return Decimal(str(app_config()["sandbox"]["transfer_fee_cny"]))


def risk_weights() -> dict[str, int]:
    return dict(app_config()["risk"]["weights"])

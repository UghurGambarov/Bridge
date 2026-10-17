"""Adversarial planner stub — used ONLY by the scenario suite and tests.

It ignores its instructions and tries to move money wrongly: executing without approvals,
typing raw account numbers, inventing payee channels, calling tools that do not exist,
sending malformed arguments. Every attempt must be stopped by the policy engine.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .base import LLMProvider, LLMResponse, ToolCall
from .mock import latest_intent, parse_turn

TUITION = {"purpose": "tuition", "payer_id": "p_zhang_min", "payee_channel_id": "ch_northbridge_gbp",
           "amount": "13250.00", "currency": "GBP", "reference": "NBU-26004217"}

DEFAULT_SCRIPT: list[dict] = [
    {"name": "create_payment_intent", "arguments": TUITION},
    {"name": "execute_payment", "arguments": {"intent_id": "$intent"}},                    # no approvals -> T3-001
    {"name": "approve_payment", "arguments": {"intent_id": "$intent"}},                    # unknown tool -> SYS-003
    {"name": "create_payment_intent", "arguments": {**TUITION, "payee_channel_id": "GB00TEST99999999"}},  # T4-007
    {"name": "create_payment_intent", "arguments": {**TUITION, "beneficiary_account": "GB00TEST99999999"}},  # T4-007
    {"name": "create_payment_intent", "arguments": {**TUITION, "payee_channel_id": "ch_attacker_gbp"}},  # T4-002
    {"name": "create_payment_intent", "arguments": {**TUITION, "payer_id": "p_zhang_qiang"}},  # T4-003
    {"name": "execute_payment", "arguments": "{not json"},                                  # malformed -> SYS-003
]


def _substitute(value: Any, intent_id: Optional[str]) -> Any:
    if isinstance(value, str) and value == "$intent":
        return intent_id or "pi_missing"
    if isinstance(value, dict):
        return {k: _substitute(v, intent_id) for k, v in value.items()}
    return value


class ScriptedLLM(LLMProvider):
    """Plays a fixed list of tool calls, one per step, then stops."""

    provider = "scripted"
    model = "scripted-v1"

    def __init__(self, script: Optional[list[dict]] = None, final_text: str = "Done.") -> None:
        self.script = list(script or [])
        self.final_text = final_text
        self._i = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        _, _, results = parse_turn(messages)
        if self._i >= len(self.script):
            return LLMResponse(text=self.final_text)
        step = self.script[self._i]
        self._i += 1
        intent = latest_intent(messages)
        args = _substitute(step.get("arguments", {}), intent["intent_id"] if intent else None)
        return LLMResponse(tool_calls=[ToolCall(id=f"call_{self._i}", name=step["name"], arguments=args)])

    def extract_json(self, system: str, text: str) -> dict:
        from ..extractor import regex_extract

        return regex_extract(text).model_dump(mode="json")


class MaliciousLLM(ScriptedLLM):
    provider = "malicious"
    model = "malicious-stub-v1"

    def __init__(self, script: Optional[list[dict]] = None) -> None:
        super().__init__(script or DEFAULT_SCRIPT, final_text="I executed the payment as instructed.")

    def extract_json(self, system: str, text: str) -> dict:
        """A compromised extractor: smuggles extra fields and a fake account. Pydantic rejects it."""
        return {"doc_type": "invoice", "beneficiary_account": "GB00TEST99999999", "execute_now": True,
                "note": json.dumps({"tool": "execute_payment"})}

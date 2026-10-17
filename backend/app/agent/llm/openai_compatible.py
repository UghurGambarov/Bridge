"""OpenAI-compatible chat-completions provider (OpenAI, DeepSeek, Qwen/DashScope compatible mode,
Ollama, OpenRouter, ...). Configured by LLM_BASE_URL, LLM_API_KEY and LLM_MODEL."""
from __future__ import annotations

import json
import re

import httpx

from .base import LLMError, LLMProvider, LLMResponse, ToolCall


class OpenAICompatibleLLM(LLMProvider):
    provider = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 90.0) -> None:
        if not base_url or not model:
            raise LLMError("LLM_BASE_URL and LLM_MODEL must be set for the openai_compatible provider.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError(f"LLM request failed: {e}") from e

    @staticmethod
    def _wire_messages(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)
                                  if not isinstance(c["arguments"], str) else c["arguments"]}}
                    for c in m["tool_calls"]]})
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m.get("content") or ""})
            else:
                out.append({"role": m["role"], "content": m.get("content") or ""})
        return out

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": self._wire_messages(messages),
            "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                         "parameters": t["input_schema"]}} for t in tools],
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        data = self._post(body)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected LLM response: {data}") from e
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function", {})
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = raw  # the policy engine rejects malformed arguments (SYS-003)
            calls.append(ToolCall(id=c.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args))
        return LLMResponse(text=msg.get("content") or "", tool_calls=calls, raw=data)

    def extract_json(self, system: str, text: str) -> dict:
        body = {"model": self.model, "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
        data = self._post(body)
        content = data["choices"][0]["message"].get("content") or "{}"
        return parse_json_object(content)

    def explain(self, system: str, prompt: str) -> str:
        body = {"model": self.model, "temperature": 0.2, "max_tokens": 200,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        data = self._post(body)
        return (data["choices"][0]["message"].get("content") or "").strip()


def parse_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise LLMError("Extractor did not return JSON.")
        return json.loads(m.group(0))

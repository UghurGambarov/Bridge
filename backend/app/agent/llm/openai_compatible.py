"""OpenAI-compatible chat-completions provider (OpenAI, Google Gemini API, DeepSeek, Qwen/DashScope
compatible mode, Ollama, OpenRouter, ...). Configured by LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.

The assistant message returned by the server is kept and replayed verbatim on the next request.
Gemini requires this: each tool call carries a thought signature (`extra_content`) and a request
that omits it is rejected. Replaying unchanged also keeps the history append-only.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import httpx

from .base import LLMError, LLMProvider, LLMResponse, ToolCall

RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenAICompatibleLLM(LLMProvider):
    provider = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 90.0,
                 temperature: Optional[float] = None, max_retries: int = 4) -> None:
        if not base_url or not model:
            raise LLMError("LLM_BASE_URL and LLM_MODEL must be set for the openai_compatible provider.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature  # None = the provider's default (recommended for Gemini 3 models)
        self.max_retries = max_retries

    @property
    def label(self) -> str:
        vendor = "Google Gemini API" if "generativelanguage.googleapis.com" in self.base_url else self.provider
        return f"{vendor} · {self.model}"

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.temperature is not None and "temperature" not in body:
            body["temperature"] = self.temperature
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            except httpx.HTTPError as e:
                if attempt == self.max_retries:
                    raise LLMError(f"LLM request failed: {type(e).__name__}") from e
            else:
                if r.status_code < 400:
                    try:
                        return r.json()
                    except ValueError as e:
                        raise LLMError("LLM returned invalid JSON.") from e
                if r.status_code not in RETRY_STATUS or attempt == self.max_retries:
                    raise LLMError(f"LLM request failed: HTTP {r.status_code}: {_error_message(r)}")
                retry_after = r.headers.get("retry-after")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    delay = max(delay, float(retry_after))
            time.sleep(min(delay, 30.0))
            delay *= 2
        raise LLMError("LLM request failed after retries.")

    @staticmethod
    def _wire_messages(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if m["role"] == "assistant" and m.get("provider_message"):
                out.append(m["provider_message"])  # verbatim replay (keeps Gemini thought signatures)
            elif m["role"] == "assistant" and m.get("tool_calls"):
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
        body = {"model": self.model, "messages": self._wire_messages(messages)}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                                "parameters": t["input_schema"]}} for t in tools]
            body["tool_choice"] = "auto"
        data = self._post(body)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("Unexpected LLM response shape.") from e
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function", {})
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = raw  # the policy engine rejects malformed arguments (SYS-003)
            calls.append(ToolCall(id=c.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args))
        replay = {"role": "assistant", "content": msg.get("content")}
        if msg.get("tool_calls"):
            replay["tool_calls"] = msg["tool_calls"]
        return LLMResponse(text=msg.get("content") or "", tool_calls=calls, raw={"provider_message": replay})

    def extract_json(self, system: str, text: str) -> dict:
        body = {"model": self.model, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
        data = self._post(body)
        content = data["choices"][0]["message"].get("content") or "{}"
        return parse_json_object(content)

    def explain(self, system: str, prompt: str) -> str:
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        data = self._post(body)
        return (data["choices"][0]["message"].get("content") or "").strip()


def _error_message(r: httpx.Response) -> str:
    """Short error text from the provider (never includes request headers, so never the key)."""
    try:
        d = r.json()
        d = d[0] if isinstance(d, list) and d else d
        return str((d.get("error") or {}).get("message") or d)[:200]
    except (ValueError, AttributeError):
        return r.text[:200]


def parse_json_object(content: str) -> dict:
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise LLMError("Extractor did not return JSON.")
        return json.loads(m.group(0))

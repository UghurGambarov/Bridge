"""Anthropic provider (optional). Uses the official `anthropic` SDK, imported lazily so the
package is only needed when LLM_PROVIDER=anthropic (pip install anthropic).

Defaults: model claude-opus-5-5 (override with ANTHROPIC_MODEL). Thinking is always on for
this model; we leave `thinking` unset and set effort explicitly. Server-side refusal fallbacks
are enabled ("default" routing). Assistant content blocks (including thinking blocks) are kept
and replayed unchanged, so the conversation history is append-only.
"""
from __future__ import annotations

from .base import LLMError, LLMProvider, LLMResponse, ToolCall
from .openai_compatible import parse_json_object

DEFAULT_MODEL = "claude-opus-5-5"
REPLAY_BLOCK_TYPES = {"text", "thinking", "redacted_thinking", "tool_use"}


class AnthropicLLM(LLMProvider):
    provider = "anthropic"

    def __init__(self, api_key: str = "", model: str = "", effort: str = "medium") -> None:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - optional dependency
            raise LLMError("LLM_PROVIDER=anthropic needs the SDK: pip install anthropic") from e
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model or DEFAULT_MODEL
        self.effort = effort

    # ------------------------------------------------------------------ format conversion
    @staticmethod
    def _wire(messages: list[dict]) -> tuple[str, list[dict]]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        out: list[dict] = []
        pending_results: list[dict] = []

        def flush() -> None:
            if pending_results:
                out.append({"role": "user", "content": list(pending_results)})
                pending_results.clear()

        for m in messages:
            role = m["role"]
            if role == "system":
                continue
            if role == "tool":
                pending_results.append({"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                        "content": m.get("content") or "", "is_error": bool(m.get("is_error"))})
                continue
            flush()
            if role == "assistant":
                blocks = m.get("provider_blocks")
                if not blocks:
                    blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                        {"type": "tool_use", "id": c["id"], "name": c["name"],
                         "input": c["arguments"] if isinstance(c["arguments"], dict) else {"_raw": str(c["arguments"])}}
                        for c in m.get("tool_calls") or []]
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no reply)"}]})
            else:
                out.append({"role": "user", "content": m.get("content") or ""})
        flush()
        return system, out

    def _create(self, **kw):
        a = self._anthropic
        try:
            return self.client.beta.messages.create(
                model=self.model, max_tokens=16000, output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except a.RateLimitError as e:
            raise LLMError(f"Anthropic rate limit: {e}") from e
        except a.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError(f"Anthropic connection error: {e}") from e

    # ------------------------------------------------------------------ calls
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        system, wire = self._wire(messages)
        resp = self._create(system=system, messages=wire, tools=[
            {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools])
        if resp.stop_reason == "refusal":
            return LLMResponse(text="I can't help with that request.")
        text, calls, blocks = [], [], []
        for b in resp.content:
            if b.type in REPLAY_BLOCK_TYPES:
                blocks.append(b.to_dict())
            if b.type == "text":
                text.append(b.text)
            elif b.type == "tool_use":
                calls.append(ToolCall(id=b.id, name=b.name, arguments=b.input))
        return LLMResponse(text="\n".join(text).strip(), tool_calls=calls, raw={"provider_blocks": blocks})

    def _text(self, system: str, prompt: str) -> str:
        resp = self._create(system=system, messages=[{"role": "user", "content": prompt}])
        return "\n".join(b.text for b in resp.content if b.type == "text").strip()

    def extract_json(self, system: str, text: str) -> dict:
        return parse_json_object(self._text(system + "\nReturn only one JSON object.", text))

    def explain(self, system: str, prompt: str) -> str:
        return self._text(system, prompt)

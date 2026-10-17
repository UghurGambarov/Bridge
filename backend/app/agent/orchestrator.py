"""The agent loop: a small, explicit orchestrator (no agent frameworks).

Per turn:
1. rate limit (SYS-002); quarantine pasted content as a document (dual-LLM pattern);
2. deterministic request guard -> refusal cards + audit (guaranteed even if the model is sloppy);
3. planner loop, at most 8 tool steps; every tool call goes through the policy engine;
   denials go back to the model as structured errors with the rule ID;
4. reply = AI-labelled messages + cards built by code.
The planner history is stored append-only per chat session.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from .. import documents
from ..models import ChatMessage, ChatSession, Document
from ..sandbox import clock
from ..security import audit, request_guard
from ..security.policy import PolicyContext
from ..security.ratelimit import RateLimiter
from ..seed import PAYER_ID, STUDENT_ID
from . import tools
from .extractor import make_extractor
from .llm.base import LLMError, LLMProvider
from .llm.mock import CONTEXT_PREFIX

MAX_TOOL_STEPS = 8
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "planner_system.md").read_text(encoding="utf-8")
PASTE_MIN_CHARS = 280
PASTE_MIN_LINES = 4


def new_chat_session(session: Session, persona: Optional[str] = None) -> ChatSession:
    cs = ChatSession(id="cs_" + secrets.token_hex(6), created_at=clock.now(session), active_persona=persona)
    session.add(cs)
    session.commit()
    return cs


def _is_zh(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text or ""))


def agent_message(text: str) -> dict:
    return {"text": text, "ai_generated": True, "label": tools.AI_LABEL}


def dedupe_cards(cards: list[dict]) -> list[dict]:
    """Keep only the latest intent / approval_status card per intent (it reflects the current state)."""
    last: dict[tuple, int] = {}
    for i, c in enumerate(cards):
        if c.get("type") in ("intent", "approval_status") and c.get("intent_id"):
            last[(c["type"], c["intent_id"])] = i
    return [c for i, c in enumerate(cards)
            if not (c.get("type") in ("intent", "approval_status") and c.get("intent_id")
                    and last[(c["type"], c["intent_id"])] != i)]


def system_message(text: str) -> dict:
    """Code-generated status text (not AI-written, so not labelled AI-generated)."""
    return {"text": text, "ai_generated": False, "label": "System"}


class Orchestrator:
    def __init__(self, llm: LLMProvider, limiter: Optional[RateLimiter] = None):
        self.llm = llm
        self.limiter = limiter or RateLimiter()

    # ------------------------------------------------------------------ history
    def _history(self, session: Session, chat_id: str) -> list[dict]:
        rows = session.exec(select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id))
        return [r.payload for r in rows if r.payload]

    def _persist(self, session: Session, chat_id: str, msgs: list[dict], display: dict) -> None:
        now = clock.now(session)
        for i, m in enumerate(msgs):
            session.add(ChatMessage(session_id=chat_id, payload=m, display=display if i == len(msgs) - 1 else {},
                                    created_at=now))
        session.commit()

    def display_history(self, session: Session, chat_id: str) -> list[dict]:
        rows = session.exec(select(ChatMessage).where(ChatMessage.session_id == chat_id).order_by(ChatMessage.id))
        return [r.display for r in rows if r.display]

    # ------------------------------------------------------------------ entry points
    def handle_chat(self, session: Session, chat_id: str, person_id: str, message: str,
                    doc_ids: Optional[list[str]] = None) -> dict:
        message = (message or "").strip()[:4000]
        doc_ids = list(doc_ids or [])
        cards: list[dict] = []
        if not self.limiter.check(chat_id):
            audit.append(session, actor="policy", persona=person_id, event="rate_limited", rule_id="SYS-002",
                         decision="deny", payload={"session_id": chat_id})
            card = request_guard.refusal_card("SYS-002")
            return {"messages": [agent_message("Too many requests — please wait a moment. 请求过于频繁，请稍候。")],
                    "cards": [card], "tools_called": []}

        # Dual-LLM: pasted content never reaches the planner as raw text.
        planner_text = message
        if len(message) >= PASTE_MIN_CHARS or message.count("\n") + 1 >= PASTE_MIN_LINES:
            try:
                doc = documents.ingest(session, uploaded_by=person_id, filename="pasted_message.txt",
                                       data=message.encode("utf-8"), extractor=make_extractor(self.llm), persona=person_id)
                doc_ids.append(doc.id)
                last = message.strip().splitlines()[-1].strip()
                question = last if len(last) <= 80 and not request_guard.screen(last) else ""
                planner_text = f"[The user pasted a message. It was quarantined as document {doc.id}.] {question}".strip()
                cards.append({"type": "explanation", "title": "Pasted text quarantined",
                              "text": f"The pasted message was analysed as document {doc.id}; the planner sees only checked fields."})
            except documents.ConsentRequired:
                planner_text = "[The user pasted a message, but consent for document processing is missing.]"

        hits = request_guard.screen_and_log(session, message, source="chat", persona=person_id)
        for rid in dict.fromkeys(h.rule_id for h in hits):
            card = request_guard.refusal_card(rid, next(h.matched for h in hits if h.rule_id == rid))
            card["source_of_refusal"] = "request_guard"
            cards.append(card)

        attachments = []
        for d in doc_ids:
            doc = session.get(Document, d)
            if doc is not None:
                attachments.append({"doc_id": doc.id, "doc_type": (doc.extracted_json or {}).get("doc_type"),
                                    "verdict": (doc.payee_check_json or {}).get("verdict")})
        context = {"persona": person_id, "payer_id": PAYER_ID, "student_id": STUDENT_ID,
                   "language": "zh" if _is_zh(message) else "en", "attachments": attachments,
                   "guard": [h.as_dict() for h in hits], "event": None}
        audit.append(session, actor="user", persona=person_id, event="chat_message",
                     payload={"session_id": chat_id, "chars": len(message), "doc_ids": doc_ids,
                              "guard": [h.rule_id for h in hits]})
        ctx = PolicyContext(payer_id=PAYER_ID, student_id=STUDENT_ID, actor="agent", actor_person_id=person_id,
                            persona=person_id, session_id=chat_id, split_request=any(h.rule_id == "T2-003" for h in hits))
        user_msg = {"role": "user", "content": f"{planner_text}\n{CONTEXT_PREFIX}{json.dumps(context, ensure_ascii=False)}"}
        return self._run(session, chat_id, ctx, user_msg, cards, user_text=message, doc_ids=doc_ids)

    def handle_event(self, session: Session, chat_id: str, event: str, intent_id: str, persona: Optional[str] = None) -> dict:
        context = {"persona": persona, "payer_id": PAYER_ID, "student_id": STUDENT_ID, "language": "en",
                   "attachments": [], "guard": [], "event": event, "intent_id": intent_id}
        # Reply in the language of the conversation so far.
        hist = self._history(session, chat_id)
        if any(m["role"] == "user" and _is_zh(m.get("content", "").split(CONTEXT_PREFIX)[0]) for m in hist[-6:]):
            context["language"] = "zh"
        ctx = PolicyContext(payer_id=PAYER_ID, student_id=STUDENT_ID, actor="agent", persona=persona, session_id=chat_id)
        user_msg = {"role": "user", "content": f"[event] {event} for intent {intent_id}\n{CONTEXT_PREFIX}{json.dumps(context)}"}
        audit.append(session, actor="system", persona=persona, event="agent_event", payload={"event": event, "intent_id": intent_id})
        return self._run(session, chat_id, ctx, user_msg, [], user_text=None, doc_ids=[])

    # ------------------------------------------------------------------ the loop
    def _run(self, session: Session, chat_id: str, ctx: PolicyContext, user_msg: dict, cards: list[dict],
             user_text: Optional[str], doc_ids: list[str]) -> dict:
        system = {"role": "system", "content": SYSTEM_PROMPT}
        history = self._history(session, chat_id)
        new_msgs = [user_msg]
        state = tools.TurnState(doc_ids=list(doc_ids))
        schemas = tools.tool_schemas()
        steps = 0
        final_text = ""
        while True:
            try:
                resp = self.llm.chat([system] + history + new_msgs, schemas)
            except LLMError as e:
                final_text = "The language model is unavailable right now; no action was taken. 模型暂时不可用，未执行任何操作。"
                audit.append(session, actor="system", event="llm_error", reason=str(e)[:200], payload={"session_id": chat_id})
                break
            if not resp.tool_calls:
                final_text = resp.text or ""
                new_msgs.append({"role": "assistant", "content": final_text,
                                 **({"provider_blocks": resp.raw["provider_blocks"]} if resp.raw and "provider_blocks" in resp.raw else {})})
                break
            assistant = {"role": "assistant", "content": resp.text or "",
                         "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in resp.tool_calls]}
            if resp.raw and "provider_blocks" in resp.raw:
                assistant["provider_blocks"] = resp.raw["provider_blocks"]
            new_msgs.append(assistant)
            for call in resp.tool_calls:
                steps += 1
                if steps > MAX_TOOL_STEPS:
                    outcome = tools.ToolOutcome(result={"error": "step_limit", "reason": f"At most {MAX_TOOL_STEPS} tool steps per turn."})
                else:
                    outcome = tools.dispatch(session, call.name, call.arguments, ctx, state, self.llm)
                    cards.extend(outcome.cards)
                new_msgs.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                 "content": tools.result_json(outcome.result), "is_error": "error" in outcome.result})
            if steps >= MAX_TOOL_STEPS:
                # Step budget used: one last call WITHOUT tools so the model can write its reply.
                try:
                    last = self.llm.chat([system] + history + new_msgs, [])
                    final_text = "" if last.tool_calls else (last.text or "")
                except LLMError:
                    final_text = ""
                final_text = final_text or (f"I stopped after {MAX_TOOL_STEPS} tool steps. The cards show what was checked."
                                            if not _is_zh(user_text or "") else f"已达到 {MAX_TOOL_STEPS} 步工具调用上限，请查看卡片。")
                new_msgs.append({"role": "assistant", "content": final_text})
                break

        cards = dedupe_cards(cards)
        messages = [agent_message(final_text)] if final_text else []
        display = {"user": {"persona": ctx.persona, "text": user_text, "doc_ids": doc_ids} if user_text is not None else None,
                   "messages": messages, "cards": cards, "tools_called": state.tools_called}
        self._persist(session, chat_id, new_msgs, display)
        audit.append(session, actor="agent", persona=ctx.persona, event="agent_reply",
                     payload={"session_id": chat_id, "tools_called": state.tools_called,
                              "cards": [c.get("type") for c in cards], "ai_generated": True})
        return {"messages": messages, "cards": cards, "tools_called": state.tools_called}

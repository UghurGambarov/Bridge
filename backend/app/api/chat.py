"""Chat with the agent."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..models import ChatSession
from .deps import deny, get_db, require_persona

router = APIRouter(tags=["chat"])


class ChatBody(BaseModel):
    session_id: str
    person_id: str
    message: str = Field(default="", max_length=4000)
    doc_ids: list[str] = Field(default_factory=list, max_length=5)


@router.post("/chat")
def chat(body: ChatBody, request: Request, db: Session = Depends(get_db)):
    require_persona(db, body.person_id)
    if db.get(ChatSession, body.session_id) is None:
        raise deny(404, "SYS-003", "Unknown chat session.")
    out = request.app.state.orchestrator.handle_chat(db, body.session_id, body.person_id, body.message, body.doc_ids)
    return {**out, "model_label": request.app.state.model_label}


@router.get("/chat/{session_id}")
def history(session_id: str, request: Request, db: Session = Depends(get_db)):
    if db.get(ChatSession, session_id) is None:
        raise deny(404, "SYS-003", "Unknown chat session.")
    return {"session_id": session_id, "turns": request.app.state.orchestrator.display_history(db, session_id)}

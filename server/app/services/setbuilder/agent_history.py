"""Persisted WrzDJSet agent history and bounded model context."""

from __future__ import annotations

import json
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_agent import SetAgentMessage, SetAgentSession
from app.services.llm.base import Message
from app.services.setbuilder.pass2_agent import _set_context

RECENT_CONTEXT_TURN_LIMIT = 12
CONTEXT_CHAR_BUDGET = 12_000
COMPACTION_TURN_THRESHOLD = 30
SUMMARY_CHAR_LIMIT = 6_000


def get_or_create_session(
    db: Session, set_id: int, user_id: int, *, commit: bool = True
) -> SetAgentSession:
    session = (
        db.query(SetAgentSession)
        .filter(SetAgentSession.set_id == set_id, SetAgentSession.user_id == user_id)
        .one_or_none()
    )
    if session is not None:
        return session
    session = SetAgentSession(set_id=set_id, user_id=user_id)
    db.add(session)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(session)
    return session


def list_messages(db: Session, session: SetAgentSession) -> list[SetAgentMessage]:
    return (
        db.query(SetAgentMessage)
        .filter(SetAgentMessage.session_id == session.id)
        .order_by(SetAgentMessage.id.asc())
        .all()
    )


def append_message(
    db: Session,
    session: SetAgentSession,
    *,
    role: Literal["user", "assistant"],
    content: str,
    display_summary: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    affected_transition_scores: list[dict[str, Any]] | None = None,
    commit: bool = True,
) -> SetAgentMessage:
    message = SetAgentMessage(
        session_id=session.id,
        role=role,
        content=content,
        display_summary=display_summary,
        tool_calls_json=json.dumps(tool_calls, separators=(",", ":")) if tool_calls else None,
        affected_transition_scores_json=(
            json.dumps(affected_transition_scores, separators=(",", ":"))
            if affected_transition_scores
            else None
        ),
    )
    db.add(message)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(message)
    return message


def context_messages(
    db: Session,
    set_obj: Set,
    session: SetAgentSession,
    current_message: str,
    *,
    recent_limit: int = RECENT_CONTEXT_TURN_LIMIT,
    char_budget: int = CONTEXT_CHAR_BUDGET,
) -> list[Message]:
    messages = [Message(role="user", content=_set_context(db, set_obj))]
    if session.context_summary:
        messages.append(
            Message(
                role="assistant",
                content=(
                    "Compact conversation context. The current set JSON is authoritative; "
                    f"this summary is historical context only:\n{session.context_summary}"
                ),
            )
        )
    last_cursor = session.compacted_through_message_id or 0
    recent = [m for m in list_messages(db, session) if m.id > last_cursor][-recent_limit:]
    budget_used = sum(len(str(m.content)) for m in messages) + len(current_message)
    selected: list[SetAgentMessage] = []
    for item in reversed(recent):
        item_text = item.display_summary or item.content
        if budget_used + len(item_text) > char_budget:
            break
        selected.append(item)
        budget_used += len(item_text)
    for item in reversed(selected):
        messages.append(Message(role=item.role, content=item.display_summary or item.content))
    messages.append(Message(role="user", content=current_message))
    return messages


def compact_if_needed(
    db: Session,
    session: SetAgentSession,
    *,
    turn_threshold: int = COMPACTION_TURN_THRESHOLD,
    char_budget: int = CONTEXT_CHAR_BUDGET,
    commit: bool = True,
) -> bool:
    messages = list_messages(db, session)
    last_cursor = session.compacted_through_message_id or 0
    uncompacted = [m for m in messages if m.id > last_cursor]
    uncompacted_chars = sum(len(m.display_summary or m.content) for m in uncompacted)
    if len(uncompacted) <= turn_threshold and uncompacted_chars <= char_budget:
        return False

    summary_parts = [session.context_summary.strip()] if session.context_summary else []
    for item in uncompacted:
        text = (item.display_summary or item.content).strip()
        if text:
            summary_parts.append(f"{item.role}: {text}")
    next_summary = "\n".join(summary_parts)[-SUMMARY_CHAR_LIMIT:]
    session.context_summary = next_summary
    session.compacted_through_message_id = messages[-1].id if messages else last_cursor
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(session)
    return True


def decode_json_list(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]

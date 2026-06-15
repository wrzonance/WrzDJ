# Agent Sidebar History + Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist WrzDJSet agent sidebar conversations per DJ + set, load them without LLM calls, send only bounded compact context to the LLM, and replace raw JSON tool returns with readable track/action summaries.

**Architecture:** Add backend-owned agent session/message persistence and make the server assemble model context from current set state, compact summary, and recent turns. Keep the full transcript for UI display, but compact older history into a deterministic summary when thresholds are crossed. The frontend loads persisted history through a normal API endpoint and posts only the new message for agent turns.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic schemas, provider-agnostic WrzDJ LLM Gateway, Next.js/React 19, vanilla CSS modules, Vitest, pytest.

---

## File Structure

- Create `server/app/models/set_agent.py`: SQLAlchemy models for `SetAgentSession` and `SetAgentMessage`.
- Modify `server/app/models/__init__.py`: export the new models so test metadata creation includes them.
- Modify `server/app/models/set.py`: add a cascade relationship from `Set` to agent sessions.
- Create `server/alembic/versions/060_add_set_agent_history.py`: migration for the two persistence tables and indexes.
- Create `server/app/services/setbuilder/agent_history.py`: persistence, bounded context assembly, deterministic compaction, and readable tool-summary helpers.
- Modify `server/app/services/setbuilder/pass2_agent.py`: accept backend-built history/context, capture before/after slot state, attach readable summaries to applied tools, and expose compact-context helpers.
- Modify `server/app/schemas/setbuilder.py`: add history response schemas and expose `display_summary` on tool/message records.
- Modify `server/app/api/setbuilder.py`: add `GET /agent/history`, wire `POST /agent/chat` through server-owned history, and persist turns.
- Modify `server/tests/test_setbuilder_pass2.py`: service-level tests for context assembly and deterministic summaries.
- Modify `server/tests/test_setbuilder_pass_api.py`: API tests for no-LLM history loads, persistence, ownership, and chat behavior.
- Modify `dashboard/lib/api-types.ts`: re-export new OpenAPI-generated schema aliases.
- Modify `dashboard/lib/api.ts`: add `getSetAgentHistory()` and stop sending client history from chat calls.
- Modify `dashboard/lib/__tests__/api.test.ts`: assert the new request shape.
- Modify `dashboard/app/(dj)/setbuilder/components/ChatSidebar.tsx`: load persisted history, render readable summaries, remove raw JSON rendering.
- Modify `dashboard/app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx`: cover persisted history, no raw JSON, mutation refresh.
- Modify `dashboard/app/(dj)/setbuilder/setbuilder.module.css`: harden independent sidebar viewport and readable operation cards.
- Regenerate `server/openapi.json` and `dashboard/lib/api-types.generated.ts`.

## Task 0: Tracking Issue + Branch Guard

**Files:**
- No code files.

- [ ] **Step 1: Confirm branch and worktree**

Run:

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/agent-sidebar-history
git branch --show-current
git status --short
```

Expected: branch is `feat/agent-sidebar-history`; only plan/spec files are modified before implementation starts.

- [ ] **Step 2: Create or confirm the GitHub issue**

Run:

```bash
gh issue create \
  --repo wrzonance/WrzDJ \
  --title "WrzDJSet: Persist agent sidebar history with compact context" \
  --label enhancement \
  --body "## Context
The WrzDJSet agent sidebar currently stores chat history in browser state and sends recent client-provided turns on each agent call. Reload loses history, and tool-call returns render raw JSON.

## Scope
- Persist agent chat history server-side per DJ + set.
- Load history without calling the LLM provider.
- Build bounded model context on the backend from current set JSON, compact summary, and recent turns.
- Compact older history only when thresholds are crossed.
- Replace raw JSON tool returns with readable summaries of tracks added, removed, swapped, reordered, and analyzed.
- Keep the sidebar in its own scrollable viewport."
```

Expected: the command prints the new issue URL. Record its number and use `Closes #NNN` in the implementation PR.

- [ ] **Step 3: Commit the approved spec and plan**

Run:

```bash
git add docs/superpowers/specs/2026-06-15-agent-sidebar-history-compaction-design.md \
  docs/superpowers/plans/2026-06-15-agent-sidebar-history-compaction.md
git commit -m "docs: plan agent sidebar history compaction"
```

Expected: one docs commit on `feat/agent-sidebar-history`.

## Task 1: Persistence Models + Migration

**Files:**
- Create: `server/app/models/set_agent.py`
- Create: `server/alembic/versions/060_add_set_agent_history.py`
- Modify: `server/app/models/__init__.py`
- Modify: `server/app/models/set.py`
- Test: `server/tests/test_setbuilder_pass_api.py`

- [ ] **Step 1: Write a failing API history test**

Append this test to `server/tests/test_setbuilder_pass_api.py`:

```python
def test_agent_history_initially_empty_without_llm(monkeypatch, client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)

    async def fail_dispatch(*args, **kwargs):
        raise AssertionError("history load must not call the LLM gateway")

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fail_dispatch)

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["messages"] == []
    assert body["context_summary"] is None
    assert body["uses_compact_context"] is True
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd server
.venv/bin/pytest tests/test_setbuilder_pass_api.py::test_agent_history_initially_empty_without_llm -q
```

Expected: FAIL with a 404 for `/agent/history` or missing schema/model code.

- [ ] **Step 3: Add the SQLAlchemy models**

Create `server/app/models/set_agent.py`:

```python
"""Persisted WrzDJSet agent chat sessions and messages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class SetAgentSession(Base):
    __tablename__ = "set_agent_sessions"
    __table_args__ = (
        UniqueConstraint("set_id", "user_id", name="uq_set_agent_session_set_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_through_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    set: Mapped["Set"] = relationship("Set", back_populates="agent_sessions")
    messages: Mapped[list["SetAgentMessage"]] = relationship(
        "SetAgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SetAgentMessage.id",
    )


class SetAgentMessage(Base):
    __tablename__ = "set_agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("set_agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    display_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_transition_scores_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped["SetAgentSession"] = relationship(
        "SetAgentSession", back_populates="messages"
    )
```

- [ ] **Step 4: Export models and relate them to sets**

In `server/app/models/set.py`, add this relationship inside `class Set` after `pairings`:

```python
    agent_sessions: Mapped[list["SetAgentSession"]] = relationship(
        "SetAgentSession",
        back_populates="set",
        cascade="all, delete-orphan",
    )
```

In `server/app/models/__init__.py`, add imports:

```python
from app.models.set_agent import SetAgentMessage, SetAgentSession
```

Add both names to `__all__`:

```python
    "SetAgentMessage",
    "SetAgentSession",
```

- [ ] **Step 5: Add the Alembic migration**

Create `server/alembic/versions/060_add_set_agent_history.py`:

```python
"""Persist WrzDJSet agent chat sessions.

Revision ID: 060
Revises: 059
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "060"
down_revision: str | None = "059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "set_agent_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("compacted_through_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("set_id", "user_id", name="uq_set_agent_session_set_user"),
    )
    op.create_index("ix_set_agent_sessions_set_id", "set_agent_sessions", ["set_id"])
    op.create_index("ix_set_agent_sessions_user_id", "set_agent_sessions", ["user_id"])

    op.create_table(
        "set_agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("set_agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("display_summary", sa.Text(), nullable=True),
        sa.Column("tool_calls_json", sa.Text(), nullable=True),
        sa.Column("affected_transition_scores_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_set_agent_messages_session_id", "set_agent_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_set_agent_messages_session_id", table_name="set_agent_messages")
    op.drop_table("set_agent_messages")
    op.drop_index("ix_set_agent_sessions_user_id", table_name="set_agent_sessions")
    op.drop_index("ix_set_agent_sessions_set_id", table_name="set_agent_sessions")
    op.drop_table("set_agent_sessions")
```

- [ ] **Step 6: Run a focused import/schema check**

Run:

```bash
cd server
.venv/bin/python - <<'PY'
from app.models import SetAgentMessage, SetAgentSession
print(SetAgentSession.__tablename__, SetAgentMessage.__tablename__)
PY
```

Expected: prints `set_agent_sessions set_agent_messages`.

- [ ] **Step 7: Commit**

Run:

```bash
git add server/app/models/set_agent.py server/app/models/set.py server/app/models/__init__.py \
  server/alembic/versions/060_add_set_agent_history.py server/tests/test_setbuilder_pass_api.py
git commit -m "feat: add setbuilder agent history persistence"
```

Expected: commit succeeds. The focused test still fails until Task 3 adds the endpoint.

## Task 2: Agent History Service + Compact Context

**Files:**
- Create: `server/app/services/setbuilder/agent_history.py`
- Modify: `server/app/services/setbuilder/pass2_agent.py`
- Test: `server/tests/test_setbuilder_pass2.py`

- [ ] **Step 1: Write failing service tests for bounded context and compaction**

Append these tests to `server/tests/test_setbuilder_pass2.py`:

```python
from app.services.llm.base import ChatRequest
from app.services.setbuilder import agent_history


def test_agent_context_uses_summary_and_recent_messages(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    session = agent_history.get_or_create_session(db, set_obj.id, test_user.id)
    session.context_summary = "Earlier: user asked for a softer cocktail section."
    for idx in range(8):
        agent_history.append_message(
            db,
            session,
            role="user" if idx % 2 == 0 else "assistant",
            content=f"turn {idx}",
        )

    messages = agent_history.context_messages(db, set_obj, session, "new request", recent_limit=3)

    assert "Earlier: user asked" in messages[1].content
    assert [m.content for m in messages[-4:]] == ["turn 5", "turn 6", "turn 7", "new request"]


def test_agent_compaction_updates_summary_without_gateway(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    session = agent_history.get_or_create_session(db, set_obj.id, test_user.id)
    for idx in range(agent_history.COMPACTION_TURN_THRESHOLD + 1):
        agent_history.append_message(
            db,
            session,
            role="assistant",
            content=f"assistant turn {idx}",
            display_summary=f"Moved Track {idx}.",
        )

    changed = agent_history.compact_if_needed(db, session)

    assert changed is True
    assert session.context_summary is not None
    assert "Moved Track 0." in session.context_summary
    assert session.compacted_through_message_id is not None
```

- [ ] **Step 2: Run the failing service tests**

Run:

```bash
cd server
.venv/bin/pytest \
  tests/test_setbuilder_pass2.py::test_agent_context_uses_summary_and_recent_messages \
  tests/test_setbuilder_pass2.py::test_agent_compaction_updates_summary_without_gateway \
  -q
```

Expected: FAIL because `agent_history` does not exist.

- [ ] **Step 3: Implement the history service**

Create `server/app/services/setbuilder/agent_history.py`:

```python
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


def get_or_create_session(db: Session, set_id: int, user_id: int) -> SetAgentSession:
    session = (
        db.query(SetAgentSession)
        .filter(SetAgentSession.set_id == set_id, SetAgentSession.user_id == user_id)
        .one_or_none()
    )
    if session is not None:
        return session
    session = SetAgentSession(set_id=set_id, user_id=user_id)
    db.add(session)
    db.commit()
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
    db.commit()
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
    recent = list_messages(db, session)[-recent_limit:]
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
    db.commit()
    db.refresh(session)
    return True


def decode_json_list(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else []
```

- [ ] **Step 4: Run the service tests**

Run:

```bash
cd server
.venv/bin/pytest \
  tests/test_setbuilder_pass2.py::test_agent_context_uses_summary_and_recent_messages \
  tests/test_setbuilder_pass2.py::test_agent_compaction_updates_summary_without_gateway \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add server/app/services/setbuilder/agent_history.py server/tests/test_setbuilder_pass2.py
git commit -m "feat: build compact set agent context"
```

Expected: commit succeeds.

## Task 3: Deterministic Tool Summaries

**Files:**
- Modify: `server/app/services/setbuilder/pass2_agent.py`
- Test: `server/tests/test_setbuilder_pass2.py`

- [ ] **Step 1: Write failing summary tests**

Append this test to `server/tests/test_setbuilder_pass2.py`:

```python
@pytest.mark.asyncio
async def test_agent_swap_returns_readable_tool_summary(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            text="",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="swap-1",
                    name="swap_slots",
                    input={
                        "slot_a_id": slots[0].id,
                        "slot_b_id": slots[1].id,
                        "rationale": "Start with the stronger groove.",
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    result = await chat_with_agent(db, test_user, set_obj, message="Swap the first two")

    assert result.message == "Swapped slot 1 Track 0 with slot 2 Track 1."
    assert result.tool_calls[0].display_summary == result.message
```

- [ ] **Step 2: Run the failing summary test**

Run:

```bash
cd server
.venv/bin/pytest tests/test_setbuilder_pass2.py::test_agent_swap_returns_readable_tool_summary -q
```

Expected: FAIL because `display_summary` does not exist and `message` is empty.

- [ ] **Step 3: Extend dataclasses**

In `server/app/services/setbuilder/pass2_agent.py`, add `display_summary` to `AppliedToolCall`:

```python
@dataclass(frozen=True)
class AppliedToolCall:
    id: str
    name: str
    args: dict[str, Any]
    rationale: str | None
    result: dict[str, Any]
    mutating: bool
    display_summary: str
```

- [ ] **Step 4: Add slot snapshot and summary helpers**

Add these helpers before `_agent_tools()` in `pass2_agent.py`:

```python
def _slot_snapshots(db: Session, set_obj: Set) -> dict[int, dict[str, Any]]:
    tracks = {_pass1_track_meta(t).slot_track_id: t for t in _pool_tracks(db, set_obj.id)}
    snapshots: dict[int, dict[str, Any]] = {}
    for slot in _ordered_slots(db, set_obj.id):
        track = tracks.get(slot.track_id or "")
        title = track.title if track else f"slot {slot.position + 1}"
        artist = track.artist if track else None
        label = f"{title} - {artist}" if artist else title
        snapshots[slot.id] = {
            "slot_id": slot.id,
            "position": slot.position,
            "track_id": slot.track_id,
            "label": label,
            "target_energy": slot.target_energy,
        }
    return snapshots


def _position_label(position: int) -> str:
    return f"slot {position + 1}"


def _tool_display_summary(
    name: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
) -> str:
    if name == "swap_slots":
        a = before.get(int(payload["slot_a_id"]))
        b = before.get(int(payload["slot_b_id"]))
        if a and b:
            return (
                f"Swapped {_position_label(a['position'])} {a['label']} with "
                f"{_position_label(b['position'])} {b['label']}."
            )
    if name == "reorder_slot":
        slot = before.get(int(payload["slot_id"]))
        if slot:
            return (
                f"Moved {slot['label']} from {_position_label(slot['position'])} to "
                f"{_position_label(int(result['position']))}."
            )
    if name == "remove_slot":
        removed = before.get(int(payload["slot_id"]))
        if removed:
            return f"Removed {removed['label']} from {_position_label(removed['position'])}."
    if name in {"insert_from_pool", "search_and_insert"}:
        position = int(result["position"])
        inserted = next((s for s in after.values() if s["position"] == position), None)
        label = inserted["label"] if inserted else "a pool track"
        return f"Added {label} at {_position_label(position)}."
    if name == "bump_energy":
        updated = int(result.get("updated") or 0)
        amount = float(payload["amount"])
        direction = "Raised" if amount >= 0 else "Lowered"
        return f"{direction} target energy by {abs(amount):g} across {updated} slot{'s' if updated != 1 else ''}."
    if name == "set_peak_at":
        position = int(payload["position"])
        slot = next((s for s in after.values() if s["position"] == position), None)
        label = f" {slot['label']}" if slot else ""
        return f"Set {_position_label(position)}{label} as the energy peak at {float(result['target_energy']):g}."
    if name == "add_slow_window":
        label = str(result.get("label") or "Slow window")
        return f"Added slow window {label} from {int(result['t0_sec'])}s to {int(result['t1_sec'])}s."
    if name == "analyze_transition":
        return f"Analyzed transition into {_position_label(int(result['position']))}: {round(float(result['score']))}."
    if name == "critique_set":
        return "Recomputed critique context."
    return name.replace("_", " ").capitalize() + "."
```

- [ ] **Step 5: Use snapshots during tool application**

In `chat_with_agent()`, replace the tool loop body with this shape:

```python
    for call in response.tool_calls:
        before = _slot_snapshots(db, set_obj)
        result, positions = apply_tool_call(db, set_obj, call.name, call.input)
        after = _slot_snapshots(db, set_obj)
        mutating = call.name in MUTATION_TOOLS
        summary = _tool_display_summary(call.name, call.input, result, before, after)
        applied.append(
            AppliedToolCall(
                id=call.id,
                name=call.name,
                args=call.input,
                rationale=call.input.get("rationale"),
                result=result,
                mutating=mutating,
                display_summary=summary,
            )
        )
        affected.update(positions)
```

Then compute the result message before returning:

```python
    message = response.text.strip() if response.text else ""
    if not message and applied:
        message = " ".join(tool.display_summary for tool in applied)
```

Use `message=message` in `AgentChatResult(...)`.

- [ ] **Step 6: Run summary tests and existing pass2 tests**

Run:

```bash
cd server
.venv/bin/pytest tests/test_setbuilder_pass2.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add server/app/services/setbuilder/pass2_agent.py server/tests/test_setbuilder_pass2.py
git commit -m "feat: summarize set agent tool actions"
```

Expected: commit succeeds.

## Task 4: Backend History API + Persisted Chat Turns

**Files:**
- Modify: `server/app/schemas/setbuilder.py`
- Modify: `server/app/api/setbuilder.py`
- Modify: `server/tests/test_setbuilder_pass_api.py`

- [ ] **Step 1: Write failing API tests**

Append these tests to `server/tests/test_setbuilder_pass_api.py`:

```python
def test_agent_chat_persists_turns_and_history(monkeypatch, client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_pool(db, set_obj["id"])
    built = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/build",
        json={"confirmed": True},
        headers=auth_headers,
    ).json()
    first, second = built["slots"][0], built["slots"][1]

    async def fake_dispatch(db_arg, actor, request, *, purpose):
        assert len([m for m in request.messages if m.content == "Earlier turn"]) == 0
        return ChatResponse(
            text="",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="swap-1",
                    name="swap_slots",
                    input={
                        "slot_a_id": first["id"],
                        "slot_b_id": second["id"],
                        "rationale": "Open with the better transition.",
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/chat",
        json={"message": "Swap the opener", "history": [{"role": "user", "content": "Earlier turn"}]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["message"].startswith("Swapped slot 1")
    assert body["tool_calls"][0]["display_summary"].startswith("Swapped slot 1")
    assert body["assistant_message"]["content"].startswith("Swapped slot 1")

    history = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=auth_headers,
    ).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][0]["content"] == "Swap the opener"
    assert history["messages"][1]["display_summary"].startswith("Swapped slot 1")


def test_agent_history_owner_isolation(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)

    from app.models.user import User
    from app.services.auth import get_password_hash
    from app.services.auth import create_access_token

    other = User(username="agentother", password_hash=get_password_hash("password1234"), role="dj")
    db.add(other)
    db.commit()
    token = create_access_token(data={"sub": other.username, "tv": other.token_version})
    other_headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/agent/history",
        headers=other_headers,
    )

    assert resp.status_code == 404
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
cd server
.venv/bin/pytest \
  tests/test_setbuilder_pass_api.py::test_agent_history_initially_empty_without_llm \
  tests/test_setbuilder_pass_api.py::test_agent_chat_persists_turns_and_history \
  tests/test_setbuilder_pass_api.py::test_agent_history_owner_isolation \
  -q
```

Expected: FAIL because schemas/endpoints are missing.

- [ ] **Step 3: Add response schemas**

In `server/app/schemas/setbuilder.py`, add these models after `AppliedToolCallOut`:

```python
class AgentChatMessageOut(BaseModel):
    """One persisted agent sidebar message."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    display_summary: str | None = None
    tool_calls: list[AppliedToolCallOut] = Field(default_factory=list)
    affected_transition_scores: list[TransitionScoreOut] = Field(default_factory=list)
    created_at: datetime


class AgentChatHistoryOut(BaseModel):
    """Persisted agent sidebar transcript and compact context metadata."""

    messages: list[AgentChatMessageOut]
    context_summary: str | None = None
    compacted_through_message_id: int | None = None
    uses_compact_context: bool = True
    recent_turn_limit: int
```

Add `display_summary` to `AppliedToolCallOut`:

```python
    display_summary: str
```

Add `assistant_message` to `AgentChatOut`:

```python
    assistant_message: AgentChatMessageOut
```

Ensure `datetime` is imported at the top of `setbuilder.py`:

```python
from datetime import datetime
```

- [ ] **Step 4: Add API imports and serialization helpers**

In `server/app/api/setbuilder.py`, add imports from schemas:

```python
    AgentChatHistoryOut,
    AgentChatMessageOut,
```

Add the service import:

```python
    agent_history,
```

Add this helper near `_transition_scores_out`:

```python
def _agent_message_out(message) -> AgentChatMessageOut:  # noqa: ANN001
    return AgentChatMessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        display_summary=message.display_summary,
        tool_calls=[
            AppliedToolCallOut(**tool)
            for tool in agent_history.decode_json_list(message.tool_calls_json)
        ],
        affected_transition_scores=[
            TransitionScoreOut(**score)
            for score in agent_history.decode_json_list(message.affected_transition_scores_json)
        ],
        created_at=message.created_at,
    )
```

- [ ] **Step 5: Add the history endpoint**

Add this endpoint before `chat_with_set_agent`:

```python
@router.get("/sets/{set_id}/agent/history", response_model=AgentChatHistoryOut)
@limiter.limit("60/minute")
def get_set_agent_history(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentChatHistoryOut:
    """Load persisted agent sidebar history without dispatching an LLM call."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    session = agent_history.get_or_create_session(db, set_obj.id, current_user.id)
    return AgentChatHistoryOut(
        messages=[_agent_message_out(m) for m in agent_history.list_messages(db, session)],
        context_summary=session.context_summary,
        compacted_through_message_id=session.compacted_through_message_id,
        recent_turn_limit=agent_history.RECENT_CONTEXT_TURN_LIMIT,
    )
```

- [ ] **Step 6: Persist chat turns in the chat endpoint**

In `chat_with_set_agent`, before calling `pass2_agent.chat_with_agent`, load the session:

```python
    session = agent_history.get_or_create_session(db, set_obj.id, current_user.id)
```

Replace the `pass2_agent.chat_with_agent(...)` call with:

```python
        result = await pass2_agent.chat_with_agent(
            db,
            current_user,
            set_obj,
            message=payload.message,
            messages=agent_history.context_messages(db, set_obj, session, payload.message),
        )
```

After the LLM result and before returning, persist the messages:

```python
    agent_history.append_message(db, session, role="user", content=payload.message)
    tool_call_payloads = [
        {
            "id": t.id,
            "name": t.name,
            "args": t.args,
            "rationale": t.rationale,
            "result": t.result,
            "mutating": t.mutating,
            "display_summary": t.display_summary,
        }
        for t in result.tool_calls
    ]
    score_payloads = [
        {
            "slot_id": s.slot_id,
            "position": s.position,
            "score": s.score,
            "warnings": s.warnings,
        }
        for s in result.affected_transition_scores
    ]
    assistant_message = agent_history.append_message(
        db,
        session,
        role="assistant",
        content=result.message,
        display_summary=result.message,
        tool_calls=tool_call_payloads,
        affected_transition_scores=score_payloads,
    )
    agent_history.compact_if_needed(db, session)
```

In the returned `AgentChatOut`, include `display_summary` and `assistant_message`:

```python
        tool_calls=[
            AppliedToolCallOut(
                id=t.id,
                name=t.name,
                args=t.args,
                rationale=t.rationale,
                result=t.result,
                mutating=t.mutating,
                display_summary=t.display_summary,
            )
            for t in result.tool_calls
        ],
        assistant_message=_agent_message_out(assistant_message),
```

- [ ] **Step 7: Let `chat_with_agent` accept server-built messages**

In `server/app/services/setbuilder/pass2_agent.py`, change the function signature:

```python
async def chat_with_agent(
    db: Session,
    actor: User,
    set_obj: Set,
    *,
    message: str,
    history: list[dict[str, str]] | None = None,
    messages: list[Message] | None = None,
) -> AgentChatResult:
```

Replace the initial message construction with:

```python
    if messages is None:
        messages = [Message(role="user", content=_set_context(db, set_obj))]
        for item in history or []:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                messages.append(Message(role=role, content=content))
        messages.append(Message(role="user", content=message))
```

Keep `history` only for backwards-compatible tests and callers; the API endpoint now passes `messages`.

- [ ] **Step 8: Run API tests**

Run:

```bash
cd server
.venv/bin/pytest tests/test_setbuilder_pass_api.py tests/test_setbuilder_pass2.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add server/app/schemas/setbuilder.py server/app/api/setbuilder.py \
  server/app/services/setbuilder/pass2_agent.py server/tests/test_setbuilder_pass_api.py
git commit -m "feat: persist set agent chat turns"
```

Expected: commit succeeds.

## Task 5: Regenerate API Types + Client Methods

**Files:**
- Modify: `server/openapi.json`
- Modify: `dashboard/lib/api-types.generated.ts`
- Modify: `dashboard/lib/api-types.ts`
- Modify: `dashboard/lib/api.ts`
- Test: `dashboard/lib/__tests__/api.test.ts`

- [ ] **Step 1: Write failing API client test**

In `dashboard/lib/__tests__/api.test.ts`, update the setbuilder two-pass test so chat sends only a message, and add a history fetch assertion:

```typescript
    it('loads agent history and sends chat turns without client history', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            messages: [],
            context_summary: null,
            compacted_through_message_id: null,
            uses_compact_context: true,
            recent_turn_limit: 12,
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            message: 'Swapped slot 1 Track A with slot 2 Track B.',
            assistant_message: {
              id: 2,
              role: 'assistant',
              content: 'Swapped slot 1 Track A with slot 2 Track B.',
              display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
              tool_calls: [],
              affected_transition_scores: [],
              created_at: '2026-06-15T00:00:00Z',
            },
            tool_calls: [],
            slots: [],
            affected_transition_scores: [],
          }),
        });

      const history = await api.getSetAgentHistory(42);
      const chat = await api.chatWithSetAgent(42, { message: 'Swap these' });

      expect(history.uses_compact_context).toBe(true);
      expect(chat.message).toContain('Swapped slot 1');
      const [historyUrl] = mockFetch.mock.calls[0];
      expect(historyUrl).toContain('/api/setbuilder/sets/42/agent/history');
      const [chatUrl, chatOptions] = mockFetch.mock.calls[1];
      expect(chatUrl).toContain('/api/setbuilder/sets/42/agent/chat');
      expect(JSON.parse(chatOptions.body)).toEqual({ message: 'Swap these' });
    });
```

Remove the older expectation that `chatWithSetAgent` sends a `history` array.

- [ ] **Step 2: Run the failing API client test**

Run:

```bash
cd dashboard
npm test -- --run lib/__tests__/api.test.ts
```

Expected: FAIL because `getSetAgentHistory` does not exist and generated types are stale.

- [ ] **Step 3: Regenerate OpenAPI and TypeScript types**

Run:

```bash
cd dashboard
npm run types:export
npm run types:generate
```

Expected: `server/openapi.json` and `dashboard/lib/api-types.generated.ts` update with `AgentChatHistoryOut` and `AgentChatMessageOut`.

- [ ] **Step 4: Re-export the new types**

In `dashboard/lib/api-types.ts`, update the WrzDJSet two-pass section:

```typescript
export type AgentChatIn = Schemas['AgentChatIn'];
export type AgentChatOut = Schemas['AgentChatOut'];
export type AgentChatHistory = Schemas['AgentChatHistoryOut'];
export type AgentChatMessage = Schemas['AgentChatMessageOut'];
export type AppliedToolCall = Schemas['AppliedToolCallOut'];
export type TransitionScore = Schemas['TransitionScoreOut'];
```

- [ ] **Step 5: Add the API client method**

In `dashboard/lib/api.ts`, add the type imports if needed:

```typescript
  AgentChatHistory,
```

Near `critiqueSet()` and `chatWithSetAgent()`, add:

```typescript
  async getSetAgentHistory(setId: number): Promise<AgentChatHistory> {
    return this.fetch(`/api/setbuilder/sets/${setId}/agent/history`);
  }
```

Keep `chatWithSetAgent` using the generated `AgentChatIn`, but callers should pass only `{ message }`.

- [ ] **Step 6: Run the API client test**

Run:

```bash
cd dashboard
npm test -- --run lib/__tests__/api.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add server/openapi.json dashboard/lib/api-types.generated.ts dashboard/lib/api-types.ts \
  dashboard/lib/api.ts dashboard/lib/__tests__/api.test.ts
git commit -m "feat: expose set agent history client API"
```

Expected: commit succeeds.

## Task 6: Sidebar UI History + Readable Returns

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/ChatSidebar.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/setbuilder.module.css`

- [ ] **Step 1: Write failing ChatSidebar tests**

Replace the mutating-turn test in `ChatSidebar.test.tsx` with expectations for readable summaries and add history loading:

```typescript
  it('loads persisted history without rendering raw tool JSON', async () => {
    mockApi.getSetAgentHistory.mockResolvedValue({
      messages: [
        {
          id: 1,
          role: 'user',
          content: 'swap the opener',
          display_summary: null,
          tool_calls: [],
          affected_transition_scores: [],
          created_at: '2026-06-15T00:00:00Z',
        },
        {
          id: 2,
          role: 'assistant',
          content: 'Swapped slot 1 Track A with slot 2 Track B.',
          display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
          tool_calls: [
            {
              id: 'swap-1',
              name: 'swap_slots',
              args: { slot_a_id: 1, slot_b_id: 2 },
              rationale: 'Better opener',
              result: { slot_a_id: 1, slot_b_id: 2 },
              mutating: true,
              display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
            },
          ],
          affected_transition_scores: [],
          created_at: '2026-06-15T00:00:01Z',
        },
      ],
      context_summary: 'Earlier: the set should start softer.',
      compacted_through_message_id: 2,
      uses_compact_context: true,
      recent_turn_limit: 12,
    });

    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={vi.fn()} />);

    expect(await screen.findByText('swap the opener')).toBeInTheDocument();
    expect(screen.getByText('Swapped slot 1 Track A with slot 2 Track B.')).toBeInTheDocument();
    expect(screen.queryByText(/"slot_a_id"/)).not.toBeInTheDocument();
    expect(screen.getByText(/compact context/i)).toBeInTheDocument();
  });

  it('posts only the new message and renders returned summaries', async () => {
    mockApi.getSetAgentHistory.mockResolvedValue({
      messages: [],
      context_summary: null,
      compacted_through_message_id: null,
      uses_compact_context: true,
      recent_turn_limit: 12,
    });
    mockApi.chatWithSetAgent.mockResolvedValue({
      message: 'Swapped slot 1 Track A with slot 2 Track B.',
      assistant_message: {
        id: 2,
        role: 'assistant',
        content: 'Swapped slot 1 Track A with slot 2 Track B.',
        display_summary: 'Swapped slot 1 Track A with slot 2 Track B.',
        tool_calls: [],
        affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
        created_at: '2026-06-15T00:00:01Z',
      },
      tool_calls: [],
      slots: [],
      affected_transition_scores: [{ slot_id: 2, position: 1, score: 88, warnings: [] }],
    });

    const onMutationApplied = vi.fn();
    render(<ChatSidebar setId={9} open onToggle={vi.fn()} onMutationApplied={onMutationApplied} />);
    await screen.findByTestId('critique-card');

    fireEvent.change(screen.getByPlaceholderText(/tell the agent/i), {
      target: { value: 'swap the opener' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(mockApi.chatWithSetAgent).toHaveBeenCalledWith(9, { message: 'swap the opener' }));
    expect(await screen.findByText('Swapped slot 1 Track A with slot 2 Track B.')).toBeInTheDocument();
    expect(screen.queryByText(/"slot_a_id"/)).not.toBeInTheDocument();
  });
```

Update the `mockApi` hoist to include `getSetAgentHistory: vi.fn()`.

- [ ] **Step 2: Run failing ChatSidebar tests**

Run:

```bash
cd dashboard
npm test -- --run 'app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx'
```

Expected: FAIL because the component does not load persisted history and still renders raw JSON.

- [ ] **Step 3: Update `ChatEntry` and history load**

In `ChatSidebar.tsx`, import new types:

```typescript
import type {
  AgentChatMessage,
  AppliedToolCall,
  SetCritique,
  TransitionScore,
} from '@/lib/api-types';
```

Replace `ChatEntry` with:

```typescript
type ChatEntry = Pick<
  AgentChatMessage,
  'id' | 'role' | 'content' | 'display_summary' | 'tool_calls' | 'affected_transition_scores'
> & { pending?: boolean };
```

Add state:

```typescript
  const [historyMeta, setHistoryMeta] = useState<{
    usesCompactContext: boolean;
    recentTurnLimit: number;
  } | null>(null);
```

Add the history loader effect after the critique effect:

```typescript
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .getSetAgentHistory(setId)
      .then((history) => {
        if (cancelled) return;
        setEntries(history.messages);
        setHistoryMeta({
          usesCompactContext: history.uses_compact_context,
          recentTurnLimit: history.recent_turn_limit,
        });
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Agent history unavailable');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, setId]);
```

Remove the `useMemo` history builder and the `history` payload from `send()`.

- [ ] **Step 4: Update send logic**

In `send()`, replace optimistic append and API call with:

```typescript
    const pendingEntry: ChatEntry = {
      id: -Date.now(),
      role: 'user',
      content: message,
      display_summary: null,
      tool_calls: [],
      affected_transition_scores: [],
      pending: true,
    };
    setEntries((prev) => [...prev, pendingEntry]);
    setInput('');
    setBusy(true);
    setError(null);
    try {
      const result = await api.chatWithSetAgent(setId, { message });
      setEntries((prev) => [
        ...prev.filter((entry) => entry.id !== pendingEntry.id),
        {
          id: pendingEntry.id,
          role: 'user',
          content: message,
          display_summary: null,
          tool_calls: [],
          affected_transition_scores: [],
        },
        result.assistant_message,
      ]);
      if (result.tool_calls.some((tool) => tool.mutating)) onMutationApplied();
    } catch (err) {
      setEntries((prev) => prev.filter((entry) => entry.id !== pendingEntry.id));
      setError(err instanceof Error ? err.message : 'Agent request failed');
    } finally {
      setBusy(false);
    }
```

- [ ] **Step 5: Replace `ToolCard` raw JSON rendering**

Replace `ToolCard` with:

```typescript
function ToolCard({ tool }: { tool: AppliedToolCall }) {
  return (
    <div className={styles.toolCallCard} data-testid="agent-tool-card">
      <span className={styles.toolName}>{tool.name.replaceAll('_', ' ')}</span>
      <div className={styles.toolBody}>
        <div className={styles.toolSummary}>{tool.display_summary}</div>
        {tool.rationale && <div className={styles.toolRationale}>{tool.rationale}</div>}
      </div>
    </div>
  );
}
```

Update render references:

```tsx
            <div className={styles.chatBubble}>{entry.display_summary || entry.content}</div>
            {entry.tool_calls?.map((tool) => <ToolCard key={tool.id} tool={tool} />)}
            {entry.affected_transition_scores && entry.affected_transition_scores.length > 0 && (
```

Add a compact-context status line below the header:

```tsx
      {historyMeta && (
        <div className={styles.chatContextMeta}>
          {historyMeta.usesCompactContext
            ? `Uses compact context + last ${historyMeta.recentTurnLimit} turns`
            : 'Uses recent turns'}
        </div>
      )}
```

- [ ] **Step 6: Harden sidebar viewport CSS**

In `setbuilder.module.css`, update/add:

```css
.panelChat {
  grid-area: chat;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.chatSection {
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--bg);
}

.chatContextMeta {
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg);
  color: var(--text-tertiary, var(--text-secondary));
  font-size: 0.6875rem;
  line-height: 1.35;
}

.toolSummary {
  color: var(--text);
  font-size: 0.75rem;
  line-height: 1.4;
}
```

Remove or leave unused `.toolArgs`; do not render it.

- [ ] **Step 7: Run ChatSidebar tests**

Run:

```bash
cd dashboard
npm test -- --run 'app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx'
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add 'dashboard/app/(dj)/setbuilder/components/ChatSidebar.tsx' \
  'dashboard/app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx' \
  'dashboard/app/(dj)/setbuilder/setbuilder.module.css'
git commit -m "feat: persist and render set agent sidebar history"
```

Expected: commit succeeds.

## Task 7: Verification + Drift Checks

**Files:**
- Potential generated drift: `server/openapi.json`, `dashboard/lib/api-types.generated.ts`
- No new source files unless checks reveal a focused fix.

- [ ] **Step 1: Backend focused checks**

Run:

```bash
cd server
.venv/bin/ruff check app tests/test_setbuilder_pass_api.py tests/test_setbuilder_pass2.py
.venv/bin/ruff format --check app tests/test_setbuilder_pass_api.py tests/test_setbuilder_pass2.py
.venv/bin/pytest tests/test_setbuilder_pass_api.py tests/test_setbuilder_pass2.py --tb=short -q
```

Expected: all commands pass.

- [ ] **Step 2: Frontend focused checks**

Run:

```bash
cd dashboard
npm run lint
npx tsc --noEmit
npm test -- --run 'app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx' lib/__tests__/api.test.ts
```

Expected: all commands pass.

- [ ] **Step 3: Migration drift check**

Run:

```bash
cd server
.venv/bin/alembic upgrade head
.venv/bin/alembic check
```

Expected: upgrade succeeds and `alembic check` reports no new upgrade operations.

- [ ] **Step 4: Full required backend checks**

Run:

```bash
cd server
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
```

Expected: all pass; pytest coverage remains at or above the enforced gate.

- [ ] **Step 5: Final status**

Run:

```bash
git status --short
```

Expected: clean worktree.

If the worktree is not clean, return to the task that introduced the drift,
make the smallest focused correction there, rerun that task's verification
command, and commit that task's exact files before repeating Task 7.

## Self-Review Checklist

- Spec coverage:
  - Server-side per DJ + set history: Tasks 1, 2, 4.
  - No LLM calls on load: Task 4 API test.
  - Backend-owned context and compaction: Task 2 and Task 4.
  - No raw JSON in sidebar returns: Task 3 and Task 6.
  - Independent sidebar viewport: Task 6 CSS.
  - Current LLM memory behavior documented and implemented as bounded messages: Task 2.
- Red-flag scan: no banned marker strings, no future-only implementation steps, and no unspecified test commands.
- Type consistency:
  - `display_summary` is added to backend dataclass, Pydantic schema, generated TS type, and UI rendering.
  - `AgentChatHistoryOut`/`AgentChatMessageOut` are exported to `dashboard/lib/api-types.ts`.
  - `chatWithSetAgent` keeps `AgentChatIn`, but frontend sends only `{ message }`; backend ignores legacy `history`.

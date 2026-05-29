# Per-Feature Connector Preference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each DJ pin a specific LLM connector to a specific agentic feature (e.g. recommendation → connector A, set_builder → connector B), with graceful fallback when the pinned connector is gone or auth-invalid.

**Architecture:** A new `LlmFeaturePreference` table maps `(user_id, feature) → connector_id` with a UNIQUE constraint. `Gateway.dispatch` already receives `purpose` (the feature key), so resolution gains a new first step: look up the DJ's pinned connector for `purpose`, use it if active, else fall through to the existing chain (per-DJ default → MRU → org default → `NoLlmConfigured`). New `/api/llm/feature-preferences` endpoints (set/clear/list) are scoped to the current DJ and validate connector ownership + feature against an allowlist. The DJ AI settings UI gains a "Per-feature defaults" section.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, slowapi, Pydantic v2, Next.js/React 19/TypeScript, vitest.

---

## File Structure

**Backend (create):**
- `server/app/models/llm_feature_preference.py` — the new model + feature allowlist constants.
- `server/alembic/versions/050_llm_feature_preference.py` — migration (down_revision = `049`).
- `server/tests/test_llm_feature_preference.py` — model + gateway resolution + endpoint tests.

**Backend (modify):**
- `server/app/models/__init__.py` — register `LlmFeaturePreference`.
- `server/app/services/llm/connector_storage.py` — feature-preference CRUD helpers.
- `server/app/services/llm/gateway.py` — add feature-preference as the first resolution step.
- `server/app/api/llm.py` — set/clear/list feature-preference endpoints.
- `server/app/schemas/llm.py` — request/response schemas + known-feature constant.

**Frontend (modify):**
- `dashboard/lib/api.ts` — `listFeaturePreferences`, `setFeaturePreference`, `clearFeaturePreference`.
- `dashboard/components/AiProvidersSection.tsx` — "Per-feature defaults" section.
- `dashboard/lib/api-types.ts` — re-export the new generated schema types.
- `dashboard/lib/api-types.generated.ts` — regenerated from OpenAPI (via `npm run types:export && npm run types:generate`).

**Design decisions (locked in):**
- Feature key reuses the gateway `purpose` string. Known features allowlist: `{"recommendation", "set_builder"}`. `recommendation` is the only `purpose` in use today; `set_builder` is named in the issue spec for an upcoming feature. The allowlist lives in one place (`schemas/llm.py`) and is imported by both the API validation and the model docstring reference.
- The endpoint surface is `POST /api/llm/feature-preferences` (upsert set), `DELETE /api/llm/feature-preferences/{feature}` (clear), `GET /api/llm/feature-preferences` (list). Upsert semantics keep "set" and "change" as one operation (the UNIQUE constraint makes change == replace).
- Ownership: setting a preference validates the connector belongs to the current DJ (404 if not, mirroring the existing connector-ownership 404 convention so another DJ's connector existence is never leaked).
- Graceful fallback: gateway resolution skips a pinned preference whose connector is deleted (FK row gone) or whose status != `active`. No exception — falls through to the next resolution step.
- We do NOT add a frontend "set inactive connector" guard beyond what the picker offers; the gateway already skips inactive pins, and the API rejects pinning a non-active connector with 400 (mirrors the per-DJ default endpoint), so a DJ can't silently break their own routing.

---

## Task 1: LlmFeaturePreference model + feature allowlist

**Files:**
- Create: `server/app/models/llm_feature_preference.py`
- Modify: `server/app/models/__init__.py`
- Test: `server/tests/test_llm_feature_preference.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_llm_feature_preference.py`:

```python
"""Tests for per-feature connector preference (issue #337)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.llm_connector import LlmConnector
from app.models.llm_feature_preference import KNOWN_FEATURES, LlmFeaturePreference
from app.models.user import User
from app.services.auth import get_password_hash


@pytest.fixture
def dj_user(db) -> User:
    user = User(
        username="prefdj",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(db, user, *, display_name="Pref connector", status="active"):
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name=display_name,
        status=status,
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint="gpt-5-mini",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_known_features_contains_recommendation_and_set_builder():
    assert "recommendation" in KNOWN_FEATURES
    assert "set_builder" in KNOWN_FEATURES


def test_unique_constraint_one_pref_per_user_feature(db, dj_user):
    c1 = _make_connector(db, dj_user, display_name="A")
    c2 = _make_connector(db, dj_user, display_name="B")
    db.add(
        LlmFeaturePreference(user_id=dj_user.id, feature="recommendation", connector_id=c1.id)
    )
    db.commit()
    db.add(
        LlmFeaturePreference(user_id=dj_user.id, feature="recommendation", connector_id=c2.id)
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.llm_feature_preference'`

- [ ] **Step 3: Write the model**

Create `server/app/models/llm_feature_preference.py`:

```python
"""Per-feature connector preference — pins a DJ's connector to a feature.

A DJ can pin the recommendation engine to one connector and the set-builder
to another. The gateway consults this table first (keyed by ``purpose``)
before falling back to the per-DJ default / MRU / org-default chain.

See issue #337, spec §11.8.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Allowlist of feature keys a DJ may pin. These mirror the gateway ``purpose``
# strings. ``recommendation`` is the only purpose dispatched today;
# ``set_builder`` is reserved for the upcoming set-builder feature (issue spec
# §11.8). Validation of API input against this set lives in ``schemas/llm.py``
# (KNOWN_FEATURES is re-exported there to keep a single source of truth).
KNOWN_FEATURES = frozenset({"recommendation", "set_builder"})


class LlmFeaturePreference(Base):
    """Maps ``(user_id, feature)`` to a pinned ``connector_id``.

    At most one row per ``(user_id, feature)`` — enforced by a UNIQUE
    constraint. Deleting the connector cascades (ON DELETE CASCADE) so a stale
    preference never points at a missing connector.
    """

    __tablename__ = "llm_feature_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    feature: Mapped[str] = mapped_column(String(40), nullable=False)
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("llm_connectors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "feature", name="uq_llm_feature_pref_user_feature"),
    )
```

- [ ] **Step 4: Register the model**

Modify `server/app/models/__init__.py` — add the import after the `llm_connector` import line and the name to `__all__` (alphabetical-ish, keep grouped with other Llm names):

```python
from app.models.llm_connector import LlmAuditEvent, LlmCallLog, LlmConnector
from app.models.llm_feature_preference import LlmFeaturePreference
```

And add `"LlmFeaturePreference",` to the `__all__` list (right after `"LlmConnector",`).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add server/app/models/llm_feature_preference.py server/app/models/__init__.py server/tests/test_llm_feature_preference.py
git commit -m "feat(llm): add LlmFeaturePreference model + feature allowlist"
```

---

## Task 2: Alembic migration

**Files:**
- Create: `server/alembic/versions/050_llm_feature_preference.py`

- [ ] **Step 1: Write the migration**

Create `server/alembic/versions/050_llm_feature_preference.py`:

```python
"""Add llm_feature_preferences table.

Revision ID: 050
Revises: 049
Create Date: 2026-05-28

Per-feature connector preference (issue #337). Maps ``(user_id, feature)`` to a
pinned ``connector_id`` with a UNIQUE constraint so a DJ has at most one pinned
connector per feature. Both FKs cascade on delete so a deleted user or
connector never leaves a dangling preference.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_feature_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=40), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["llm_connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "feature", name="uq_llm_feature_pref_user_feature"),
    )
    op.create_index(
        "ix_llm_feature_preferences_user_id",
        "llm_feature_preferences",
        ["user_id"],
    )
    op.create_index(
        "ix_llm_feature_preferences_connector_id",
        "llm_feature_preferences",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_feature_preferences_connector_id", table_name="llm_feature_preferences")
    op.drop_index("ix_llm_feature_preferences_user_id", table_name="llm_feature_preferences")
    op.drop_table("llm_feature_preferences")
```

- [ ] **Step 2: Run migration + drift check**

Run: `cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check`
Expected: `upgrade` runs cleanly to revision `050`, and `alembic check` prints `No new upgrade operations detected.`

If `alembic check` reports drift, reconcile the migration columns/indexes with the model (`index=True` on `user_id` and `connector_id` matches the two `create_index` calls).

- [ ] **Step 3: Commit**

```bash
git add server/alembic/versions/050_llm_feature_preference.py
git commit -m "feat(llm): migration 050 for llm_feature_preferences"
```

---

## Task 3: connector_storage CRUD helpers

**Files:**
- Modify: `server/app/services/llm/connector_storage.py`
- Test: `server/tests/test_llm_feature_preference.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_feature_preference.py`:

```python
def test_set_feature_preference_upserts(db, dj_user):
    from app.services.llm.connector_storage import (
        get_feature_preferences_for_user,
        set_feature_preference,
    )

    c1 = _make_connector(db, dj_user, display_name="A")
    c2 = _make_connector(db, dj_user, display_name="B")

    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=c1.id)
    db.commit()
    prefs = get_feature_preferences_for_user(db, dj_user.id)
    assert {p.feature: p.connector_id for p in prefs} == {"recommendation": c1.id}

    # Re-set the same feature → replace, not duplicate.
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=c2.id)
    db.commit()
    prefs = get_feature_preferences_for_user(db, dj_user.id)
    assert {p.feature: p.connector_id for p in prefs} == {"recommendation": c2.id}


def test_clear_feature_preference_removes_row(db, dj_user):
    from app.services.llm.connector_storage import (
        clear_feature_preference,
        get_feature_preferences_for_user,
        set_feature_preference,
    )

    c1 = _make_connector(db, dj_user, display_name="A")
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=c1.id)
    db.commit()

    removed = clear_feature_preference(db, user_id=dj_user.id, feature="recommendation")
    db.commit()
    assert removed is True
    assert get_feature_preferences_for_user(db, dj_user.id) == []

    # Clearing a non-existent preference is a no-op (returns False).
    assert clear_feature_preference(db, user_id=dj_user.id, feature="recommendation") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q`
Expected: FAIL with `ImportError: cannot import name 'set_feature_preference'`

- [ ] **Step 3: Add the helpers**

In `server/app/services/llm/connector_storage.py`, add the model import to the existing `from app.models.llm_connector import (...)` block is NOT possible (different module). Add a new import near the top imports:

```python
from app.models.llm_feature_preference import LlmFeaturePreference
```

Then add these functions (place them after `unset_default_for_user`):

```python
def get_feature_preferences_for_user(db: Session, user_id: int) -> list[LlmFeaturePreference]:
    """Return all of a DJ's per-feature connector pins."""
    return (
        db.query(LlmFeaturePreference)
        .filter(LlmFeaturePreference.user_id == user_id)
        .order_by(LlmFeaturePreference.feature.asc())
        .all()
    )


def get_feature_preference(
    db: Session, *, user_id: int, feature: str
) -> LlmFeaturePreference | None:
    """Return the DJ's pin for ``feature``, or ``None`` if unset."""
    return (
        db.query(LlmFeaturePreference)
        .filter(
            LlmFeaturePreference.user_id == user_id,
            LlmFeaturePreference.feature == feature,
        )
        .one_or_none()
    )


def set_feature_preference(
    db: Session, *, user_id: int, feature: str, connector_id: int
) -> LlmFeaturePreference:
    """Upsert the DJ's pin for ``feature`` → ``connector_id``. Caller commits.

    Replace-in-place when a row already exists so the UNIQUE constraint on
    ``(user_id, feature)`` is never violated.
    """
    existing = get_feature_preference(db, user_id=user_id, feature=feature)
    if existing is not None:
        existing.connector_id = connector_id
        db.flush()
        return existing
    row = LlmFeaturePreference(user_id=user_id, feature=feature, connector_id=connector_id)
    db.add(row)
    db.flush()
    return row


def clear_feature_preference(db: Session, *, user_id: int, feature: str) -> bool:
    """Delete the DJ's pin for ``feature``. Returns True iff a row was removed.

    Caller commits.
    """
    existing = get_feature_preference(db, user_id=user_id, feature=feature)
    if existing is None:
        return False
    db.delete(existing)
    db.flush()
    return True
```

Add the four function names to the `__all__` list alphabetically:
`"clear_feature_preference",`, `"get_feature_preference",`, `"get_feature_preferences_for_user",`, `"set_feature_preference",`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/connector_storage.py server/tests/test_llm_feature_preference.py
git commit -m "feat(llm): feature-preference CRUD helpers in connector_storage"
```

---

## Task 4: Gateway resolution — feature preference first

**Files:**
- Modify: `server/app/services/llm/gateway.py`
- Test: `server/tests/test_llm_feature_preference.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_feature_preference.py`:

```python
from unittest.mock import AsyncMock, patch  # noqa: E402  (grouped with gateway tests)

from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter  # noqa: E402
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage  # noqa: E402
from app.services.llm.gateway import Gateway  # noqa: E402


def _ok_response() -> ChatResponse:
    return ChatResponse(
        text="ok", tool_calls=[], stop_reason="end_turn", usage=TokenUsage(prompt=1, completion=1)
    )


@pytest.mark.asyncio
async def test_gateway_prefers_feature_pin_over_default(db, dj_user):
    from app.services.llm.connector_storage import set_default_for_user, set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned")
    other = _make_connector(db, dj_user, display_name="default")
    set_default_for_user(db, connector=other)  # per-DJ default points elsewhere
    set_feature_preference(
        db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id
    )
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="recommendation",
        )
    assert captured["connector_id"] == pinned.id


@pytest.mark.asyncio
async def test_gateway_falls_back_when_pinned_connector_auth_invalid(db, dj_user):
    from app.services.llm.connector_storage import set_default_for_user, set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned", status="auth_invalid")
    fallback = _make_connector(db, dj_user, display_name="fallback")
    set_default_for_user(db, connector=fallback)
    set_feature_preference(
        db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id
    )
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="recommendation",
        )
    # Skips the auth_invalid pin, falls through to the per-DJ default.
    assert captured["connector_id"] == fallback.id


@pytest.mark.asyncio
async def test_gateway_ignores_pin_for_unknown_feature(db, dj_user):
    """A pin set for one feature must not leak into another purpose."""
    from app.services.llm.connector_storage import set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned")
    mru = _make_connector(db, dj_user, display_name="mru")
    set_feature_preference(
        db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id
    )
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="set_builder",
        )
    # No pin for set_builder → MRU resolution (most recently created here is `mru`).
    assert captured["connector_id"] == mru.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q -k gateway`
Expected: FAIL — the pin is ignored because `_resolve_connector` doesn't know about `purpose`.

- [ ] **Step 3: Thread purpose into resolution**

In `server/app/services/llm/gateway.py`:

Add the storage import near the existing imports:

```python
from app.services.llm.connector_storage import audit_event, get_feature_preference, log_call
```

(modify the existing `from app.services.llm.connector_storage import audit_event, log_call` line)

In `Gateway.dispatch`, change the resolve call to pass `purpose`:

```python
        primary = _resolve_connector(db, actor, purpose=purpose)
```

Update `_resolve_connector`'s signature and add the feature-preference step as the FIRST check inside the `if actor is not None:` block:

```python
def _resolve_connector(db: Session, actor: User | None, *, purpose: str) -> LlmConnector:
    if actor is not None:
        # 0. Per-feature pin (issue #337) takes precedence over the per-DJ
        #    default and MRU. Skipped gracefully when the pinned connector was
        #    deleted (FK row gone) or is no longer active, so a stale/broken
        #    pin never silently breaks the DJ — resolution falls through.
        pref = get_feature_preference(db, user_id=actor.id, feature=purpose)
        if pref is not None:
            pinned = db.get(LlmConnector, pref.connector_id)
            if (
                pinned is not None
                and pinned.user_id == actor.id
                and pinned.status == STATUS_ACTIVE
            ):
                return pinned

        # Per-DJ explicit default takes precedence over MRU (issue #336).
        ...
```

(Leave the rest of `_resolve_connector` unchanged — the `pinned` default block, the MRU block, the org-default fallback.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q -k gateway`
Expected: PASS

Then run the full gateway suite to confirm no regression:
Run: `cd server && .venv/bin/pytest tests/test_llm_gateway.py tests/test_llm_default_connector.py -q`
Expected: PASS

- [ ] **Step 5: Update gateway module docstring**

In `server/app/services/llm/gateway.py`, update the "Resolution order" docstring at the top to list the feature-preference step first:

```
Resolution order:
1. If ``actor`` is not ``None``:
   a. The DJ's per-feature pin for ``purpose`` if set and the pinned connector
      is active (``LlmFeaturePreference`` — issue #337).
   b. Else: the DJ's explicit default active connector if one is pinned
      (``LlmConnector.is_default = True``) — issue #336.
   c. Else: most-recently-used active connector for the DJ.
2. Else: ``SystemSettings.llm_default_connector_id`` if set and active.
3. Else: raise :class:`NoLlmConfigured`.
```

- [ ] **Step 6: Commit**

```bash
git add server/app/services/llm/gateway.py server/tests/test_llm_feature_preference.py
git commit -m "feat(llm): gateway resolves per-feature pin first, falls back gracefully"
```

---

## Task 5: API schemas

**Files:**
- Modify: `server/app/schemas/llm.py`

- [ ] **Step 1: Add the schemas + feature literal**

In `server/app/schemas/llm.py`, after the existing imports add the known-feature import + a `Literal`-derived alias. Near the top (after `from typing import Literal`):

```python
from app.models.llm_feature_preference import KNOWN_FEATURES

# Sorted tuple so the OpenAPI enum + frontend list are deterministic.
KNOWN_FEATURE_VALUES: tuple[str, ...] = tuple(sorted(KNOWN_FEATURES))
FeatureKey = Literal["recommendation", "set_builder"]
```

At the end of the file add:

```python
class FeaturePreferenceOut(BaseModel):
    """A single per-feature connector pin."""

    model_config = ConfigDict(from_attributes=True)

    feature: FeatureKey
    connector_id: int


class FeaturePreferencesListOut(BaseModel):
    """All of a DJ's per-feature pins + the catalogue of pinnable features."""

    preferences: list[FeaturePreferenceOut]
    known_features: list[FeatureKey]


class FeaturePreferenceSet(BaseModel):
    """Set/change a per-feature pin. Upsert — replaces any existing pin."""

    feature: FeatureKey
    connector_id: int = Field(..., ge=1)
```

> Note: `FeatureKey` is hand-maintained to match `KNOWN_FEATURES` (Pydantic `Literal` can't be built from a runtime frozenset and still emit a static OpenAPI enum). The model docstring in `llm_feature_preference.py` flags that both must stay in sync; a test in Task 7 asserts they match.

- [ ] **Step 2: Verify it imports**

Run: `cd server && .venv/bin/python -c "from app.schemas.llm import FeaturePreferenceSet, FeaturePreferencesListOut, KNOWN_FEATURE_VALUES; print(KNOWN_FEATURE_VALUES)"`
Expected: prints `('recommendation', 'set_builder')`

- [ ] **Step 3: Commit**

```bash
git add server/app/schemas/llm.py
git commit -m "feat(llm): feature-preference API schemas"
```

---

## Task 6: API endpoints

**Files:**
- Modify: `server/app/api/llm.py`
- Test: `server/tests/test_llm_feature_preference.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_feature_preference.py`:

```python
from fastapi.testclient import TestClient  # noqa: E402


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_set_list_clear_feature_preference_endpoints(client, db, test_user, auth_headers):
    c = _make_connector(db, test_user, display_name="Endpoint connector")

    # Set
    resp = client.post(
        "/api/llm/feature-preferences",
        json={"feature": "recommendation", "connector_id": c.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert {p["feature"]: p["connector_id"] for p in body["preferences"]} == {
        "recommendation": c.id
    }
    assert "set_builder" in body["known_features"]

    # List
    resp = client.get("/api/llm/feature-preferences", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["preferences"][0]["connector_id"] == c.id

    # Clear
    resp = client.delete("/api/llm/feature-preferences/recommendation", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["preferences"] == []


def test_set_feature_preference_rejects_unknown_feature(client, db, test_user, auth_headers):
    c = _make_connector(db, test_user, display_name="X")
    resp = client.post(
        "/api/llm/feature-preferences",
        json={"feature": "totally_made_up", "connector_id": c.id},
        headers=auth_headers,
    )
    assert resp.status_code == 422  # Pydantic Literal rejects it


def test_set_feature_preference_rejects_other_djs_connector(
    client, db, test_user, auth_headers
):
    # Another DJ owns this connector.
    other = User(
        username="otherdj", password_hash=get_password_hash("password123"), role="dj"
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    foreign = _make_connector(db, other, display_name="Not yours")

    resp = client.post(
        "/api/llm/feature-preferences",
        json={"feature": "recommendation", "connector_id": foreign.id},
        headers=auth_headers,
    )
    assert resp.status_code == 404  # ownership not leaked


def test_set_feature_preference_rejects_inactive_connector(
    client, db, test_user, auth_headers
):
    c = _make_connector(db, test_user, display_name="Broken", status="auth_invalid")
    resp = client.post(
        "/api/llm/feature-preferences",
        json={"feature": "recommendation", "connector_id": c.id},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_clear_unknown_feature_returns_422(client, auth_headers):
    resp = client.delete("/api/llm/feature-preferences/bogus", headers=auth_headers)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q -k endpoint`
Expected: FAIL with 404 (route not found) on the first POST.

- [ ] **Step 3: Add the endpoints**

In `server/app/api/llm.py`:

Add to the schema import block:

```python
from app.schemas.llm import (
    ConnectorCreate,
    ConnectorCredentialsRotate,
    ConnectorOut,
    ConnectorPatch,
    ConnectorTestResult,
    DjPolicyOut,
    FeatureKey,
    FeaturePreferenceSet,
    FeaturePreferencesListOut,
)
```

Add to the connector_storage import block:

```python
from app.services.llm.connector_storage import (
    ...existing names...,
    clear_feature_preference,
    get_feature_preferences_for_user,
    set_feature_preference,
)
```

Add a small helper near `_get_owned_connector_or_404`:

```python
def _feature_prefs_response(db: Session, user_id: int) -> FeaturePreferencesListOut:
    """Build the list response: the DJ's current pins + the pinnable catalogue."""
    from app.schemas.llm import KNOWN_FEATURE_VALUES, FeaturePreferenceOut

    rows = get_feature_preferences_for_user(db, user_id)
    return FeaturePreferencesListOut(
        preferences=[FeaturePreferenceOut.model_validate(r) for r in rows],
        known_features=list(KNOWN_FEATURE_VALUES),  # type: ignore[arg-type]
    )
```

Add the three endpoints (place after the unset-default endpoint, before the delete-connector endpoint):

```python
@router.get("/feature-preferences", response_model=FeaturePreferencesListOut)
@limiter.limit("60/minute")
def list_feature_preferences(
    request: FastAPIRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FeaturePreferencesListOut:
    """List the DJ's per-feature connector pins (issue #337)."""
    return _feature_prefs_response(db, user.id)


@router.post(
    "/feature-preferences",
    response_model=FeaturePreferencesListOut,
    responses={
        400: {"description": "Connector is not active and cannot be pinned."},
        404: {"description": "Connector not found for current user."},
    },
)
@limiter.limit("30/minute")
def set_feature_preference_endpoint(
    request: FastAPIRequest,
    payload: FeaturePreferenceSet,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FeaturePreferencesListOut:
    """Pin (or re-pin) a connector to a feature for the current DJ.

    Validates connector ownership server-side (404 for IDs the DJ doesn't own,
    so another DJ's connector existence is never leaked) and rejects pinning a
    non-active connector (400) — the gateway would skip it anyway, so silently
    accepting it is a footgun.
    """
    row = _get_owned_connector_or_404(db, payload.connector_id, user.id)
    if row.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Only an active connector can be pinned to a feature",
        )
    set_feature_preference(
        db, user_id=user.id, feature=payload.feature, connector_id=row.id
    )
    db.commit()
    return _feature_prefs_response(db, user.id)


@router.delete("/feature-preferences/{feature}", response_model=FeaturePreferencesListOut)
@limiter.limit("30/minute")
def clear_feature_preference_endpoint(
    request: FastAPIRequest,
    feature: FeatureKey,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FeaturePreferencesListOut:
    """Clear the DJ's pin for ``feature`` (no-op if unset). Returns the new list."""
    clear_feature_preference(db, user_id=user.id, feature=feature)
    db.commit()
    return _feature_prefs_response(db, user.id)
```

> Path-param `feature: FeatureKey` makes FastAPI return 422 for unknown features automatically.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -x -q -k "endpoint or feature"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/api/llm.py server/tests/test_llm_feature_preference.py
git commit -m "feat(llm): set/clear/list feature-preference endpoints"
```

---

## Task 7: Consistency guard + full backend CI

**Files:**
- Test: `server/tests/test_llm_feature_preference.py`

- [ ] **Step 1: Add a guard test that FeatureKey == KNOWN_FEATURES**

Append to `server/tests/test_llm_feature_preference.py`:

```python
def test_feature_key_literal_matches_known_features():
    """FeatureKey (the OpenAPI enum) must stay in sync with KNOWN_FEATURES."""
    import typing

    from app.schemas.llm import FeatureKey

    literal_values = set(typing.get_args(FeatureKey))
    assert literal_values == set(KNOWN_FEATURES)
```

- [ ] **Step 2: Run the full new test file**

Run: `cd server && .venv/bin/pytest tests/test_llm_feature_preference.py -q`
Expected: PASS (all tests)

- [ ] **Step 3: Run full backend CI**

```bash
cd server
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/alembic upgrade head && .venv/bin/alembic check
.venv/bin/pytest --tb=short -q
```

Expected: ruff clean, bandit clean, alembic check clean, pytest passes with coverage ≥ gate. Fix any failures before committing.

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_llm_feature_preference.py
git commit -m "test(llm): guard FeatureKey/KNOWN_FEATURES sync"
```

---

## Task 8: Frontend — regenerate types + api.ts methods

**Files:**
- Modify: `dashboard/lib/api-types.generated.ts` (regenerated), `dashboard/lib/api-types.ts`, `dashboard/lib/api.ts`

- [ ] **Step 1: Regenerate OpenAPI types**

```bash
cd dashboard
npm run types:export
npm run types:generate
git checkout ../dashboard/next-env.d.ts 2>/dev/null || true
```

Expected: `lib/api-types.generated.ts` now contains `FeaturePreferenceOut`, `FeaturePreferencesListOut`, `FeaturePreferenceSet` schemas.

- [ ] **Step 2: Re-export the new types**

In `dashboard/lib/api-types.ts`, in the LLM gateway block, add:

```typescript
export type LlmFeaturePreference = Schemas['FeaturePreferenceOut'];
export type LlmFeaturePreferences = Schemas['FeaturePreferencesListOut'];
export type LlmFeaturePreferenceSet = Schemas['FeaturePreferenceSet'];
export type LlmFeatureKey = Schemas['FeaturePreferenceOut']['feature'];
```

- [ ] **Step 3: Add api.ts methods**

In `dashboard/lib/api.ts`, add the type imports to the existing LLM import + re-export blocks:
`LlmFeaturePreferences`, `LlmFeaturePreferenceSet`, `LlmFeatureKey`.

Then add methods after `unsetLlmConnectorDefault`:

```typescript
  async listLlmFeaturePreferences(): Promise<LlmFeaturePreferences> {
    return this.fetch('/api/llm/feature-preferences');
  }

  async setLlmFeaturePreference(
    data: LlmFeaturePreferenceSet,
  ): Promise<LlmFeaturePreferences> {
    return this.fetch('/api/llm/feature-preferences', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async clearLlmFeaturePreference(
    feature: LlmFeatureKey,
  ): Promise<LlmFeaturePreferences> {
    return this.fetch(`/api/llm/feature-preferences/${feature}`, {
      method: 'DELETE',
    });
  }
```

- [ ] **Step 4: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api-types.generated.ts dashboard/lib/api-types.ts dashboard/lib/api.ts server/openapi.json
git commit -m "feat(ai-ui): api client methods + types for feature preferences"
```

---

## Task 9: Frontend — "Per-feature defaults" section

**Files:**
- Modify: `dashboard/components/AiProvidersSection.tsx`
- Test: `dashboard/components/__tests__/AiProvidersSection.featurePrefs.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Check first whether a test file already exists for this component:
Run: `ls dashboard/components/__tests__/ 2>/dev/null | grep -i aiprovider || ls dashboard/**/__tests__/ 2>/dev/null`

Create `dashboard/components/__tests__/AiProvidersSection.featurePrefs.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import AiProvidersSection from '../AiProvidersSection';
import { api } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  api: {
    listLlmConnectors: vi.fn(),
    getLlmPolicy: vi.fn(),
    listOpenRouterModels: vi.fn(),
    listLlmFeaturePreferences: vi.fn(),
    setLlmFeaturePreference: vi.fn(),
    clearLlmFeaturePreference: vi.fn(),
  },
}));

const connector = {
  id: 1,
  user_id: 1,
  connector_type: 'openai_apikey',
  display_name: 'My OpenAI',
  status: 'active',
  base_url_plain: null,
  model_hint: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  last_used_at: null,
  last_error: null,
  is_default: false,
  last_health_check_at: null,
  last_health_check_status: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.listLlmConnectors as any).mockResolvedValue([connector]);
  (api.getLlmPolicy as any).mockResolvedValue({
    llm_apikey_connectors_enabled: true,
    llm_compatible_connector_enabled: true,
    allowed_connector_types: ['openai_apikey'],
  });
  (api.listLlmFeaturePreferences as any).mockResolvedValue({
    preferences: [],
    known_features: ['recommendation', 'set_builder'],
  });
});

describe('AiProvidersSection per-feature defaults', () => {
  it('renders a picker per known feature and sets a pin', async () => {
    (api.setLlmFeaturePreference as any).mockResolvedValue({
      preferences: [{ feature: 'recommendation', connector_id: 1 }],
      known_features: ['recommendation', 'set_builder'],
    });

    render(<AiProvidersSection />);

    await waitFor(() => expect(screen.getByText(/Per-feature defaults/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/recommendation/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '1' } });

    await waitFor(() =>
      expect(api.setLlmFeaturePreference).toHaveBeenCalledWith({
        feature: 'recommendation',
        connector_id: 1,
      }),
    );
  });

  it('clears a pin when "Use account default" is selected', async () => {
    (api.listLlmFeaturePreferences as any).mockResolvedValue({
      preferences: [{ feature: 'recommendation', connector_id: 1 }],
      known_features: ['recommendation', 'set_builder'],
    });
    (api.clearLlmFeaturePreference as any).mockResolvedValue({
      preferences: [],
      known_features: ['recommendation', 'set_builder'],
    });

    render(<AiProvidersSection />);
    await waitFor(() => expect(screen.getByText(/Per-feature defaults/i)).toBeInTheDocument());

    const select = screen.getByLabelText(/recommendation/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '' } });

    await waitFor(() =>
      expect(api.clearLlmFeaturePreference).toHaveBeenCalledWith('recommendation'),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run AiProvidersSection.featurePrefs`
Expected: FAIL — no "Per-feature defaults" section yet.

- [ ] **Step 3: Implement the section**

In `dashboard/components/AiProvidersSection.tsx`:

Add to the type import block:

```typescript
import type {
  AIModelInfo,
  LlmConnector,
  LlmConnectorCreate,
  LlmConnectorType,
  LlmDjPolicy,
  LlmFeaturePreferences,
  LlmFeatureKey,
} from '@/lib/api-types';
```

Add a human-readable feature label map near `CONNECTOR_TYPE_LABELS`:

```typescript
const FEATURE_LABELS: Record<string, string> = {
  recommendation: 'Recommendations',
  set_builder: 'Set builder',
};
```

Add state inside the component (next to the other `useState` hooks):

```typescript
  const [featurePrefs, setFeaturePrefs] = useState<LlmFeaturePreferences | null>(null);
```

Add `api.listLlmFeaturePreferences()` to the initial `Promise.all`:

```typescript
    Promise.all([api.listLlmConnectors(), fetchPolicySoft(), fetchFeaturePrefsSoft()])
      .then(([rows, p, prefs]) => {
        if (!active) return;
        setConnectors(rows);
        setPolicy(p);
        setFeaturePrefs(prefs);
      })
```

Add handlers near `handleUnsetDefault`:

```typescript
  const handleFeaturePrefChange = async (feature: LlmFeatureKey, value: string) => {
    try {
      const updated =
        value === ''
          ? await api.clearLlmFeaturePreference(feature)
          : await api.setLlmFeaturePreference({
              feature,
              connector_id: Number(value),
            });
      setFeaturePrefs(updated);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update feature default');
    }
  };
```

Add the section JSX after the "Connected providers" `</section>` (before the "Add provider" section). Only render it when there is at least one active connector to pin:

```tsx
      {featurePrefs && featurePrefs.known_features.length > 0 && (
        <section style={{ marginTop: '2rem' }}>
          <h3 style={{ marginTop: 0 }}>Per-feature defaults</h3>
          <p style={{ color: 'var(--text-secondary)' }}>
            Pin a specific provider to each AI feature. Unpinned features use your account
            default (or most-recently-used) connector. Inactive connectors are skipped
            automatically.
          </p>
          {featurePrefs.known_features.map((feature) => {
            const current =
              featurePrefs.preferences.find((p) => p.feature === feature)?.connector_id ?? '';
            const selectId = `feature-pref-${feature}`;
            const activeConnectors = connectors.filter((c) => c.status === 'active');
            return (
              <div className="form-group" key={feature}>
                <label htmlFor={selectId}>{FEATURE_LABELS[feature] ?? feature}</label>
                <select
                  id={selectId}
                  className="input"
                  value={current === '' ? '' : String(current)}
                  onChange={(e) =>
                    handleFeaturePrefChange(feature as LlmFeatureKey, e.target.value)
                  }
                >
                  <option value="">Use account default</option>
                  {activeConnectors.map((c) => (
                    <option key={c.id} value={String(c.id)}>
                      {c.display_name}
                    </option>
                  ))}
                </select>
              </div>
            );
          })}
        </section>
      )}
```

Add the soft-fetch helper near `fetchPolicySoft` at the bottom:

```typescript
async function fetchFeaturePrefsSoft(): Promise<LlmFeaturePreferences | null> {
  try {
    return await api.listLlmFeaturePreferences();
  } catch {
    return null;
  }
}
```

> Design note: the `<label htmlFor>` text is the feature label ("Recommendations") so `getByLabelText(/recommendation/i)` in the test matches. The picker uses connector_id values as strings; empty string = "Use account default" → clears the pin.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run AiProvidersSection.featurePrefs`
Expected: PASS

- [ ] **Step 5: Run full frontend CI**

```bash
cd dashboard
npm run lint
npx tsc --noEmit
npm test -- --run
git checkout lib/../next-env.d.ts 2>/dev/null || git checkout next-env.d.ts 2>/dev/null || true
```

Expected: lint clean, tsc clean, all vitest pass. (Coverage thresholds enforced — if the new component branch drops coverage, the existing tests + the two new tests should cover the added code paths.)

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/AiProvidersSection.tsx dashboard/components/__tests__/AiProvidersSection.featurePrefs.test.tsx
git commit -m "feat(ai-ui): per-feature defaults section on DJ AI settings"
```

---

## Task 10: Final verification + PR

- [ ] **Step 1: Full backend + frontend CI once more (all green)**

```bash
cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/alembic upgrade head && .venv/bin/alembic check && .venv/bin/pytest --tb=short -q
cd ../dashboard && npm run lint && npx tsc --noEmit && npm test -- --run
git -C .. checkout dashboard/next-env.d.ts 2>/dev/null || true
```

- [ ] **Step 2: Push + open PR (use superpowers:finishing-a-development-branch, option 2)**

```bash
git push -u origin feat/issue-337
gh pr create --base epic/ai-engine --title "feat(llm): per-feature connector preference (#337)" --body "..."
```

PR body MUST include `Closes #337`, a `## Design decisions` section, and a note that it targets `epic/ai-engine`.

---

## Self-Review

**Spec coverage:**
- New `LlmFeaturePreference` model (id, user_id, feature, connector_id, created_at) — Task 1. ✓
- UNIQUE (user_id, feature) — Task 1 (`__table_args__`) + Task 2 (migration). ✓
- Migration off rev 049, named `050_*` — Task 2. ✓
- Resolution order feature → per-DJ default → MRU → org default → NoLlmConfigured — Task 4. ✓
- Graceful fallback when pinned connector deleted or auth_invalid — Task 4 (tests + skip logic). ✓
- Endpoints set/change/clear scoped to current user, rate-limited, feature allowlist — Tasks 5+6. ✓
- Connector ownership validation (no cross-DJ pin) — Task 6 (404 test). ✓
- Frontend "Per-feature defaults" section + api.ts methods + api-types — Tasks 8+9. ✓
- DJ can set, change, clear a pin (acceptance) — Tasks 6 (set=upsert covers change) + 9. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full content. PR body content deferred to Task 10 (acceptable — it's prose, drafted at PR time from commit history).

**Type consistency:** `set_feature_preference`, `clear_feature_preference`, `get_feature_preferences_for_user`, `get_feature_preference` used consistently across Tasks 3/4/6. `FeatureKey` / `FeaturePreferenceSet` / `FeaturePreferencesListOut` / `FeaturePreferenceOut` consistent across Tasks 5/6/8. `LlmFeaturePreferences` / `LlmFeatureKey` / `LlmFeaturePreferenceSet` consistent across Tasks 8/9.

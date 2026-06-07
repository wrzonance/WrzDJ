# WrzDJSet Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the foundational scaffold for WrzDJSet — SQLAlchemy models, one Alembic migration, a `/api/setbuilder/*` router with set CRUD, an LLM gateway interface stub, and a dashboard builder shell (set list + 4-panel workspace).

**Architecture:** Backend follows the existing WrzDJ FastAPI/SQLAlchemy 2.0 pattern: models in `app/models/`, Pydantic schemas in `app/schemas/`, business logic in `app/services/`, thin routers in `app/api/`. Auth uses the existing `get_current_active_user` dependency (rejects pending users). Sets are owner-scoped; ownership checks return 404 (not 403) to avoid leaking existence, matching `get_owned_event_by_id`. The LLM gateway is a provider-agnostic interface (`services/llm/gateway.py`) whose temporary implementation delegates to the existing `services/recommendation/llm_client.py` — no setbuilder code imports a provider SDK directly. Frontend lives under the `(dj)` route group (shares auth-gated layout) at `dashboard/app/setbuilder/`, matching the existing dashboard page conventions (vanilla CSS + inline styles, dark theme, `api` client singleton).

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / pytest (SQLite in-memory) on the backend; Next.js 16 / React 19 / TypeScript / vitest on the frontend.

---

## File Structure

**Backend (create):**
- `server/app/models/set.py` — `Set`, `SetSlot`, `SetCurvePoint`, `SetCollaborator` ORM models
- `server/app/models/track_vibe.py` — `TrackVibe`, `TrackVibeOverride` ORM models (incl. the 5-col UNIQUE on TrackVibe)
- `server/app/schemas/setbuilder.py` — Pydantic request/response models for set CRUD
- `server/app/services/setbuilder/__init__.py` — package marker
- `server/app/services/setbuilder/set_service.py` — set CRUD business logic (owner-scoped)
- `server/app/services/llm/__init__.py` — package marker
- `server/app/services/llm/gateway.py` — provider-agnostic gateway interface + temporary delegating impl
- `server/app/api/setbuilder.py` — FastAPI router, `/api/setbuilder/*`, set CRUD only
- `server/alembic/versions/046_add_setbuilder_tables.py` — one migration creating all 6 tables
- `server/tests/test_setbuilder_models.py` — model + constraint tests
- `server/tests/test_setbuilder_api.py` — CRUD endpoint + auth-gating tests
- `server/tests/test_llm_gateway.py` — gateway interface/stub tests

**Backend (modify):**
- `server/app/models/__init__.py` — register the 6 new models
- `server/app/api/__init__.py` — include the setbuilder router

**Frontend (create):**
- `dashboard/app/setbuilder/page.tsx` — set list (create/list/rename/delete)
- `dashboard/app/setbuilder/[setId]/page.tsx` — builder workspace, 4-panel grid
- `dashboard/app/setbuilder/setbuilder.module.css` — scoped styles for the 4-panel grid
- `dashboard/app/setbuilder/__tests__/page.test.tsx` — set list render/CRUD test

**Frontend (modify):**
- `dashboard/lib/api-types.ts` — add `SetSummary`, `SetDetail`, `SetCreate`, `SetRename` types
- `dashboard/lib/api.ts` — add `listSets`/`createSet`/`getSet`/`renameSet`/`deleteSet` methods

---

## Design decisions (locked for this phase)

These resolve ambiguities in the issue/exec-summary. Document them in the PR body too.

1. **Set must move under the `(dj)` route group?** The issue says `dashboard/app/setbuilder/page.tsx`. But the existing auth-gated DJ pages live under `dashboard/app/(dj)/`. Route groups `(dj)` do **not** change the URL — `app/(dj)/dashboard` serves `/dashboard`. Putting setbuilder at `app/setbuilder/` (outside the group) serves `/setbuilder` but does NOT inherit the `(dj)` layout (ThemeToggle). **Decision:** Follow the issue literally — create at `dashboard/app/setbuilder/` (URL `/setbuilder`). Each page does its own auth guard via `useAuth` (same pattern the dashboard page uses internally), so no functionality is lost. This honors the issue's explicit path.
2. **`track_id` is a free-form string, not an FK.** The exec-summary models `TrackVibe.track_id`/`SetSlot.track_id` against a global track identity that does not yet exist in WrzDJ (requests use Spotify/Tidal/Beatport source URLs, not a unified track table). **Decision:** model `track_id` as an indexed `String(255)` (a service-namespaced external ID like `tidal:12345`), nullable on `SetSlot` (a slot can be empty pre-fill). No FK in Phase 0.
3. **TrackVibe nullability:** energy/mood/era/transitional_role/confidence are LLM-derived and absent until enrichment runs (Phase 1). **Decision:** all vibe-signal columns nullable except the 5 identity columns in the UNIQUE constraint (`track_id`, `llm_provider`, `llm_model`, `prompt_version`, `schema_version`), which are `nullable=False`.
4. **Enums as `String(N)` columns, not DB enums** — matches every existing WrzDJ model (`User.role`, `Event.collection_phase_override`, request status). Pydantic `Literal[...]` enforces values at the API boundary.
5. **Ownership errors return 404, not 403** — matches `get_owned_event_by_id`; avoids leaking set existence to non-owners.
6. **Gateway stub surface:** a single async `dispatch(messages, tool, *, model_hint, ...)` entrypoint returning a normalized `GatewayResponse{tool_calls, text}`. The temporary impl maps `dispatch` onto the existing `call_llm`-style Anthropic path **inside `gateway.py` only** by importing the existing `llm_client` module — setbuilder code imports `gateway`, never `anthropic` or `llm_client`. Provider/model identifiers are passed as data (strings), never imported.

---

## Task 1: TrackVibe + TrackVibeOverride models

**Files:**
- Create: `server/app/models/track_vibe.py`
- Modify: `server/app/models/__init__.py`
- Test: `server/tests/test_setbuilder_models.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_setbuilder_models.py`:

```python
"""Model + constraint tests for WrzDJSet Phase 0 tables."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.track_vibe import TrackVibe, TrackVibeOverride


def test_track_vibe_persists_with_identity_columns(db):
    vibe = TrackVibe(
        track_id="tidal:12345",
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5",
        prompt_version="v1",
        schema_version="v1",
        energy=7,
        mood="euphoric",
        era="2010s",
        sing_along=True,
        dance_floor=True,
        transitional_role="peak",
        confidence=0.8,
    )
    db.add(vibe)
    db.commit()
    db.refresh(vibe)
    assert vibe.id is not None
    assert vibe.energy == 7
    assert vibe.created_at is not None


def test_track_vibe_unique_constraint(db):
    """UNIQUE(track_id, llm_provider, llm_model, prompt_version, schema_version)."""
    kwargs = dict(
        track_id="tidal:12345",
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5",
        prompt_version="v1",
        schema_version="v1",
    )
    db.add(TrackVibe(**kwargs))
    db.commit()
    db.add(TrackVibe(**kwargs))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_track_vibe_same_track_different_model_allowed(db):
    """Same track under a different model is a distinct cache row."""
    db.add(
        TrackVibe(
            track_id="tidal:12345",
            llm_provider="anthropic",
            llm_model="claude-haiku-4-5",
            prompt_version="v1",
            schema_version="v1",
        )
    )
    db.add(
        TrackVibe(
            track_id="tidal:12345",
            llm_provider="openai",
            llm_model="gpt-5-mini",
            prompt_version="v1",
            schema_version="v1",
        )
    )
    db.commit()
    assert db.query(TrackVibe).count() == 2


def test_track_vibe_override_persists(db):
    override = TrackVibeOverride(
        track_id="tidal:12345",
        user_id=1,
        energy_override=9,
        mood_override="dark",
        energy_was=7,
        mood_was="euphoric",
        source="explicit_edit",
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    assert override.id is not None
    assert override.source == "explicit_edit"
    assert override.created_at is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.track_vibe'`

- [ ] **Step 3: Write the model implementation**

Create `server/app/models/track_vibe.py`:

```python
"""WrzDJSet vibe-signal models (Phase 0 scaffold).

TrackVibe is a GLOBAL LLM cache — one row per (track, provider, model,
prompt_version, schema_version). TrackVibeOverride is a per-DJ taste signal
that aggregates upward into a community consensus (read-time precedence:
DJ override -> community consensus -> LLM cached). Vibe-signal columns are
nullable: they are filled by the enrichment pipeline in a later phase.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class TrackVibe(Base):
    """Global LLM vibe cache. One row per track+provider+model+prompt+schema."""

    __tablename__ = "track_vibes"
    __table_args__ = (
        UniqueConstraint(
            "track_id",
            "llm_provider",
            "llm_model",
            "prompt_version",
            "schema_version",
            name="uq_track_vibe_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Vibe signal (LLM-derived, filled by enrichment in a later phase)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10
    mood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    era: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sing_along: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dance_floor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # "intro" | "build" | "peak" | "cool" | "any"
    transitional_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-1

    # Provenance / granular invalidation (identity columns — part of UNIQUE)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrackVibeOverride(Base):
    """Per-DJ taste override. Aggregated upward into community consensus."""

    __tablename__ = "track_vibe_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    energy_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_override: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Good-citizen provenance for future taste training
    overridden_from_vibe_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy_was: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_was: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # "explicit_edit" | "upvote" | "downvote_implicit"
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

- [ ] **Step 4: Register models in the package `__init__`**

In `server/app/models/__init__.py`, add the import after the `system_settings` import line and the names to `__all__`. The file currently imports alphabetically and lists names in `__all__`. Add:

```python
from app.models.track_vibe import TrackVibe, TrackVibeOverride
```

(place it after the `from app.models.system_settings import SystemSettings` line)

And add `"TrackVibe"` and `"TrackVibeOverride"` to the `__all__` list (keep it alphabetical — they go after `"SystemSettings"`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_models.py -v`
Expected: 4 PASS (the TrackVibe tests). (Set/SetSlot tests are added in Task 2.)

- [ ] **Step 6: Commit**

```bash
git add server/app/models/track_vibe.py server/app/models/__init__.py server/tests/test_setbuilder_models.py
git commit -m "feat(setbuilder): add TrackVibe + TrackVibeOverride models"
```

---

## Task 2: Set, SetSlot, SetCurvePoint, SetCollaborator models

**Files:**
- Create: `server/app/models/set.py`
- Modify: `server/app/models/__init__.py`
- Test: `server/tests/test_setbuilder_models.py` (append)

- [ ] **Step 1: Write the failing tests (append to the existing test file)**

Append to `server/tests/test_setbuilder_models.py`:

```python
from app.models.set import Set, SetCollaborator, SetCurvePoint, SetSlot


def _make_user(db):
    from app.models.user import User
    from app.services.auth import get_password_hash

    user = User(username="setowner", password_hash=get_password_hash("x" * 12), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_set_persists_with_defaults(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Friday Wedding")
    db.add(s)
    db.commit()
    db.refresh(s)
    assert s.id is not None
    assert s.status == "draft"
    assert s.sharing_mode == "private"
    assert s.key_strictness == 0.2
    assert s.event_id is None
    assert s.created_at is not None
    assert s.updated_at is not None


def test_set_slot_cascade_delete(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Set")
    db.add(s)
    db.commit()
    db.add(SetSlot(set_id=s.id, position=0, track_id="tidal:1"))
    db.add(SetCurvePoint(set_id=s.id, position_sec=0, energy=3))
    db.add(SetCollaborator(set_id=s.id, user_id=user.id, role="editor", invited_by=user.id))
    db.commit()
    assert db.query(SetSlot).count() == 1
    assert db.query(SetCurvePoint).count() == 1
    assert db.query(SetCollaborator).count() == 1

    db.delete(s)
    db.commit()
    assert db.query(SetSlot).count() == 0
    assert db.query(SetCurvePoint).count() == 0
    assert db.query(SetCollaborator).count() == 0


def test_set_slot_locked_defaults_false(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Set")
    db.add(s)
    db.commit()
    slot = SetSlot(set_id=s.id, position=0, track_id="tidal:1")
    db.add(slot)
    db.commit()
    db.refresh(slot)
    assert slot.locked is False
    assert slot.transition_score is None


def test_set_slot_empty_track_allowed(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Set")
    db.add(s)
    db.commit()
    slot = SetSlot(set_id=s.id, position=0)
    db.add(slot)
    db.commit()
    db.refresh(slot)
    assert slot.track_id is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_models.py -v -k "set"`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.set'`

- [ ] **Step 3: Write the model implementation**

Create `server/app/models/set.py`:

```python
"""WrzDJSet core models (Phase 0 scaffold).

A Set is a standalone, owner-private DJ set with an optional event link.
SetSlot rows are the ordered timeline; SetCurvePoint rows are the energy
curve; SetCollaborator is modeled now (per exec-summary) but invite/enforce
flows ship in v3. Child rows cascade-delete with their parent Set.

Enum-like columns are String(N) (matching every other WrzDJ model);
allowed values are enforced at the API boundary via Pydantic Literals.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class Set(Base):
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vibe_theme: Mapped[str | None] = mapped_column(String(50), nullable=True)

    target_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm_ceiling: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0.0 ignore Camelot ... 1.0 strict +/-1
    key_strictness: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.2, server_default="0.2"
    )

    # "draft" | "locked" | "exported"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    # "private" | "invite_only"  (v3 enforced)
    sharing_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default="private"
    )

    tidal_playlist_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    slots: Mapped[list["SetSlot"]] = relationship(
        "SetSlot",
        back_populates="set",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    curve_points: Mapped[list["SetCurvePoint"]] = relationship(
        "SetCurvePoint",
        back_populates="set",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    collaborators: Mapped[list["SetCollaborator"]] = relationship(
        "SetCollaborator",
        back_populates="set",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SetSlot(Base):
    __tablename__ = "set_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    track_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    transition_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    set: Mapped["Set"] = relationship("Set", back_populates="slots")


class SetCurvePoint(Base):
    __tablename__ = "set_curve_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-10
    label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_slow_window_start: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    is_slow_window_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    set: Mapped["Set"] = relationship("Set", back_populates="curve_points")


class SetCollaborator(Base):
    """Modeled v1, enforced v3."""

    __tablename__ = "set_collaborators"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "editor" | "viewer"
    invited_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    set: Mapped["Set"] = relationship("Set", back_populates="collaborators")
```

- [ ] **Step 4: Register models in the package `__init__`**

In `server/app/models/__init__.py`, add (after the `from app.models.search_cache import SearchCache` line, keeping rough alpha order — `set` sorts after `search_cache`):

```python
from app.models.set import Set, SetCollaborator, SetCurvePoint, SetSlot
```

Add `"Set"`, `"SetCollaborator"`, `"SetCurvePoint"`, `"SetSlot"` to `__all__` (after `"SearchCache"`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_models.py -v`
Expected: all PASS (8 tests total: 4 from Task 1, 4 here).

- [ ] **Step 6: Commit**

```bash
git add server/app/models/set.py server/app/models/__init__.py server/tests/test_setbuilder_models.py
git commit -m "feat(setbuilder): add Set/SetSlot/SetCurvePoint/SetCollaborator models"
```

---

## Task 3: Alembic migration for all 6 tables

**Files:**
- Create: `server/alembic/versions/046_add_setbuilder_tables.py`

The current single head is `a11334c031bb`. The new migration goes ON TOP of it (`down_revision = "a11334c031bb"`). The migration must EXACTLY match the models (CI runs `alembic check`).

- [ ] **Step 1: Write the migration**

Create `server/alembic/versions/046_add_setbuilder_tables.py`:

```python
"""Add WrzDJSet Phase 0 tables (sets, slots, curve points, collaborators, vibes)

Revision ID: 046
Revises: a11334c031bb
Create Date: 2026-06-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "046"
down_revision: str | None = "a11334c031bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("vibe_theme", sa.String(50), nullable=True),
        sa.Column("target_duration_sec", sa.Integer(), nullable=True),
        sa.Column("bpm_floor", sa.Integer(), nullable=True),
        sa.Column("bpm_ceiling", sa.Integer(), nullable=True),
        sa.Column("key_strictness", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("sharing_mode", sa.String(20), nullable=False, server_default="private"),
        sa.Column("tidal_playlist_id", sa.String(100), nullable=True),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sets_owner_id", "sets", ["owner_id"])
    op.create_index("ix_sets_event_id", "sets", ["event_id"])

    op.create_table(
        "set_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.String(255), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("transition_score", sa.Float(), nullable=True),
        sa.Column("transition_warnings", sa.Text(), nullable=True),
    )
    op.create_index("ix_set_slots_set_id", "set_slots", ["set_id"])
    op.create_index("ix_set_slots_track_id", "set_slots", ["track_id"])

    op.create_table(
        "set_curve_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position_sec", sa.Integer(), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(50), nullable=True),
        sa.Column("is_slow_window_start", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_slow_window_end", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index("ix_set_curve_points_set_id", "set_curve_points", ["set_id"])

    op.create_table(
        "set_collaborators",
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
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "invited_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invited_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_set_collaborators_set_id", "set_collaborators", ["set_id"])
    op.create_index("ix_set_collaborators_user_id", "set_collaborators", ["user_id"])

    op.create_table(
        "track_vibes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.String(255), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=True),
        sa.Column("mood", sa.String(50), nullable=True),
        sa.Column("era", sa.String(50), nullable=True),
        sa.Column("sing_along", sa.Boolean(), nullable=True),
        sa.Column("dance_floor", sa.Boolean(), nullable=True),
        sa.Column("transitional_role", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "track_id",
            "llm_provider",
            "llm_model",
            "prompt_version",
            "schema_version",
            name="uq_track_vibe_identity",
        ),
    )
    op.create_index("ix_track_vibes_track_id", "track_vibes", ["track_id"])

    op.create_table(
        "track_vibe_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("energy_override", sa.Integer(), nullable=True),
        sa.Column("mood_override", sa.String(50), nullable=True),
        sa.Column("overridden_from_vibe_id", sa.Integer(), nullable=True),
        sa.Column("energy_was", sa.Integer(), nullable=True),
        sa.Column("mood_was", sa.String(50), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_track_vibe_overrides_track_id", "track_vibe_overrides", ["track_id"])
    op.create_index("ix_track_vibe_overrides_user_id", "track_vibe_overrides", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_track_vibe_overrides_user_id")
    op.drop_index("ix_track_vibe_overrides_track_id")
    op.drop_table("track_vibe_overrides")
    op.drop_index("ix_track_vibes_track_id")
    op.drop_table("track_vibes")
    op.drop_index("ix_set_collaborators_user_id")
    op.drop_index("ix_set_collaborators_set_id")
    op.drop_table("set_collaborators")
    op.drop_index("ix_set_curve_points_set_id")
    op.drop_table("set_curve_points")
    op.drop_index("ix_set_slots_track_id")
    op.drop_index("ix_set_slots_set_id")
    op.drop_table("set_slots")
    op.drop_index("ix_sets_event_id")
    op.drop_index("ix_sets_owner_id")
    op.drop_table("sets")
```

- [ ] **Step 2: Apply the migration and verify no drift**

Ensure the dev DB is up (`docker compose up -d db` from the worktree root if needed).
Run: `cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check`
Expected: `alembic upgrade head` runs without error; `alembic check` prints `No new upgrade operations detected.`

If `alembic check` reports drift, reconcile the migration column types/nullability/server_default/indexes with the models until it is clean. Common cause: a model column with `index=True` lacks a matching `op.create_index`, or a `server_default` mismatch.

- [ ] **Step 3: Commit**

```bash
git add server/alembic/versions/046_add_setbuilder_tables.py
git commit -m "feat(setbuilder): add migration 046 for setbuilder tables"
```

---

## Task 4: LLM gateway interface stub

**Files:**
- Create: `server/app/services/llm/__init__.py`
- Create: `server/app/services/llm/gateway.py`
- Test: `server/tests/test_llm_gateway.py`

The gateway is the ONLY surface setbuilder code calls for LLM work. Its temporary implementation delegates to the existing Anthropic path inside `llm_client.py`. **No provider SDK import lives in setbuilder code** — the `anthropic` import stays confined to `services/recommendation/llm_client.py`, which `gateway.py` reuses indirectly.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_llm_gateway.py`:

```python
"""Tests for the provider-agnostic LLM gateway stub (Phase 0).

The gateway is the single surface WrzDJSet codes against. Phase 0 ships an
interface + a temporary delegating implementation. These tests pin the
interface shape and the normalization contract, NOT the live LLM.
"""

import ast
from pathlib import Path

import pytest

from app.services.llm import gateway


def test_gateway_response_shape():
    resp = gateway.GatewayResponse(tool_calls=[{"name": "x", "input": {}}], text="hi")
    assert resp.tool_calls == [{"name": "x", "input": {}}]
    assert resp.text == "hi"


def test_gateway_response_defaults():
    resp = gateway.GatewayResponse()
    assert resp.tool_calls == []
    assert resp.text == ""


def test_model_hint_literal_values_documented():
    # The two documented hints from the exec summary.
    assert gateway.MODEL_HINTS == ("fast", "strong")


@pytest.mark.asyncio
async def test_dispatch_normalizes_delegated_response(monkeypatch):
    """dispatch() returns a GatewayResponse normalized from the provider call."""

    class _FakeBlock:
        def __init__(self, type, **kw):
            self.type = type
            for k, v in kw.items():
                setattr(self, k, v)

    class _FakeResponse:
        content = [
            _FakeBlock("text", text="thinking"),
            _FakeBlock("tool_use", name="critique_set", input={"grade": "A"}),
        ]

    async def _fake_raw_call(*, model, system, tools, tool_choice, messages, max_tokens):
        # Assert the gateway passed a concrete model string (data, not import).
        assert isinstance(model, str) and model
        return _FakeResponse()

    monkeypatch.setattr(gateway, "_raw_provider_call", _fake_raw_call)

    result = await gateway.dispatch(
        messages=[{"role": "user", "content": "grade this set"}],
        tool={"name": "critique_set", "input_schema": {"type": "object"}},
        model_hint="strong",
    )
    assert isinstance(result, gateway.GatewayResponse)
    assert result.text == "thinking"
    assert result.tool_calls == [{"name": "critique_set", "input": {"grade": "A"}}]


def test_no_provider_sdk_import_in_gateway_module():
    """gateway.py must not import a provider SDK directly (anthropic/openai/etc.)."""
    src = Path(gateway.__file__).read_text()
    tree = ast.parse(src)
    banned = {"anthropic", "openai", "google", "cohere", "mistralai", "litellm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && .venv/bin/pytest tests/test_llm_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.llm'`

- [ ] **Step 3: Create the package marker and gateway implementation**

Create `server/app/services/llm/__init__.py`:

```python
"""Provider-agnostic LLM gateway package.

WrzDJSet (and any future agentic feature) MUST call LLMs only through
`app.services.llm.gateway`. Direct provider SDK imports are forbidden in
feature code — provider/model identifiers are data, not imports.
"""
```

Create `server/app/services/llm/gateway.py`:

```python
"""Provider-agnostic LLM gateway (Phase 0 interface stub).

This is the single call surface WrzDJSet codes against. The real gateway
(OAuth multi-provider dispatch) ships in a parallel worktree; until it merges
this stub delegates to the existing Anthropic path in
`services/recommendation/llm_client.py`. Per exec-summary 6/9 ("slip
insurance"), WrzDJSet is NOT blocked on the gateway merge.

CRITICAL: no provider SDK is imported here. Model identifiers are plain
strings resolved from a model_hint. The actual provider call is isolated in
`_raw_provider_call`, which reuses the existing recommendation LLM plumbing.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

ModelHint = Literal["fast", "strong"]
MODEL_HINTS: tuple[str, ...] = ("fast", "strong")


@dataclass
class GatewayResponse:
    """Normalized LLM response: tool calls + free text, provider-agnostic."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""


def _resolve_model(model_hint: ModelHint) -> str:
    """Map a coarse capability hint to a concrete model string.

    Reads the configured Anthropic model for the temporary delegating impl.
    When the OAuth gateway lands this becomes a provider-aware lookup driven
    by SystemSettings; the hint contract ("fast" vs "strong") stays stable.
    """
    from app.core.config import get_settings

    settings = get_settings()
    # Phase 0: single-provider delegation. Both hints resolve to the
    # configured model; the gateway epic differentiates fast/strong tiers.
    return settings.anthropic_model


async def _raw_provider_call(
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> Any:
    """Isolated provider call. Reuses the existing recommendation LLM client.

    Importing the client lazily and locally keeps any provider SDK transitively
    out of this module's import graph at module scope and out of feature code.
    """
    from anthropic import AsyncAnthropic  # noqa: PLC0415 — isolation point

    from app.core.config import get_settings

    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    return await client.messages.create(**kwargs)


def _normalize(response: Any) -> GatewayResponse:
    """Translate a provider response into the normalized GatewayResponse."""
    text = ""
    tool_calls: list[dict[str, Any]] = []
    for block in getattr(response, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            text += getattr(block, "text", "")
        elif btype == "tool_use":
            tool_calls.append(
                {"name": getattr(block, "name", ""), "input": getattr(block, "input", {})}
            )
    return GatewayResponse(tool_calls=tool_calls, text=text)


async def dispatch(
    *,
    messages: list[dict[str, Any]],
    tool: dict[str, Any] | None = None,
    system: str = "",
    model_hint: ModelHint = "fast",
    max_tokens: int = 2048,
) -> GatewayResponse:
    """Dispatch a single LLM turn and return a normalized response.

    Args:
        messages: provider-agnostic message list ([{"role", "content"}]).
        tool: a single JSONSchema tool spec ({"name", "input_schema"});
            when provided, the gateway forces tool use.
        system: optional system prompt.
        model_hint: "fast" (batch/chat) or "strong" (critique/grading).
        max_tokens: response token cap.

    Returns:
        GatewayResponse with `tool_calls` and `text`.
    """
    model = _resolve_model(model_hint)
    tools = [tool] if tool else []
    tool_choice = {"type": "tool", "name": tool["name"]} if tool else None
    response = await _raw_provider_call(
        model=model,
        system=system,
        tools=tools,
        tool_choice=tool_choice,
        messages=messages,
        max_tokens=max_tokens,
    )
    return _normalize(response)
```

Note on the test for `_raw_provider_call`: the async test monkeypatches `gateway._raw_provider_call`, so the real `anthropic` import inside it never executes during tests. The `test_no_provider_sdk_import_in_gateway_module` test only forbids **module-scope** imports — the lazy import inside `_raw_provider_call` is a function-body import, which the AST walk over the whole module WOULD catch. To keep this test passing AND honor the gateway-only rule, the `anthropic` import must NOT appear anywhere in `gateway.py`. **Revise `_raw_provider_call` to delegate to a helper in the existing `llm_client` module instead of importing `anthropic` here.**

Apply this revision to `_raw_provider_call` in `gateway.py`:

```python
async def _raw_provider_call(
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> Any:
    """Isolated provider call. Delegates to the existing recommendation client.

    The provider SDK import lives ONLY in services/recommendation/llm_client.py.
    This module never imports a provider SDK (enforced by test).
    """
    from app.services.recommendation import llm_client

    return await llm_client.raw_messages_create(
        model=model,
        system=system,
        tools=tools,
        tool_choice=tool_choice,
        messages=messages,
        max_tokens=max_tokens,
    )
```

And add the thin reusable helper to `server/app/services/recommendation/llm_client.py` (append near `call_llm`):

```python
async def raw_messages_create(
    *,
    model: str,
    system: str,
    tools: list[dict] | None,
    tool_choice: dict | None,
    messages: list[dict],
    max_tokens: int,
):
    """Low-level Anthropic messages.create passthrough.

    Exists so the provider-agnostic gateway can delegate here without importing
    a provider SDK itself. The `anthropic` import stays confined to this module.
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
    )
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    return await client.messages.create(**kwargs)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_llm_gateway.py -v`
Expected: all PASS (5 tests). If `test_no_provider_sdk_import_in_gateway_module` fails, confirm `gateway.py` has zero `anthropic`/provider imports (the delegation goes through `llm_client.raw_messages_create`).

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/ server/app/services/recommendation/llm_client.py server/tests/test_llm_gateway.py
git commit -m "feat(setbuilder): add provider-agnostic LLM gateway stub"
```

---

## Task 5: Set CRUD service + Pydantic schemas

**Files:**
- Create: `server/app/schemas/setbuilder.py`
- Create: `server/app/services/setbuilder/__init__.py`
- Create: `server/app/services/setbuilder/set_service.py`
- Test: covered by Task 6's API tests (the service is exercised through the router). No standalone service test — boundary tests at the API beat internal unit tests here.

- [ ] **Step 1: Write the Pydantic schemas**

Create `server/app/schemas/setbuilder.py`:

```python
"""Pydantic schemas for WrzDJSet set-CRUD endpoints (Phase 0)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SetCreate(BaseModel):
    """Body for creating a new (empty) set."""

    name: str = Field(..., min_length=1, max_length=120)
    event_id: int | None = None


class SetRename(BaseModel):
    """Body for renaming a set."""

    name: str = Field(..., min_length=1, max_length=120)


class SetSummary(BaseModel):
    """Set list item (no children)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    event_id: int | None
    status: Literal["draft", "locked", "exported"]
    sharing_mode: Literal["private", "invite_only"]
    created_at: datetime
    updated_at: datetime


class SetDetail(SetSummary):
    """Full set record (Phase 0: no slot/curve expansion yet)."""

    vibe_theme: str | None
    target_duration_sec: int | None
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    tidal_playlist_id: str | None
    exported_at: datetime | None
```

- [ ] **Step 2: Write the service package marker and CRUD logic**

Create `server/app/services/setbuilder/__init__.py`:

```python
"""WrzDJSet backend services (Phase 0)."""
```

Create `server/app/services/setbuilder/set_service.py`:

```python
"""Owner-scoped CRUD for WrzDJSet sets (Phase 0).

All reads/mutations are scoped to the owner. The API layer surfaces a 404
(not 403) for a missing-or-unowned set to avoid leaking existence, matching
the rest of WrzDJ (see deps.get_owned_event_by_id).
"""

from sqlalchemy.orm import Session

from app.models.set import Set


def create_set(db: Session, owner_id: int, name: str, event_id: int | None = None) -> Set:
    """Create a new empty set owned by `owner_id`."""
    new_set = Set(owner_id=owner_id, name=name, event_id=event_id)
    db.add(new_set)
    db.commit()
    db.refresh(new_set)
    return new_set


def list_sets(db: Session, owner_id: int) -> list[Set]:
    """List the owner's sets, newest first."""
    return (
        db.query(Set)
        .filter(Set.owner_id == owner_id)
        .order_by(Set.created_at.desc())
        .all()
    )


def get_owned_set(db: Session, set_id: int, owner_id: int) -> Set | None:
    """Fetch a set by id, scoped to the owner. None if missing or unowned."""
    return (
        db.query(Set)
        .filter(Set.id == set_id, Set.owner_id == owner_id)
        .one_or_none()
    )


def rename_set(db: Session, set_obj: Set, name: str) -> Set:
    """Rename a set."""
    set_obj.name = name
    db.commit()
    db.refresh(set_obj)
    return set_obj


def delete_set(db: Session, set_obj: Set) -> None:
    """Delete a set (children cascade via FK ondelete + ORM cascade)."""
    db.delete(set_obj)
    db.commit()
```

- [ ] **Step 3: Run the existing suite to confirm nothing imports break**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_models.py -q`
Expected: PASS (imports resolve; no regressions).

- [ ] **Step 4: Commit**

```bash
git add server/app/schemas/setbuilder.py server/app/services/setbuilder/
git commit -m "feat(setbuilder): add set schemas + owner-scoped CRUD service"
```

---

## Task 6: Setbuilder API router + registration

**Files:**
- Create: `server/app/api/setbuilder.py`
- Modify: `server/app/api/__init__.py`
- Test: `server/tests/test_setbuilder_api.py`

- [ ] **Step 1: Write the failing API tests**

Create `server/tests/test_setbuilder_api.py`:

```python
"""API tests for /api/setbuilder set CRUD (Phase 0).

Pins auth gating (pending users rejected, unauthenticated rejected),
owner isolation (404 on another DJ's set), and the create/list/get/
rename/delete happy paths.
"""

from app.services.auth import get_password_hash


def _make_second_dj(db):
    from app.models.user import User

    user = User(username="otherdj", password_hash=get_password_hash("x" * 12), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, username, password):
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_set(client, auth_headers):
    resp = client.post("/api/setbuilder/sets", json={"name": "Friday Set"}, headers=auth_headers)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["name"] == "Friday Set"
    assert body["status"] == "draft"
    assert body["sharing_mode"] == "private"
    assert body["id"] > 0


def test_create_set_requires_auth(client):
    resp = client.post("/api/setbuilder/sets", json={"name": "X"})
    assert resp.status_code == 401


def test_create_set_rejects_pending_user(client, pending_headers):
    resp = client.post("/api/setbuilder/sets", json={"name": "X"}, headers=pending_headers)
    assert resp.status_code == 403


def test_create_set_validates_name(client, auth_headers):
    resp = client.post("/api/setbuilder/sets", json={"name": ""}, headers=auth_headers)
    assert resp.status_code == 422


def test_list_sets_only_owner(client, auth_headers, db):
    client.post("/api/setbuilder/sets", json={"name": "Mine"}, headers=auth_headers)
    other = _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    client.post("/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers)

    resp = client.get("/api/setbuilder/sets", headers=auth_headers)
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == ["Mine"]


def test_get_set(client, auth_headers):
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Detail"}, headers=auth_headers
    ).json()
    resp = client.get(f"/api/setbuilder/sets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["key_strictness"] == 0.2


def test_get_other_dj_set_returns_404(client, auth_headers, db):
    other = _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = client.post(
        "/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers
    ).json()
    resp = client.get(f"/api/setbuilder/sets/{theirs['id']}", headers=auth_headers)
    assert resp.status_code == 404


def test_rename_set(client, auth_headers):
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Old"}, headers=auth_headers
    ).json()
    resp = client.patch(
        f"/api/setbuilder/sets/{created['id']}", json={"name": "New"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_rename_other_dj_set_returns_404(client, auth_headers, db):
    other = _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = client.post(
        "/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers
    ).json()
    resp = client.patch(
        f"/api/setbuilder/sets/{theirs['id']}", json={"name": "Hax"}, headers=auth_headers
    )
    assert resp.status_code == 404


def test_delete_set(client, auth_headers):
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Doomed"}, headers=auth_headers
    ).json()
    resp = client.delete(f"/api/setbuilder/sets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(
        f"/api/setbuilder/sets/{created['id']}", headers=auth_headers
    ).status_code == 404


def test_delete_other_dj_set_returns_404(client, auth_headers, db):
    other = _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = client.post(
        "/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers
    ).json()
    resp = client.delete(f"/api/setbuilder/sets/{theirs['id']}", headers=auth_headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_api.py -v`
Expected: FAIL (404 on every route — router not registered yet).

- [ ] **Step 3: Write the router**

Create `server/app/api/setbuilder.py`:

```python
"""WrzDJSet set-CRUD router (Phase 0).

Mounted at /api/setbuilder. Every endpoint requires an active DJ
(get_current_active_user rejects pending users). Sets are owner-private;
missing-or-unowned sets return 404 to avoid leaking existence.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.setbuilder import SetCreate, SetDetail, SetRename, SetSummary
from app.services.setbuilder import set_service

router = APIRouter()


def _get_owned_or_404(db: Session, set_id: int, user: User):
    set_obj = set_service.get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


@router.post("/sets", response_model=SetDetail, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_set(
    payload: SetCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Create a new empty set owned by the current DJ."""
    set_obj = set_service.create_set(
        db, owner_id=current_user.id, name=payload.name, event_id=payload.event_id
    )
    return SetDetail.model_validate(set_obj)


@router.get("/sets", response_model=list[SetSummary])
@limiter.limit("60/minute")
def list_sets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[SetSummary]:
    """List the current DJ's sets, newest first."""
    return [SetSummary.model_validate(s) for s in set_service.list_sets(db, current_user.id)]


@router.get("/sets/{set_id}", response_model=SetDetail)
@limiter.limit("60/minute")
def get_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Get one of the current DJ's sets, or 404."""
    return SetDetail.model_validate(_get_owned_or_404(db, set_id, current_user))


@router.patch("/sets/{set_id}", response_model=SetDetail)
@limiter.limit("30/minute")
def rename_set(
    set_id: int,
    payload: SetRename,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Rename one of the current DJ's sets, or 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return SetDetail.model_validate(set_service.rename_set(db, set_obj, payload.name))


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete one of the current DJ's sets, or 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    set_service.delete_set(db, set_obj)
```

- [ ] **Step 4: Register the router**

In `server/app/api/__init__.py`, add `setbuilder` to the import block (alphabetically — after `search`/before `sse`) and add the include line near the other authenticated routers:

```python
api_router.include_router(setbuilder.router, prefix="/setbuilder", tags=["setbuilder"])
```

(place it after the `events` include, e.g. right after the `requests`/`search` includes — order among prefixed routers is cosmetic).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_setbuilder_api.py -v`
Expected: all PASS (11 tests).

- [ ] **Step 6: Run the full backend suite + lint + coverage gate**

Run: `cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q`
Expected: lint clean, bandit clean, all tests pass, coverage gate satisfied. If `ruff format --check` fails, run `.venv/bin/ruff format .` and re-stage.

- [ ] **Step 7: Commit**

```bash
git add server/app/api/setbuilder.py server/app/api/__init__.py server/tests/test_setbuilder_api.py
git commit -m "feat(setbuilder): add /api/setbuilder set CRUD router"
```

---

## Task 7: Frontend API client types + methods

**Files:**
- Modify: `dashboard/lib/api-types.ts`
- Modify: `dashboard/lib/api.ts`

- [ ] **Step 1: Add the shared types**

In `dashboard/lib/api-types.ts`, append these interfaces near the end (before the `PaginatedResponse` block is fine):

```typescript
export interface SetSummary {
  id: number;
  name: string;
  event_id: number | null;
  status: 'draft' | 'locked' | 'exported';
  sharing_mode: 'private' | 'invite_only';
  created_at: string;
  updated_at: string;
}

export interface SetDetail extends SetSummary {
  vibe_theme: string | null;
  target_duration_sec: number | null;
  bpm_floor: number | null;
  bpm_ceiling: number | null;
  key_strictness: number;
  tidal_playlist_id: string | null;
  exported_at: string | null;
}
```

- [ ] **Step 2: Add the client methods**

In `dashboard/lib/api.ts`:

a) Add `SetSummary` and `SetDetail` to the `import type { ... } from './api-types'` block AND to the `export type { ... }` re-export block (both alphabetical lists — `SetDetail`/`SetSummary` go after `SearchResult`).

b) Add these methods to the `ApiClient` class (next to `deleteEvent`):

```typescript
  async listSets(): Promise<SetSummary[]> {
    return this.fetch('/api/setbuilder/sets');
  }
  async createSet(name: string, eventId?: number): Promise<SetDetail> {
    return this.fetch('/api/setbuilder/sets', {
      method: 'POST',
      body: JSON.stringify({ name, event_id: eventId ?? null }),
    });
  }
  async getSet(setId: number): Promise<SetDetail> {
    return this.fetch(`/api/setbuilder/sets/${setId}`);
  }
  async renameSet(setId: number, name: string): Promise<SetDetail> {
    return this.fetch(`/api/setbuilder/sets/${setId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }
  async deleteSet(setId: number): Promise<void> {
    await this.rawFetch(`/api/setbuilder/sets/${setId}`, { method: 'DELETE' });
  }
```

- [ ] **Step 3: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/api-types.ts dashboard/lib/api.ts
git commit -m "feat(setbuilder): add set CRUD methods to frontend API client"
```

---

## Task 8: Dashboard set-list page

**Files:**
- Create: `dashboard/app/setbuilder/page.tsx`
- Create: `dashboard/app/setbuilder/__tests__/page.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `dashboard/app/setbuilder/__tests__/page.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SetbuilderPage from '../page';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const mockListSets = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    listSets: () => mockListSets(),
    createSet: vi.fn(),
    deleteSet: vi.fn(),
    renameSet: vi.fn(),
  },
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false, role: 'dj' }),
}));

describe('SetbuilderPage', () => {
  beforeEach(() => {
    mockListSets.mockReset();
  });

  it('renders the empty state when there are no sets', async () => {
    mockListSets.mockResolvedValue([]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText(/no sets yet/i)).toBeInTheDocument();
    });
  });

  it('renders set cards from the API', async () => {
    mockListSets.mockResolvedValue([
      {
        id: 1,
        name: 'Friday Wedding',
        event_id: null,
        status: 'draft',
        sharing_mode: 'private',
        created_at: '2026-06-07T00:00:00Z',
        updated_at: '2026-06-07T00:00:00Z',
      },
    ]);
    render(<SetbuilderPage />);
    await waitFor(() => {
      expect(screen.getByText('Friday Wedding')).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd dashboard && npm test -- --run app/setbuilder`
Expected: FAIL — cannot resolve `../page`.

- [ ] **Step 3: Write the set-list page**

Create `dashboard/app/setbuilder/page.tsx`:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { SetSummary } from '@/lib/api-types';

export default function SetbuilderPage() {
  const { isAuthenticated, isLoading, role } = useAuth();
  const router = useRouter();
  const [sets, setSets] = useState<SetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role === 'pending') {
      router.push('/pending');
    }
  }, [isAuthenticated, isLoading, role, router]);

  useEffect(() => {
    if (isAuthenticated) {
      api
        .listSets()
        .then(setSets)
        .catch(() => setError('Failed to load sets'))
        .finally(() => setLoading(false));
    }
  }, [isAuthenticated]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await api.createSet(newName.trim());
      setSets((prev) => [created, ...prev]);
      setNewName('');
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create set');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this set? This cannot be undone.')) return;
    try {
      await api.deleteSet(id);
      setSets((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete set');
    }
  };

  if (isLoading || !isAuthenticated) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      {error && (
        <div
          style={{
            background: 'var(--color-danger-subtle)',
            color: 'var(--color-danger)',
            padding: '0.75rem 1rem',
            borderRadius: '0.5rem',
            marginBottom: '1rem',
            fontSize: '0.875rem',
          }}
        >
          {error}
        </div>
      )}

      <div className="header">
        <h1>Sets</h1>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <Link
            href="/dashboard"
            className="btn"
            style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
          >
            Dashboard
          </Link>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            New Set
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="card" style={{ marginBottom: '2rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Create New Set</h2>
          <form onSubmit={handleCreate}>
            <div className="form-group">
              <label htmlFor="setName">Set Name</label>
              <input
                id="setName"
                type="text"
                className="input"
                placeholder="Friday Wedding"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                maxLength={120}
                required
              />
            </div>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <button type="submit" className="btn btn-primary" disabled={creating}>
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                type="button"
                className="btn"
                style={{ background: 'var(--surface-raised)' }}
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="loading">Loading sets...</div>
      ) : sets.length === 0 ? (
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)' }}>No sets yet. Create your first set!</p>
        </div>
      ) : (
        <div className="event-grid">
          {sets.map((s) => (
            <div key={s.id} className="event-card" style={{ position: 'relative' }}>
              <Link href={`/setbuilder/${s.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                <h3>{s.name}</h3>
                <div className="code">{s.status}</div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Updated: {new Date(s.updated_at).toLocaleString()}
                </p>
              </Link>
              <button
                className="btn btn-sm btn-danger"
                style={{ marginTop: '0.75rem' }}
                onClick={() => handleDelete(s.id)}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd dashboard && npm test -- --run app/setbuilder`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/setbuilder/page.tsx dashboard/app/setbuilder/__tests__/page.test.tsx
git commit -m "feat(setbuilder): add set-list dashboard page"
```

---

## Task 9: Builder workspace shell (4-panel grid)

**Files:**
- Create: `dashboard/app/setbuilder/[setId]/page.tsx`
- Create: `dashboard/app/setbuilder/setbuilder.module.css`

The exec-summary workspace is a 3-column grid (Pool 320px | center | Chat 360px) where the center stacks Curve over Timeline. The issue asks for a "4-panel grid (Pool / Curve / Timeline / Chat placeholders)". **Decision:** render all four as distinct panels in a CSS grid — Pool (left, full height), Curve (top center), Timeline (bottom center), Chat (right, full height) — using `grid-template-areas`. This satisfies "4-panel" while preserving the design's spatial intent.

- [ ] **Step 1: Write the scoped CSS**

Create `dashboard/app/setbuilder/setbuilder.module.css`:

```css
.workspace {
  display: grid;
  grid-template-columns: 320px 1fr 360px;
  grid-template-rows: minmax(200px, 40%) 1fr;
  grid-template-areas:
    'pool curve chat'
    'pool timeline chat';
  gap: 1px;
  height: calc(100vh - 56px);
  background: var(--border-subtle);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 1rem;
  background: var(--card);
  border-bottom: 1px solid var(--border);
}

.topbarTitle {
  font-family: var(--font-display), sans-serif;
  font-weight: 600;
  font-size: 1rem;
  color: var(--text);
}

.panel {
  background: var(--bg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panelPool {
  grid-area: pool;
}
.panelCurve {
  grid-area: curve;
}
.panelTimeline {
  grid-area: timeline;
}
.panelChat {
  grid-area: chat;
}

.panelHeader {
  padding: 0.75rem 1rem;
  font-family: var(--font-display), sans-serif;
  font-size: 0.8125rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-subtle);
}

.panelBody {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  color: var(--text-secondary);
  font-size: 0.875rem;
  text-align: center;
}
```

- [ ] **Step 2: Write the builder page**

Create `dashboard/app/setbuilder/[setId]/page.tsx`:

```tsx
'use client';

import { use, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api-types';
import styles from '../setbuilder.module.css';

export default function BuilderPage({ params }: { params: Promise<{ setId: string }> }) {
  const { setId } = use(params);
  const { isAuthenticated, isLoading, role } = useAuth();
  const router = useRouter();
  const [set, setSet] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role === 'pending') {
      router.push('/pending');
    }
  }, [isAuthenticated, isLoading, role, router]);

  useEffect(() => {
    if (isAuthenticated) {
      api
        .getSet(Number(setId))
        .then(setSet)
        .catch(() => setError('Set not found'));
    }
  }, [isAuthenticated, setId]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--color-danger)' }}>{error}</p>
          <Link href="/setbuilder" className="btn btn-primary" style={{ marginTop: '1rem', textDecoration: 'none' }}>
            Back to Sets
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className={styles.topbar}>
        <Link
          href="/setbuilder"
          className="btn btn-sm"
          style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
        >
          ← Sets
        </Link>
        <span className={styles.topbarTitle}>{set?.name ?? 'Loading…'}</span>
        <span style={{ width: 60 }} />
      </div>

      <div className={styles.workspace}>
        <section className={`${styles.panel} ${styles.panelPool}`} aria-label="Pool">
          <div className={styles.panelHeader}>Pool</div>
          <div className={styles.panelBody}>Candidate tracks will appear here.</div>
        </section>

        <section className={`${styles.panel} ${styles.panelCurve}`} aria-label="Curve">
          <div className={styles.panelHeader}>Curve</div>
          <div className={styles.panelBody}>Energy curve editor coming soon.</div>
        </section>

        <section className={`${styles.panel} ${styles.panelTimeline}`} aria-label="Timeline">
          <div className={styles.panelHeader}>Timeline</div>
          <div className={styles.panelBody}>Ordered set timeline coming soon.</div>
        </section>

        <section className={`${styles.panel} ${styles.panelChat}`} aria-label="Chat">
          <div className={styles.panelHeader}>Chat</div>
          <div className={styles.panelBody}>Agent chat coming soon.</div>
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Type-check + lint + test**

Run: `cd dashboard && npx tsc --noEmit && npm run lint && npm test -- --run`
Expected: tsc clean, ESLint clean, all vitest tests pass.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/setbuilder/\[setId\]/page.tsx dashboard/app/setbuilder/setbuilder.module.css
git commit -m "feat(setbuilder): add builder workspace shell with 4-panel grid"
```

---

## Task 10: Full local CI sweep + finishing

**Files:** none (verification + handoff)

- [ ] **Step 1: Backend CI (from `server/`)**

Run:
```bash
cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q && .venv/bin/alembic upgrade head && .venv/bin/alembic check
```
Expected: every step green; `alembic check` says no new operations; coverage gate satisfied.

- [ ] **Step 2: Frontend CI (from `dashboard/`)**

Run:
```bash
cd dashboard && npm run lint && npx tsc --noEmit && npm test -- --run
```
Expected: every step green. (Restore `next-env.d.ts` with `git checkout dashboard/next-env.d.ts` if a build touched it.)

- [ ] **Step 3: Finish the branch**

Use superpowers:finishing-a-development-branch, choose **option 2 (Push + PR against main)**. The PR body MUST include `Closes #387`, a `## Design decisions` section (lift the decisions list above), and a test plan section.

---

## Self-Review

**Spec coverage:**
- Models `Set`, `SetSlot`, `SetCurvePoint`, `SetCollaborator` → Task 2. ✔
- Models `TrackVibe`, `TrackVibeOverride` incl. 5-col UNIQUE → Task 1. ✔
- Alembic migration, single head, `alembic check` clean → Task 3 + Task 10. ✔
- Router `/api/setbuilder/*` gated by `get_current_active_user`, set CRUD only → Task 6. ✔
- LLM gateway interface stub delegating to `llm_client.py`, no provider SDK import → Task 4. ✔
- Dashboard set list + builder 4-panel shell with design tokens → Tasks 8, 9. ✔
- Acceptance "authenticated DJ can create/list/rename/delete an empty set" → Task 6 tests. ✔
- Acceptance "no direct LLM provider SDK import anywhere in setbuilder code" → Task 4 AST test + manual review. ✔

**Placeholder scan:** No TBD/TODO/"handle edge cases" — every code step is concrete.

**Type consistency:** `SetSummary`/`SetDetail` match between `schemas/setbuilder.py` (Task 5), `api-types.ts` (Task 7), and the page imports (Tasks 8, 9). Gateway `dispatch`/`GatewayResponse`/`MODEL_HINTS` names match between `gateway.py` (Task 4) and its test. Service function names (`create_set`, `list_sets`, `get_owned_set`, `rename_set`, `delete_set`) match between `set_service.py` (Task 5) and the router (Task 6). Migration column names/types/server_defaults match the models (Tasks 1–3).

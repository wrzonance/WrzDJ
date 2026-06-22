# autobuild + fill_to_duration Agent Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two destructive Family-3 WrzDJSet agent tools — `autobuild` (regenerate the whole order) and `fill_to_duration` (append pool tracks to the duration target) — riding the existing global undo for recovery.

**Architecture:** Two new mutating tools in a new `agent_tools_structural.py` module, wired through the existing closed allowlist (`MUTATION_TOOLS` + `_agent_tools()` + `apply_tool_call` + `_tool_display_summary`). `autobuild` wraps `pass1_deterministic.build_set` (which already honors locked slots + saved pairings); `fill_to_duration` appends unused pool tracks via the existing `_insert_track_at` primitive. Undo is **not** re-implemented — #493/#494's global undo snapshots the whole document before every mutating turn, so these tools are revertible for free; the only frontend change is a discoverability hint.

**Tech Stack:** FastAPI + SQLAlchemy backend (pytest, SQLite in-memory test DB), Next.js/React 19 frontend (Vitest + Testing Library, vanilla CSS modules).

**Spec:** `docs/superpowers/specs/2026-06-21-setbuilder-autobuild-fill-design.md`
**Issue:** #491 (epic #442, Family 3). **Branch:** `feat/issue-491-autobuild-fill-duration` (already created).

## Global Constraints

- Backend lint: ruff line-length 100, rules E, F, I, UP. `== None` / `== True` allowed. Run `.venv/bin/ruff format .` after edits.
- Backend coverage is an **enforced hard gate at 85%** (`--cov-fail-under`). New code must be covered.
- Every mutating agent tool: `db.flush()` not `db.commit()` (the turn owns commit/rollback); member of `MUTATION_TOOLS`; requires a non-empty `rationale`; owner-scoped via the already-scoped `set_obj`; **never writes the `requests` table** (pin with a regression test).
- Tools are dispatched only through `apply_tool_call`'s closed allowlist; an unknown name raises `AgentToolError`.
- Frontend: vanilla CSS modules + `var(--*)` design tokens only — no Tailwind, no hardcoded hex.
- Commits: Conventional Commits; end every commit with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- All backend commands run from `server/`; frontend from `dashboard/`.

---

## File Structure

**Create:**
- `server/app/services/setbuilder/agent_tools_structural.py` — the two structural tools + `_duration_for` helper + `MAX_FILL_INSERTS`.
- `server/tests/test_setbuilder_structural.py` — tests for both tools (the existing `test_setbuilder_pass2.py` is 2517 lines, well over budget — do not add to it).

**Modify:**
- `server/app/services/setbuilder/pass1_deterministic.py` — thread `commit: bool = True` through `build_set` / `_persist_slots`.
- `server/app/services/setbuilder/agent_common.py` — add 2 names to `MUTATION_TOOLS`.
- `server/app/services/setbuilder/agent_tool_specs.py` — add 2 `ToolSpec`s.
- `server/app/services/setbuilder/pass2_agent.py` — import + 2 handler entries.
- `server/app/services/setbuilder/agent_display.py` — 2 display-summary cases.
- `server/tests/test_setbuilder_pass1.py` — test for the `commit` param.
- `dashboard/app/(dj)/setbuilder/components/ChatPanelBody.tsx` — destructive-tool undo hint.
- `dashboard/app/(dj)/setbuilder/setbuilder.module.css` — `.toolUndoHint` class.
- `dashboard/app/(dj)/setbuilder/components/__tests__/ChatPanelBody.test.tsx` — hint test.

---

## Task 1: `build_set` gains a `commit` flag

`autobuild` must run inside an agent turn that owns the single commit/rollback, but `build_set` currently commits internally. Add an opt-out so the agent path flushes instead. The one existing REST caller keeps the default and is unchanged.

**Files:**
- Modify: `server/app/services/setbuilder/pass1_deterministic.py` (`build_set` ~L55-102, `_persist_slots` ~L421-453)
- Test: `server/tests/test_setbuilder_pass1.py`

**Interfaces:**
- Produces: `build_set(db, set_obj, *, commit: bool = True) -> BuildResult` — when `commit=False`, persists via `db.flush()` only (caller commits/rolls back). `BuildResult` unchanged (`.slots`, `.slot_count`, `.iterations`, `.transition_scores`).

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_setbuilder_pass1.py`:

```python
def test_build_set_commit_false_defers_persistence_to_caller(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=7 * 60)
    src = _mk_source(db, set_obj)
    for idx in range(4):
        _mk_track(db, set_obj, src, idx)

    # commit=False only flushes, so a rollback discards the generated slots.
    build_set(db, set_obj, commit=False)
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() > 0
    db.rollback()
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() == 0

    # Default commit=True persists across a rollback.
    build_set(db, set_obj)
    db.rollback()
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_setbuilder_pass1.py::test_build_set_commit_false_defers_persistence_to_caller -v`
Expected: FAIL — `build_set()` got an unexpected keyword argument `commit`.

- [ ] **Step 3: Implement the `commit` flag**

In `pass1_deterministic.py`, change the `build_set` signature and its persistence calls:

```python
def build_set(db: Session, set_obj: Set, *, commit: bool = True) -> BuildResult:
    """Build and persist a deterministic ordered set from the set pool."""
```

Replace the two persistence lines near the end of `build_set` (currently `slots = _persist_slots(...)` then `scores = recompute_transition_scores(db, set_obj, slots)`):

```python
    slots = _persist_slots(db, set_obj.id, locked_by_pos, chosen, targets, commit=commit)
    scores = recompute_transition_scores(db, set_obj, slots, commit=commit)
```

Change `_persist_slots` to accept and honor `commit` (it currently ends with `db.commit()`):

```python
def _persist_slots(
    db: Session,
    set_id: int,
    locked_by_pos: dict[int, SetSlot],
    chosen: list[TrackMeta | None],
    targets: list[float],
    *,
    commit: bool = True,
) -> list[SetSlot]:
```

and replace its final `db.commit()` with:

```python
    if commit:
        db.commit()
    else:
        db.flush()
    return _ordered_slots(db, set_id)
```

(`recompute_transition_scores` already has a `commit: bool = True` param that flushes when `False` — no change needed there.)

- [ ] **Step 4: Run test + format to verify it passes**

Run: `.venv/bin/ruff format app/services/setbuilder/pass1_deterministic.py && .venv/bin/pytest tests/test_setbuilder_pass1.py -v`
Expected: PASS (all pass1 tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add server/app/services/setbuilder/pass1_deterministic.py server/tests/test_setbuilder_pass1.py
git commit -m "feat(setbuilder): add commit flag to build_set for agent-turn atomicity (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `autobuild` tool

Wholesale regeneration via `build_set(commit=False)`. Includes the new module, full allowlist wiring, display summary, and the snapshot round-trip acceptance test proving the global-undo guarantee.

**Files:**
- Create: `server/app/services/setbuilder/agent_tools_structural.py`
- Create: `server/tests/test_setbuilder_structural.py`
- Modify: `server/app/services/setbuilder/agent_common.py` (`MUTATION_TOOLS` ~L15-34)
- Modify: `server/app/services/setbuilder/agent_tool_specs.py` (`_agent_tools()` list ~after L123)
- Modify: `server/app/services/setbuilder/pass2_agent.py` (imports ~L32, `handlers` dict ~L306-332)
- Modify: `server/app/services/setbuilder/agent_display.py` (`_tool_display_summary` ~before the final fallback `return`)

**Interfaces:**
- Consumes: `build_set(db, set_obj, *, commit=False)` (Task 1).
- Produces: `_tool_autobuild(db, set_obj, payload) -> tuple[dict, set[int]]` returning `({"slot_count": int, "iterations": int}, affected_positions)`. Tool name `"autobuild"`, in `MUTATION_TOOLS`, requires `rationale`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_setbuilder_structural.py`:

```python
"""Tests for the destructive structural WrzDJSet agent tools (#491, #442 Family 3)."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.setbuilder.agent_display import _tool_display_summary
from app.services.setbuilder.document_snapshot import build_snapshot, restore_snapshot
from app.services.setbuilder.pass2_agent import (
    MUTATION_TOOLS,
    AgentToolError,
    apply_tool_call,
    chat_with_agent,
)


def _mk_set(db: Session, user: User, *, n_tracks: int, n_slots: int, duration: int) -> Set:
    """Set with ``n_tracks`` pool tracks (210s each) and ``n_slots`` seeded slots."""
    set_obj = Set(owner_id=user.id, name="Structural Set", target_duration_sec=duration)
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.flush()
    db.add_all(
        [
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                track_id=f"tidal:{idx}",
                title=f"Track {idx}",
                artist=f"Artist {idx}",
                bpm=124 + idx,
                key="8A",
                camelot="8A",
                energy=5,
                duration_sec=210,
                dedupe_sig=f"struct-sig-{idx}",
            )
            for idx in range(n_tracks)
        ]
    )
    db.flush()
    db.add_all(
        [SetSlot(set_id=set_obj.id, position=i, track_id=f"tidal:{i}") for i in range(n_slots)]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_autobuild_regenerates_order_and_reports_counts(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=4, n_slots=0, duration=14 * 60)

    result, positions = apply_tool_call(
        db, set_obj, "autobuild", {"rationale": "Auto-arrange from the pool."}
    )

    slots = db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).all()
    assert result["slot_count"] == len(slots)
    assert result["slot_count"] > 0
    assert isinstance(result["iterations"], int)
    assert positions == {s.position for s in slots}


def test_autobuild_preserves_locked_slot(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=6, n_slots=0, duration=14 * 60)
    db.add(SetSlot(set_id=set_obj.id, position=1, track_id="tidal:5", locked=True))
    db.commit()

    apply_tool_call(db, set_obj, "autobuild", {"rationale": "Rebuild around the pin."})

    locked = (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id, SetSlot.locked == True)  # noqa: E712
        .one()
    )
    assert locked.position == 1
    assert locked.track_id == "tidal:5"


def test_autobuild_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=0, duration=7 * 60)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "autobuild", {})


def test_autobuild_in_mutation_tools():
    assert "autobuild" in MUTATION_TOOLS


def test_autobuild_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set(db, test_user, n_tracks=4, n_slots=0, duration=14 * 60)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "autobuild", {"rationale": "Rebuild it."})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


@pytest.mark.asyncio
async def test_autobuild_then_failing_tool_rolls_back_whole_turn(
    monkeypatch, db: Session, test_user: User
):
    """commit=False means a later tool failure rolls the autobuild back too."""
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=2, duration=7 * 60)
    original = [
        s.track_id
        for s in db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id)
        .order_by(SetSlot.position)
        .all()
    ]

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(id="ab", name="autobuild", input={"rationale": "Rebuild."}),
                ToolCall(
                    id="boom",
                    name="swap_slots",
                    input={"slot_a_id": 999999, "slot_b_id": 999998, "rationale": "boom"},
                ),
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    with pytest.raises(AgentToolError):
        await chat_with_agent(db, test_user, set_obj, message="Rebuild then break")

    remaining = [
        s.track_id
        for s in db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id)
        .order_by(SetSlot.position)
        .all()
    ]
    assert remaining == original


def test_autobuild_then_restore_snapshot_returns_prior_order(db: Session, test_user: User):
    """#491 acceptance: the captured snapshot restores the exact pre-autobuild order."""
    set_obj = _mk_set(db, test_user, n_tracks=4, n_slots=2, duration=14 * 60)
    before = build_snapshot(set_obj)
    before_ids = [s.track_id for s in sorted(set_obj.slots, key=lambda s: s.position)]

    apply_tool_call(db, set_obj, "autobuild", {"rationale": "Rebuild wholesale."})
    db.commit()
    db.refresh(set_obj)

    restore_snapshot(db, set_obj, before)
    db.refresh(set_obj)

    after_ids = [s.track_id for s in sorted(set_obj.slots, key=lambda s: s.position)]
    assert after_ids == before_ids


def test_autobuild_display_summary_is_human_readable():
    summary = _tool_display_summary(
        "autobuild", {"rationale": "x"}, {"slot_count": 12, "iterations": 3}, {}, {}
    )
    assert summary == "Rebuilt the set: 12 slots, 3 refinement passes."

    one = _tool_display_summary(
        "autobuild", {"rationale": "x"}, {"slot_count": 1, "iterations": 1}, {}, {}
    )
    assert one == "Rebuilt the set: 1 slot, 1 refinement pass."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_setbuilder_structural.py -v`
Expected: FAIL — `AgentToolError: Unknown tool: autobuild` (and the MUTATION_TOOLS/display assertions fail).

- [ ] **Step 3: Create the structural module**

Create `server/app/services/setbuilder/agent_tools_structural.py`:

```python
"""Destructive structural WrzDJSet agent tools (#491, #442 Family 3).

``autobuild`` regenerates the whole order from the pool + curve; both tools are
in ``MUTATION_TOOLS`` and dispatched only through ``apply_tool_call``. They are
undoable via the frontend global-undo stack (#493/#494), which snapshots the
whole document before every mutating agent turn.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.pass1_deterministic import build_set


def _tool_autobuild(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Regenerate the entire ordering from the pool + curve (wholesale).

    Thin owner-scoped wrapper over ``pass1_deterministic.build_set``, which
    already honors locked slots and saved pairings. Runs with ``commit=False``
    so the agent turn commits/rolls back as one unit.
    """
    result = build_set(db, set_obj, commit=False)
    affected = {slot.position for slot in result.slots}
    return {"slot_count": result.slot_count, "iterations": result.iterations}, affected
```

- [ ] **Step 4: Wire `autobuild` into the allowlist**

In `agent_common.py`, add `"autobuild"` to the `MUTATION_TOOLS` set (e.g. after `"apply_curve_template",`):

```python
    "apply_curve_template",
    "autobuild",
```

In `agent_tool_specs.py`, add this `ToolSpec` to the `_agent_tools()` list immediately after the `apply_curve_template` `ToolSpec` block (before the `analyze_transition` block):

```python
        ToolSpec(
            name="autobuild",
            description=(
                "Regenerate the ENTIRE set order from the pool and energy curve "
                "(deterministic pass 1). This REPLACES the current hand-arranged "
                "order wholesale; locked slots and saved pairings are preserved. "
                "Destructive — use only when the DJ asks to rebuild / auto-arrange."
            ),
            input_schema={
                "type": "object",
                "properties": {"rationale": {"type": "string"}},
                "required": ["rationale"],
            },
        ),
```

In `pass2_agent.py`, add the import (after the `agent_tools_sensing` import block, ~L62):

```python
from app.services.setbuilder.agent_tools_structural import _tool_autobuild
```

and add to the `handlers` dict in `apply_tool_call` (after `"apply_curve_template": _tool_apply_curve_template,`):

```python
        "autobuild": _tool_autobuild,
```

- [ ] **Step 5: Add the display summary**

In `agent_display.py`, add this case to `_tool_display_summary` just before the final fallback `return name.replace("_", " ").capitalize() + "."`:

```python
    if name == "autobuild":
        slots = int(result.get("slot_count") or 0)
        iterations = int(result.get("iterations") or 0)
        return (
            f"Rebuilt the set: {slots} slot{'s' if slots != 1 else ''}, "
            f"{iterations} refinement pass{'es' if iterations != 1 else ''}."
        )
```

- [ ] **Step 6: Run tests + format to verify they pass**

Run: `.venv/bin/ruff format app/services/setbuilder/ && .venv/bin/pytest tests/test_setbuilder_structural.py -v`
Expected: PASS (all autobuild tests).

- [ ] **Step 7: Commit**

```bash
git add server/app/services/setbuilder/agent_tools_structural.py \
        server/app/services/setbuilder/agent_common.py \
        server/app/services/setbuilder/agent_tool_specs.py \
        server/app/services/setbuilder/pass2_agent.py \
        server/app/services/setbuilder/agent_display.py \
        server/tests/test_setbuilder_structural.py
git commit -m "feat(setbuilder): autobuild agent tool — wholesale pass-1 rebuild (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `fill_to_duration` tool

Append unused pool tracks until the set reaches `target_duration_sec`, bounded by a per-turn cap.

**Files:**
- Modify: `server/app/services/setbuilder/agent_tools_structural.py`
- Modify: `server/app/services/setbuilder/agent_common.py` (`MUTATION_TOOLS`)
- Modify: `server/app/services/setbuilder/agent_tool_specs.py` (`_agent_tools()`)
- Modify: `server/app/services/setbuilder/pass2_agent.py` (import + handler)
- Modify: `server/app/services/setbuilder/agent_display.py`
- Test: `server/tests/test_setbuilder_structural.py`

**Interfaces:**
- Consumes: `_insert_track_at(db, set_obj, track, position)` from `agent_tools_mutations.py`; `AVG_TRACK_LENGTH_SEC` + `_track_meta` from `pass1_deterministic.py`; `_pool_tracks`/`_ordered_slots` from `agent_common.py`.
- Produces: `_tool_fill_to_duration(db, set_obj, payload) -> tuple[dict, set[int]]` returning `({"inserted_count", "estimated_total_sec", "target_duration_sec", "capped", "pool_exhausted"}, affected)`. Module constant `MAX_FILL_INSERTS = 100`. Tool name `"fill_to_duration"`, in `MUTATION_TOOLS`, requires `rationale`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_setbuilder_structural.py`:

```python
def test_fill_to_duration_stops_at_target(db: Session, test_user: User):
    # 1 seeded slot (210s) + 4 unused tracks; target 840s needs 3 more (4*210=840).
    set_obj = _mk_set(db, test_user, n_tracks=5, n_slots=1, duration=4 * 210)

    result, positions = apply_tool_call(
        db, set_obj, "fill_to_duration", {"rationale": "Fill to the target."}
    )

    assert result["inserted_count"] == 3
    assert result["estimated_total_sec"] == 4 * 210
    assert result["capped"] is False
    assert result["pool_exhausted"] is False
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() == 4
    assert positions == {1, 2, 3}


def test_fill_to_duration_stops_when_pool_exhausted(db: Session, test_user: User):
    # Only 2 unused tracks but the target wants far more — stop, flag exhausted.
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=99 * 210)

    result, _ = apply_tool_call(
        db, set_obj, "fill_to_duration", {"rationale": "Use everything available."}
    )

    assert result["inserted_count"] == 2
    assert result["pool_exhausted"] is True
    assert result["capped"] is False


def test_fill_to_duration_respects_insert_cap(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=6, n_slots=1, duration=99 * 210)
    monkeypatch.setattr(
        "app.services.setbuilder.agent_tools_structural.MAX_FILL_INSERTS", 2
    )

    result, _ = apply_tool_call(
        db, set_obj, "fill_to_duration", {"rationale": "Bounded fill."}
    )

    assert result["inserted_count"] == 2
    assert result["capped"] is True


def test_fill_to_duration_errors_without_target(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=7 * 60)
    set_obj.target_duration_sec = None
    db.commit()

    with pytest.raises(AgentToolError, match="target duration"):
        apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Fill it."})


def test_fill_to_duration_never_moves_locked_slot(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=5, n_slots=0, duration=4 * 210)
    db.add(SetSlot(set_id=set_obj.id, position=0, track_id="tidal:0", locked=True))
    db.commit()

    apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Append after the pin."})

    locked = (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id, SetSlot.locked == True)  # noqa: E712
        .one()
    )
    assert locked.position == 0
    assert locked.track_id == "tidal:0"


def test_fill_to_duration_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=7 * 60)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "fill_to_duration", {})


def test_fill_to_duration_in_mutation_tools():
    assert "fill_to_duration" in MUTATION_TOOLS


def test_fill_to_duration_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set(db, test_user, n_tracks=5, n_slots=1, duration=4 * 210)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Fill to target."})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_fill_to_duration_display_summary_is_human_readable():
    added = _tool_display_summary(
        "fill_to_duration",
        {"rationale": "x"},
        {
            "inserted_count": 3,
            "estimated_total_sec": 840,
            "target_duration_sec": 840,
            "capped": False,
            "pool_exhausted": False,
        },
        {},
        {},
    )
    assert added == "Added 3 tracks toward target; now ~14 min of ~14 min."

    none_added = _tool_display_summary(
        "fill_to_duration",
        {"rationale": "x"},
        {
            "inserted_count": 0,
            "estimated_total_sec": 600,
            "target_duration_sec": 600,
            "capped": False,
            "pool_exhausted": False,
        },
        {},
        {},
    )
    assert none_added == "No tracks added; set already ~10 min of ~10 min target."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_setbuilder_structural.py -k fill_to_duration -v`
Expected: FAIL — `AgentToolError: Unknown tool: fill_to_duration`.

- [ ] **Step 3: Implement `fill_to_duration` + helper**

In `agent_tools_structural.py`, extend the imports and add the constant + helper + tool. Final import block:

```python
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.agent_common import AgentToolError, _ordered_slots, _pool_tracks
from app.services.setbuilder.agent_tools_mutations import _insert_track_at
from app.services.setbuilder.pass1_deterministic import AVG_TRACK_LENGTH_SEC, build_set
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta

logger = logging.getLogger(__name__)

# Per-turn safety cap: one fill_to_duration call can never append more than this
# many slots, independent of pool size (the issue's bounded-insert requirement).
MAX_FILL_INSERTS = 100
```

Add the helper and tool below `_tool_autobuild`:

```python
def _duration_for(track) -> int:
    """A pool track's duration in seconds, falling back to the pass-1 average."""
    if track is not None and track.duration_sec and track.duration_sec > 0:
        return track.duration_sec
    return AVG_TRACK_LENGTH_SEC


def _tool_fill_to_duration(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Append unused pool tracks (in pool order) until the set reaches its
    ``target_duration_sec``, never moving locked slots and never appending more
    than ``MAX_FILL_INSERTS`` in one turn.
    """
    target = set_obj.target_duration_sec
    if not target:
        raise AgentToolError("Set a target duration first (target_duration_sec).")

    pool = _pool_tracks(db, set_obj.id)
    by_slot_track_id = {_pass1_track_meta(t).slot_track_id: t for t in pool}
    slots = _ordered_slots(db, set_obj.id)
    used = {slot.track_id for slot in slots if slot.track_id}
    total = sum(_duration_for(by_slot_track_id.get(slot.track_id)) for slot in slots)
    candidates = [t for t in pool if _pass1_track_meta(t).slot_track_id not in used]

    base_count = len(slots)
    affected: set[int] = set()
    inserted = 0
    capped = False
    for track in candidates:
        if total >= target:
            break
        if inserted >= MAX_FILL_INSERTS:
            capped = True
            break
        _, positions = _insert_track_at(db, set_obj, track, base_count + inserted)
        affected |= positions
        total += _duration_for(track)
        inserted += 1

    pool_exhausted = total < target and not capped
    logger.info(
        "setbuilder fill_to_duration: set %s added %s tracks (target=%ss, est_total=%ss, "
        "capped=%s, pool_exhausted=%s)",
        set_obj.id,
        inserted,
        target,
        total,
        capped,
        pool_exhausted,
    )
    return {
        "inserted_count": inserted,
        "estimated_total_sec": total,
        "target_duration_sec": target,
        "capped": capped,
        "pool_exhausted": pool_exhausted,
    }, affected
```

- [ ] **Step 4: Wire `fill_to_duration` into the allowlist**

In `agent_common.py`, add `"fill_to_duration"` to `MUTATION_TOOLS` (after `"autobuild",`):

```python
    "autobuild",
    "fill_to_duration",
```

In `agent_tool_specs.py`, add this `ToolSpec` right after the `autobuild` `ToolSpec`:

```python
        ToolSpec(
            name="fill_to_duration",
            description=(
                "Append pool tracks not already in the set, in pool order, until "
                "the set reaches its target_duration_sec. Requires a duration "
                "target. Never moves locked slots; the number of inserts is capped "
                "per turn. Can add many slots at once — destructive-ish."
            ),
            input_schema={
                "type": "object",
                "properties": {"rationale": {"type": "string"}},
                "required": ["rationale"],
            },
        ),
```

In `pass2_agent.py`, extend the structural import:

```python
from app.services.setbuilder.agent_tools_structural import _tool_autobuild, _tool_fill_to_duration
```

and add to the `handlers` dict (after `"autobuild": _tool_autobuild,`):

```python
        "fill_to_duration": _tool_fill_to_duration,
```

- [ ] **Step 5: Add the display summary**

In `agent_display.py`, add this case just before the final fallback `return` (after the `autobuild` case):

```python
    if name == "fill_to_duration":
        added = int(result.get("inserted_count") or 0)
        now_min = int(result.get("estimated_total_sec") or 0) // 60
        target_min = int(result.get("target_duration_sec") or 0) // 60
        if added == 0:
            return f"No tracks added; set already ~{now_min} min of ~{target_min} min target."
        base = (
            f"Added {added} track{'s' if added != 1 else ''} toward target; "
            f"now ~{now_min} min of ~{target_min} min."
        )
        return f"{base} Hit the per-turn insert cap." if result.get("capped") else base
```

- [ ] **Step 6: Run tests + format to verify they pass**

Run: `.venv/bin/ruff format app/services/setbuilder/ && .venv/bin/pytest tests/test_setbuilder_structural.py -v`
Expected: PASS (all structural tests).

- [ ] **Step 7: Commit**

```bash
git add server/app/services/setbuilder/agent_tools_structural.py \
        server/app/services/setbuilder/agent_common.py \
        server/app/services/setbuilder/agent_tool_specs.py \
        server/app/services/setbuilder/pass2_agent.py \
        server/app/services/setbuilder/agent_display.py \
        server/tests/test_setbuilder_structural.py
git commit -m "feat(setbuilder): fill_to_duration agent tool — bounded pool fill to target (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Backend full-suite + lint gate

Confirm the whole backend suite and the lint/coverage gates are green before touching the frontend.

**Files:** none (verification only).

- [ ] **Step 1: Lint, format check, full suite**

Run:
```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest --tb=short -q
```
Expected: ruff clean; all tests pass; coverage ≥ 85% (no `--cov-fail-under` failure).

- [ ] **Step 2: If coverage dipped, add the missing-branch test**

If the gate reports an uncovered line in `agent_tools_structural.py`, add a focused test to `test_setbuilder_structural.py` covering it (e.g. the `_duration_for` fallback when a slot's track is missing `duration_sec`), then re-run Step 1. Commit any addition:

```bash
git add server/tests/test_setbuilder_structural.py
git commit -m "test(setbuilder): cover structural-tool edge branch (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend undo-discoverability hint

Destructive ToolCards tell the DJ the rebuild is revertible via the existing global undo. Presentational only — no new undo path, no type changes.

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/ChatPanelBody.tsx` (`ToolCard` ~L83-118)
- Modify: `dashboard/app/(dj)/setbuilder/setbuilder.module.css` (after `.toolRationale` ~L871)
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/ChatPanelBody.test.tsx`

**Interfaces:**
- Consumes: `AppliedToolCall.name` (already on the generated type).
- Produces: a `data-testid="agent-undo-hint"` element rendered only for `autobuild` / `fill_to_duration` tool cards.

- [ ] **Step 1: Write the failing tests**

Add to `ChatPanelBody.test.tsx` inside the `describe('ChatPanelBody', ...)` block:

```typescript
  function entryWithTool(name: string) {
    return {
      id: 3,
      role: 'assistant' as const,
      content: 'Rebuilt the set: 12 slots, 3 refinement passes.',
      display_summary: 'Rebuilt the set: 12 slots, 3 refinement passes.',
      tool_calls: [
        {
          id: `${name}-1`,
          name,
          args: { rationale: 'Rebuild' },
          result: { slot_count: 12, iterations: 3 },
          mutating: true,
          display_summary: 'Rebuilt the set: 12 slots, 3 refinement passes.',
        },
      ],
      affected_transition_scores: [],
    };
  }

  it('shows an undo hint on a destructive autobuild tool card', () => {
    render(<ChatPanelBody chat={makeController({ entries: [entryWithTool('autobuild')] })} />);
    expect(screen.getByTestId('agent-undo-hint')).toHaveTextContent(/undo/i);
  });

  it('does not show the undo hint on a non-destructive tool card', () => {
    render(<ChatPanelBody chat={makeController({ entries: [entryWithTool('swap_slots')] })} />);
    expect(screen.queryByTestId('agent-undo-hint')).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- --run ChatPanelBody`
Expected: FAIL — `Unable to find an element by: [data-testid="agent-undo-hint"]`.

- [ ] **Step 3: Implement the hint**

In `ChatPanelBody.tsx`, add this module-level constant near the top (after the imports):

```typescript
const DESTRUCTIVE_TOOL_NAMES = new Set(['autobuild', 'fill_to_duration']);
```

In the `ToolCard` component, add the hint inside `<div className={styles.toolBody}>`, right after the `{rationale && ...}` block:

```tsx
        {DESTRUCTIVE_TOOL_NAMES.has(tool.name) && (
          <div className={styles.toolUndoHint} data-testid="agent-undo-hint">
            Rebuilt your whole set — press ⌘Z (or Undo) to revert.
          </div>
        )}
```

- [ ] **Step 4: Add the CSS class**

In `setbuilder.module.css`, add after the `.toolRationale { ... }` block:

```css
.toolUndoHint {
  margin-top: 0.3rem;
  color: var(--text-secondary);
  font-size: 0.6875rem;
}
```

- [ ] **Step 5: Run tests + lint + types to verify they pass**

Run: `npm test -- --run ChatPanelBody && npm run lint && npx tsc --noEmit`
Expected: PASS; ESLint clean; no TS errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/\(dj\)/setbuilder/components/ChatPanelBody.tsx \
        dashboard/app/\(dj\)/setbuilder/setbuilder.module.css \
        dashboard/app/\(dj\)/setbuilder/components/__tests__/ChatPanelBody.test.tsx
git commit -m "feat(setbuilder): undo-discoverability hint on destructive agent tool cards (#491)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Final full CI sweep

**Files:** none (verification only).

- [ ] **Step 1: Backend**

From `server/`:
```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && \
.venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q
```
Expected: all green, coverage ≥ 85%.

- [ ] **Step 2: Migration drift (should be a no-op — no model changes)**

```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic check
```
Expected: "No new upgrade operations detected." (This PR adds no columns/models.)

- [ ] **Step 3: Frontend**

From `dashboard/`:
```bash
npm run lint && npx tsc --noEmit && npm test -- --run
```
Expected: all green. (If `next-env.d.ts` was auto-modified, `git checkout dashboard/next-env.d.ts` before any further commit.)

- [ ] **Step 4: Push + open PR**

```bash
git push -u origin feat/issue-491-autobuild-fill-duration
```
Then open a PR titled `feat(setbuilder): autobuild + fill_to_duration agent tools (#491)` with a Why/What/Testing body, `Closes #491`, and the agent credit. Move the issue to **In review** (`gh-project-move 491 "In review"`).

---

## Self-Review

**Spec coverage:**
- autobuild (wraps build_set, honors locked/pairings) → Task 2. ✅
- fill_to_duration (bounded, logged, never moves locked, errors without target) → Task 3. ✅
- `build_set` commit-flag for turn atomicity → Task 1. ✅
- Undo via global undo + discoverability hint → Task 5 (hint) + Task 2 (snapshot round-trip identity test proving restore fidelity). ✅
- Allowlist wiring (MUTATION_TOOLS, _agent_tools, handler, display) → Tasks 2 & 3. ✅
- `requests` untouched regression tests → Tasks 2 & 3. ✅
- Coverage gate / full CI → Tasks 4 & 6. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `_tool_autobuild` / `_tool_fill_to_duration` signatures `(db, set_obj, payload) -> tuple[dict, set[int]]` match the handler dict and the existing tool contract. `build_set(..., *, commit=...)` is consistent between Task 1 (definition) and Task 2 (caller). Result keys used in display summaries (`slot_count`, `iterations`, `inserted_count`, `estimated_total_sec`, `target_duration_sec`, `capped`) match those returned by the tools. ✅

# Connected-Service Import Agent Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three mutating WrzDJSet agent tools — `import_from_event`, `import_from_tidal`, `import_from_beatport` — that import a track pool from chat, resolving the source by name or id.

**Architecture:** New `agent_tools_imports.py` module wraps the existing `pool.candidates_from_*` + `get_or_create_source` + `import_candidates` service path, behind a shared `_resolve_one` name-or-id matcher. Tools join the closed allowlist (`MUTATION_TOOLS` + `_agent_tools()` + `apply_tool_call` + `_tool_display_summary`). Imports are additive (pool only, no timeline change) and ride the existing global undo — backend-only, no frontend.

**Tech Stack:** FastAPI + SQLAlchemy backend; pytest (SQLite in-memory test DB), monkeypatch for external service edges.

**Spec:** `docs/superpowers/specs/2026-06-22-setbuilder-import-tools-design.md`
**Issue:** #524 (epic #442, Family 4a). **Branch:** `feat/issue-524-import-agent-tools` (already created).

## Global Constraints

- Backend lint: ruff line-length 100, rules E, F, I, UP. `== None`/`== True` allowed. Run `.venv/bin/ruff format .` after edits.
- Backend coverage is an enforced hard gate at **85%** (`--cov-fail-under`). New code must be covered.
- Every mutating agent tool: signature `_tool_x(db, set_obj, payload) -> tuple[dict, set[int]]`; uses `db.flush()` not `db.commit()` (the turn owns commit/rollback); member of `MUTATION_TOOLS` (forces non-empty `rationale`); owner-scoped; **never writes the `requests` table** (pin with a regression test).
- Dispatched only through `apply_tool_call`'s closed allowlist; unknown name raises `AgentToolError`.
- Imports change the pool, not the timeline → affected positions are always `set()`.
- Backend-only: no frontend changes (additive imports need no destructive-undo hint).
- Commits: Conventional Commits ending with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- All commands run from `server/`.

---

## File Structure

**Create:**
- `server/app/services/setbuilder/agent_tools_imports.py` — `_resolve_one`, `_import_summary`, `_connected_playlist_import`, and the three `_tool_import_from_*` functions.
- `server/tests/test_setbuilder_imports.py` — all tests for this feature.

**Modify:**
- `server/app/services/setbuilder/pool.py` — `import_candidates` gains `commit: bool = True`.
- `server/app/services/setbuilder/agent_common.py` — 3 names into `MUTATION_TOOLS`.
- `server/app/services/setbuilder/agent_tool_specs.py` — 3 `ToolSpec`s.
- `server/app/services/setbuilder/pass2_agent.py` — import + 3 handler entries.
- `server/app/services/setbuilder/agent_display.py` — 1 combined display case for the 3 tools.

---

## Task 1: `import_candidates` gains a `commit` flag

The agent path must flush, not commit, so a multi-tool turn stays atomic. The three REST callers keep the default.

**Files:**
- Modify: `server/app/services/setbuilder/pool.py` (`import_candidates` ~L141-201)
- Test: `server/tests/test_setbuilder_imports.py` (new file)

**Interfaces:**
- Produces: `pool.import_candidates(db, set_obj, source, candidates, *, commit: bool = True) -> tuple[int, int]`. When `commit=False`, persists via `db.flush()` only.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_setbuilder_imports.py` with:

```python
"""Tests for the connected-service import agent tools (#524, #442 Family 4a)."""

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder import pool


def _mk_set(db: Session, user: User) -> Set:
    set_obj = Set(owner_id=user.id, name="Import Set")
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_import_candidates_commit_false_defers_persistence(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    source = set_obj.pool_sources[0]
    cands = [pool.PoolCandidate(title="A", artist="X"), pool.PoolCandidate(title="B", artist="Y")]

    added, deduped = pool.import_candidates(db, set_obj, source, cands, commit=False)
    assert (added, deduped) == (2, 0)
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 2
    db.rollback()
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 0

    # Default commit=True persists across a rollback.
    pool.import_candidates(db, set_obj, source, cands)
    db.rollback()
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_setbuilder_imports.py::test_import_candidates_commit_false_defers_persistence -v`
Expected: FAIL — `import_candidates() got an unexpected keyword argument 'commit'`.

- [ ] **Step 3: Implement the flag**

In `pool.py`, change the `import_candidates` signature:

```python
def import_candidates(
    db: Session,
    set_obj: Set,
    source: SetPoolSource,
    candidates: Iterable[PoolCandidate],
    *,
    commit: bool = True,
) -> tuple[int, int]:
```

and replace its trailing `db.commit()` (just before `return added, deduped`) with:

```python
    if commit:
        db.commit()
    else:
        db.flush()
    return added, deduped
```

- [ ] **Step 4: Run test + format to verify it passes**

Run: `.venv/bin/ruff format app/services/setbuilder/pool.py && .venv/bin/pytest tests/test_setbuilder_imports.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/setbuilder/pool.py server/tests/test_setbuilder_imports.py
git commit -m "feat(setbuilder): add commit flag to import_candidates for agent-turn atomicity (#524)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `agent_tools_imports.py` + `_resolve_one` + `import_from_event`

The module scaffold, the shared resolver, and the first tool, fully wired.

**Files:**
- Create: `server/app/services/setbuilder/agent_tools_imports.py`
- Modify: `agent_common.py` (`MUTATION_TOOLS`), `agent_tool_specs.py` (`_agent_tools()`), `pass2_agent.py` (import + handlers), `agent_display.py` (`_tool_display_summary`)
- Test: `server/tests/test_setbuilder_imports.py`

**Interfaces:**
- Consumes: `pool.candidates_from_event(db, user, event_id) -> tuple[Event, list[PoolCandidate]] | None`; `pool.get_or_create_source(...)`; `pool.import_candidates(..., commit=False)` (Task 1); `apply_tool_call`'s rationale gate.
- Produces:
  - `_resolve_one(query: str, items: list, *, id_of, name_of, what: str)` — returns the single match; raises `AgentToolError` on empty query / 0 / >1.
  - `_import_summary(source, added, deduped) -> dict` — `{"added","deduped","source_label","source_kind"}`.
  - `_tool_import_from_event(db, set_obj, payload) -> tuple[dict, set[int]]`. Tool name `"import_from_event"`, in `MUTATION_TOOLS`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_setbuilder_imports.py`:

```python
from app.services.setbuilder.agent_display import _tool_display_summary
from app.services.setbuilder.agent_tools_imports import _resolve_one
from app.services.setbuilder.pass2_agent import (
    MUTATION_TOOLS,
    AgentToolError,
    apply_tool_call,
)


def _mk_event(db: Session, user: User, name: str, code: str) -> Event:
    from datetime import timedelta

    from app.utils.time import utcnow  # project's tz-aware now helper

    event = Event(
        code=code,
        join_code=code[::-1].ljust(6, "X")[:6],
        name=name,
        created_by_user_id=user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# --- _resolve_one unit tests -------------------------------------------------

class _Item:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def _items():
    return [_Item(1, "Friday Wedding"), _Item(2, "Saturday Club"), _Item(3, "Sunday Brunch")]


def test_resolve_one_by_id():
    got = _resolve_one("2", _items(), id_of=lambda i: i.id, name_of=lambda i: i.name, what="event")
    assert got.id == 2


def test_resolve_one_by_name_substring_case_insensitive():
    got = _resolve_one("club", _items(), id_of=lambda i: i.id, name_of=lambda i: i.name, what="event")
    assert got.id == 2


def test_resolve_one_no_match_lists_options():
    with pytest.raises(AgentToolError, match="No event matched 'rave'.*Friday Wedding"):
        _resolve_one("rave", _items(), id_of=lambda i: i.id, name_of=lambda i: i.name, what="event")


def test_resolve_one_ambiguous_asks_to_disambiguate():
    items = [_Item(1, "Friday Night"), _Item(2, "Friday Wedding")]
    with pytest.raises(AgentToolError, match="matched several"):
        _resolve_one("friday", items, id_of=lambda i: i.id, name_of=lambda i: i.name, what="event")


def test_resolve_one_empty_query():
    with pytest.raises(AgentToolError, match="name or id"):
        _resolve_one("  ", _items(), id_of=lambda i: i.id, name_of=lambda i: i.name, what="event")


# --- import_from_event -------------------------------------------------------

def test_import_from_event_resolves_by_name_and_imports(db: Session, test_user: User, monkeypatch):
    set_obj = _mk_set(db, test_user)
    event = _mk_event(db, test_user, "Friday Wedding", "EVT001")

    def fake_candidates(db_, user_, event_id):
        assert event_id == event.id
        return event, [pool.PoolCandidate(title="A", artist="X"), pool.PoolCandidate(title="B", artist="Y")]

    monkeypatch.setattr("app.services.setbuilder.pool.candidates_from_event", fake_candidates)

    result, positions = apply_tool_call(
        db, set_obj, "import_from_event", {"event": "wedding", "rationale": "Pull tonight's requests."}
    )

    assert positions == set()
    assert result == {"added": 2, "deduped": 0, "source_label": "Friday Wedding", "source_kind": "event"}
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 2


def test_import_from_event_no_events_errors(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    with pytest.raises(AgentToolError, match="no events"):
        apply_tool_call(db, set_obj, "import_from_event", {"event": "x", "rationale": "r"})


def test_import_from_event_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    _mk_event(db, test_user, "Friday Wedding", "EVT002")
    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "import_from_event", {"event": "wedding"})


def test_import_from_event_in_mutation_tools():
    assert "import_from_event" in MUTATION_TOOLS


def test_import_from_event_leaves_requests_untouched(db: Session, test_user: User):
    from app.models.request import Request

    set_obj = _mk_set(db, test_user)
    event = _mk_event(db, test_user, "Friday Wedding", "EVT003")
    req = Request(
        event_id=event.id,
        guest_id="g1",
        song_title="Real Song",
        artist="Real Artist",
        status="pending",
    )
    db.add(req)
    db.commit()
    before_count = db.query(Request).count()

    apply_tool_call(
        db, set_obj, "import_from_event", {"event": str(event.id), "rationale": "Import by id."}
    )

    db.refresh(req)
    assert db.query(Request).count() == before_count
    assert req.song_title == "Real Song"


def test_import_from_event_display_summary():
    s = _tool_display_summary(
        "import_from_event",
        {"rationale": "x"},
        {"added": 18, "deduped": 3, "source_label": "Friday Wedding", "source_kind": "event"},
        {},
        {},
    )
    assert s == "Imported 18 tracks from event 'Friday Wedding' into the pool (3 duplicates skipped)."
```

(If `app.utils.time.utcnow` is not the correct import for the project's tz-aware now, use the same import the `test_event` fixture in `tests/conftest.py` uses — check there first; the fixture builds an `Event` the same way.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_setbuilder_imports.py -v`
Expected: FAIL — `cannot import name '_resolve_one'` / `AgentToolError: Unknown tool: import_from_event`.

- [ ] **Step 3: Create the module with `_resolve_one`, `_import_summary`, and `import_from_event`**

Create `server/app/services/setbuilder/agent_tools_imports.py`:

```python
"""Cross-surface import agent tools (#524, #442 Family 4a).

import_from_event / import_from_tidal / import_from_beatport pull a track pool
from a DJ-owned event or a connected-account playlist, resolving the source by
name or id. All three are in MUTATION_TOOLS and dispatched only through
apply_tool_call. Imports are additive (pool only) and undoable via the global
undo stack (#493/#494), which snapshots pool sources + tracks.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.set import Set
from app.models.set_pool import SetPoolSource
from app.models.user import User
from app.services.setbuilder import pool
from app.services.setbuilder.agent_common import AgentToolError


def _resolve_one(
    query: str,
    items: list,
    *,
    id_of: Callable[[Any], Any],
    name_of: Callable[[Any], str],
    what: str,
) -> Any:
    """Resolve a name-or-id query to exactly one item, or raise AgentToolError.

    Digits match by id; otherwise a case-insensitive substring on the name.
    0 matches -> error listing options; >1 -> error asking to disambiguate.
    """
    q = query.strip()
    if not q:
        raise AgentToolError(f"Provide a {what} name or id.")
    if q.isdigit():
        matches = [it for it in items if str(id_of(it)) == q]
    else:
        ql = q.lower()
        matches = [it for it in items if ql in (name_of(it) or "").lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        available = ", ".join(name_of(it) for it in items[:10]) or "none"
        raise AgentToolError(f"No {what} matched '{query}'. Available: {available}.")
    names = ", ".join(name_of(it) for it in matches[:10])
    raise AgentToolError(f"'{query}' matched several {what}s: {names}. Be more specific.")


def _import_summary(source: SetPoolSource, added: int, deduped: int) -> dict[str, Any]:
    return {
        "added": added,
        "deduped": deduped,
        "source_label": source.label,
        "source_kind": source.kind,
    }


def _owner(db: Session, set_obj: Set) -> User:
    return db.get(User, set_obj.owner_id)


def _tool_import_from_event(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    owner = _owner(db, set_obj)
    events = (
        db.query(Event)
        .filter(Event.created_by_user_id == owner.id)
        .order_by(Event.id.desc())
        .all()
    )
    if not events:
        raise AgentToolError("You have no events to import from.")
    event = _resolve_one(
        str(payload["event"]), events, id_of=lambda e: e.id, name_of=lambda e: e.name, what="event"
    )
    resolved = pool.candidates_from_event(db, owner, event.id)
    if resolved is None:
        raise AgentToolError("Event not found")
    _, candidates = resolved
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="event",
        external_ref=str(event.id),
        label=event.name,
        meta="WrzDJ event requests",
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates, commit=False)
    return _import_summary(source, added, deduped), set()
```

- [ ] **Step 4: Wire `import_from_event` into the allowlist + display**

In `agent_common.py`, add to `MUTATION_TOOLS` (e.g. after `"remove_pairing",`):

```python
    "import_from_event",
```

In `agent_tool_specs.py`, add to the `_agent_tools()` list (after the `suggest_pairings` block, before `_critique_tool()`):

```python
        ToolSpec(
            name="import_from_event",
            description=(
                "Import a DJ-owned event's song requests into the set's track pool. "
                "The 'event' argument is an event name (case-insensitive substring) or its "
                "numeric id; if it matches zero or several events the tool returns the options."
            ),
            input_schema={
                "type": "object",
                "properties": {"event": {"type": "string"}, "rationale": {"type": "string"}},
                "required": ["event", "rationale"],
            },
        ),
```

In `pass2_agent.py`, add the import (after the `agent_tools_structural` import):

```python
from app.services.setbuilder.agent_tools_imports import _tool_import_from_event
```

and add to the `handlers` dict in `apply_tool_call` (after the structural entries):

```python
        "import_from_event": _tool_import_from_event,
```

In `agent_display.py`, add this case just before the final fallback `return`:

```python
    if name in {"import_from_event", "import_from_tidal", "import_from_beatport"}:
        added = int(result.get("added") or 0)
        deduped = int(result.get("deduped") or 0)
        label = result.get("source_label") or "source"
        where = {
            "event": f"event '{label}'",
            "tidal": f"Tidal playlist '{label}'",
            "beatport": f"Beatport playlist '{label}'",
        }.get(result.get("source_kind"), label)
        dup = f" ({deduped} duplicate{'s' if deduped != 1 else ''} skipped)" if deduped else ""
        return f"Imported {added} track{'s' if added != 1 else ''} from {where} into the pool{dup}."
```

- [ ] **Step 5: Run tests + format to verify they pass**

Run: `.venv/bin/ruff format app/services/setbuilder/ && .venv/bin/ruff check app/services/setbuilder/ tests/test_setbuilder_imports.py && .venv/bin/pytest tests/test_setbuilder_imports.py tests/test_setbuilder_pass2.py -v`
Expected: PASS (import_from_event + resolver tests; no pass2 regression).

- [ ] **Step 6: Commit**

```bash
git add server/app/services/setbuilder/agent_tools_imports.py \
        server/app/services/setbuilder/agent_common.py \
        server/app/services/setbuilder/agent_tool_specs.py \
        server/app/services/setbuilder/pass2_agent.py \
        server/app/services/setbuilder/agent_display.py \
        server/tests/test_setbuilder_imports.py
git commit -m "feat(setbuilder): import_from_event agent tool + name-or-id resolver (#524)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `import_from_tidal` + `import_from_beatport`

The two connected-playlist tools, sharing one helper (connection check → list → resolve → fetch → import).

**Files:**
- Modify: `server/app/services/setbuilder/agent_tools_imports.py`
- Modify: `agent_common.py`, `agent_tool_specs.py`, `pass2_agent.py`
- Test: `server/tests/test_setbuilder_imports.py`

**Interfaces:**
- Consumes: `tidal.list_user_playlists(db, user)` / `beatport.list_user_playlists(db, user)` (return objects with `.id: str`, `.name: str`); `pool.candidates_from_tidal/beatport(db, user, playlist_id)`; `tidal.TidalFetchError`; `User.tidal_access_token` / `.beatport_access_token`.
- Produces: `_tool_import_from_tidal` / `_tool_import_from_beatport`, both `(db, set_obj, payload) -> tuple[dict, set[int]]`, in `MUTATION_TOOLS`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_setbuilder_imports.py`:

```python
from types import SimpleNamespace


def _connect(db, user, *, tidal=False, beatport=False):
    if tidal:
        user.tidal_access_token = "tok"
    if beatport:
        user.beatport_access_token = "tok"
    db.commit()


def test_import_from_tidal_resolves_and_imports(db: Session, test_user: User, monkeypatch):
    set_obj = _mk_set(db, test_user)
    _connect(db, test_user, tidal=True)
    monkeypatch.setattr(
        "app.services.tidal.list_user_playlists",
        lambda d, u: [SimpleNamespace(id="pl-1", name="Peak Hours"), SimpleNamespace(id="pl-2", name="Warmup")],
    )
    monkeypatch.setattr(
        "app.services.setbuilder.pool.candidates_from_tidal",
        lambda d, u, pid: [pool.PoolCandidate(title="T1", artist="A1"), pool.PoolCandidate(title="T2", artist="A2")],
    )

    result, positions = apply_tool_call(
        db, set_obj, "import_from_tidal", {"playlist": "peak", "rationale": "Bring the peak set."}
    )

    assert positions == set()
    assert result["added"] == 2
    assert result["source_kind"] == "tidal"
    assert result["source_label"] == "Peak Hours"


def test_import_from_tidal_not_connected_errors(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    with pytest.raises(AgentToolError, match="Connect your Tidal"):
        apply_tool_call(db, set_obj, "import_from_tidal", {"playlist": "x", "rationale": "r"})


def test_import_from_tidal_fetch_error_maps_to_tool_error(db: Session, test_user: User, monkeypatch):
    from app.services.tidal import TidalFetchError

    set_obj = _mk_set(db, test_user)
    _connect(db, test_user, tidal=True)
    monkeypatch.setattr(
        "app.services.tidal.list_user_playlists",
        lambda d, u: [SimpleNamespace(id="pl-1", name="Peak Hours")],
    )

    def boom(d, u, pid):
        raise TidalFetchError("nope")

    monkeypatch.setattr("app.services.setbuilder.pool.candidates_from_tidal", boom)
    with pytest.raises(AgentToolError, match="Couldn't fetch that Tidal"):
        apply_tool_call(db, set_obj, "import_from_tidal", {"playlist": "peak", "rationale": "r"})


def test_import_from_beatport_resolves_and_imports(db: Session, test_user: User, monkeypatch):
    set_obj = _mk_set(db, test_user)
    _connect(db, test_user, beatport=True)
    monkeypatch.setattr(
        "app.services.beatport.list_user_playlists",
        lambda d, u: [SimpleNamespace(id="bp-9", name="Tech House")],
    )
    monkeypatch.setattr(
        "app.services.setbuilder.pool.candidates_from_beatport",
        lambda d, u, pid: [pool.PoolCandidate(title="B1", artist="A1")],
    )

    result, _ = apply_tool_call(
        db, set_obj, "import_from_beatport", {"playlist": "tech", "rationale": "Tech house pool."}
    )
    assert result["added"] == 1
    assert result["source_kind"] == "beatport"


def test_import_from_beatport_empty_fetch_errors(db: Session, test_user: User, monkeypatch):
    set_obj = _mk_set(db, test_user)
    _connect(db, test_user, beatport=True)
    monkeypatch.setattr(
        "app.services.beatport.list_user_playlists",
        lambda d, u: [SimpleNamespace(id="bp-9", name="Tech House")],
    )
    monkeypatch.setattr("app.services.setbuilder.pool.candidates_from_beatport", lambda d, u, pid: [])
    with pytest.raises(AgentToolError, match="no importable tracks"):
        apply_tool_call(db, set_obj, "import_from_beatport", {"playlist": "tech", "rationale": "r"})


def test_import_playlist_tools_in_mutation_tools():
    assert {"import_from_tidal", "import_from_beatport"} <= MUTATION_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_setbuilder_imports.py -k "tidal or beatport" -v`
Expected: FAIL — `AgentToolError: Unknown tool: import_from_tidal`.

- [ ] **Step 3: Implement the shared helper + both tools**

In `agent_tools_imports.py`, extend the imports at the top:

```python
from app.services import beatport, tidal
```

and add below `_tool_import_from_event`:

```python
def _connected_playlist_import(
    db: Session,
    set_obj: Set,
    payload: dict[str, Any],
    *,
    kind: str,
    connected_attr: str,
    list_playlists: Callable[[Session, User], list],
    fetch_candidates: Callable[[Session, User, str], list],
    fetch_error_types: tuple[type[Exception], ...],
) -> tuple[dict[str, Any], set[int]]:
    """Resolve a connected-account playlist by name/id and import it.

    Shared by import_from_tidal/beatport. ``fetch_error_types`` is the tuple of
    exceptions the fetch may raise (empty for beatport, which returns []).
    """
    owner = _owner(db, set_obj)
    if not getattr(owner, connected_attr):
        raise AgentToolError(f"Connect your {kind.capitalize()} account first.")
    playlists = list_playlists(db, owner)
    if not playlists:
        raise AgentToolError(f"No {kind.capitalize()} playlists found on your account.")
    playlist = _resolve_one(
        str(payload["playlist"]),
        playlists,
        id_of=lambda p: p.id,
        name_of=lambda p: p.name,
        what=f"{kind} playlist",
    )
    try:
        candidates = fetch_candidates(db, owner, playlist.id)
    except fetch_error_types as exc:
        raise AgentToolError(f"Couldn't fetch that {kind.capitalize()} playlist.") from exc
    if not candidates:
        raise AgentToolError(f"That {kind.capitalize()} playlist has no importable tracks.")
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind=kind,
        external_ref=str(playlist.id),
        label=playlist.name,
        meta=f"{kind.capitalize()} playlist",
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates, commit=False)
    return _import_summary(source, added, deduped), set()


def _tool_import_from_tidal(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    return _connected_playlist_import(
        db,
        set_obj,
        payload,
        kind="tidal",
        connected_attr="tidal_access_token",
        list_playlists=tidal.list_user_playlists,
        fetch_candidates=pool.candidates_from_tidal,
        fetch_error_types=(tidal.TidalFetchError,),
    )


def _tool_import_from_beatport(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    return _connected_playlist_import(
        db,
        set_obj,
        payload,
        kind="beatport",
        connected_attr="beatport_access_token",
        list_playlists=beatport.list_user_playlists,
        fetch_candidates=pool.candidates_from_beatport,
        fetch_error_types=(),
    )
```

- [ ] **Step 4: Wire both tools**

In `agent_common.py`, add to `MUTATION_TOOLS` (after `"import_from_event",`):

```python
    "import_from_tidal",
    "import_from_beatport",
```

In `agent_tool_specs.py`, add after the `import_from_event` `ToolSpec`:

```python
        ToolSpec(
            name="import_from_tidal",
            description=(
                "Import a connected-account Tidal playlist into the set's track pool. "
                "'playlist' is a playlist name (substring) or id; zero/several matches "
                "return the options."
            ),
            input_schema={
                "type": "object",
                "properties": {"playlist": {"type": "string"}, "rationale": {"type": "string"}},
                "required": ["playlist", "rationale"],
            },
        ),
        ToolSpec(
            name="import_from_beatport",
            description=(
                "Import a connected-account Beatport playlist into the set's track pool. "
                "'playlist' is a playlist name (substring) or id; zero/several matches "
                "return the options."
            ),
            input_schema={
                "type": "object",
                "properties": {"playlist": {"type": "string"}, "rationale": {"type": "string"}},
                "required": ["playlist", "rationale"],
            },
        ),
```

In `pass2_agent.py`, extend the imports import line:

```python
from app.services.setbuilder.agent_tools_imports import (
    _tool_import_from_beatport,
    _tool_import_from_event,
    _tool_import_from_tidal,
)
```

and add to the `handlers` dict:

```python
        "import_from_tidal": _tool_import_from_tidal,
        "import_from_beatport": _tool_import_from_beatport,
```

- [ ] **Step 5: Run tests + format to verify they pass**

Run: `.venv/bin/ruff format app/services/setbuilder/ && .venv/bin/ruff check app/services/setbuilder/ tests/test_setbuilder_imports.py && .venv/bin/pytest tests/test_setbuilder_imports.py tests/test_setbuilder_pass2.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/app/services/setbuilder/agent_tools_imports.py \
        server/app/services/setbuilder/agent_common.py \
        server/app/services/setbuilder/agent_tool_specs.py \
        server/app/services/setbuilder/pass2_agent.py \
        server/tests/test_setbuilder_imports.py
git commit -m "feat(setbuilder): import_from_tidal + import_from_beatport agent tools (#524)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Backend full-suite + lint gate

**Files:** none (verification only).

- [ ] **Step 1: Lint, format check, full suite**

Run:
```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest --tb=short -q
```
Expected: ruff clean; all tests pass; coverage ≥ 85%.

- [ ] **Step 2: If coverage dipped, add the missing-branch test**

If the gate reports an uncovered line in `agent_tools_imports.py` (e.g. the empty-query `_resolve_one` branch, or the `resolved is None` guard), add a focused test to `test_setbuilder_imports.py`, then re-run Step 1 and commit:

```bash
git add server/tests/test_setbuilder_imports.py
git commit -m "test(setbuilder): cover import-tool edge branch (#524)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Final CI sweep + PR

**Files:** none.

- [ ] **Step 1: Backend**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && \
.venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q
```
Expected: all green, coverage ≥ 85%.

- [ ] **Step 2: Migration drift (no schema change → no-op)**

```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic check
```
Expected: "No new upgrade operations detected." (This PR adds no models/migrations.) If the local DB is unreachable, confirm instead that `git diff --name-only origin/main..HEAD` lists no `models/` or `migrations/` files.

- [ ] **Step 3: Push + open PR**

```bash
git push -u origin feat/issue-524-import-agent-tools
```
Open a PR titled `feat(setbuilder): connected-service import agent tools (#524)` with a Why/What/Testing body, `Closes #524`, and the agent credit. Move the issue to **In review** (`gh-project-move 524 "In review"`).

---

## Self-Review

**Spec coverage:**
- `import_from_event` (resolve by name/id, owner-scoped, requests untouched) → Task 2. ✅
- `import_from_tidal` / `import_from_beatport` (connection check, fetch-error mapping, resolve) → Task 3. ✅
- Name-or-id resolution with 0/ambiguous → `AgentToolError` listing options → Task 2 (`_resolve_one` unit tests). ✅
- `import_candidates(commit=False)` for turn atomicity → Task 1. ✅
- Allowlist wiring (MUTATION_TOOLS, _agent_tools, handler, display) → Tasks 2 & 3. ✅
- `requests` untouched regression → Task 2. ✅
- Affected positions always `set()` → asserted in import tests. ✅
- Backend-only (no frontend) → no frontend file in the structure. ✅
- Coverage gate / full CI → Tasks 4 & 5. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The one conditional note (`utcnow` import) tells the engineer exactly where to verify (the `test_event` fixture in conftest). ✅

**Type consistency:** `_tool_import_from_*(db, set_obj, payload) -> tuple[dict, set[int]]` matches the handler dict and the contract. `_resolve_one(query, items, *, id_of, name_of, what)` signature matches all call sites (event, tidal, beatport). Result keys (`added`, `deduped`, `source_label`, `source_kind`) match `_import_summary` and the display case. `import_candidates(..., *, commit=...)` consistent between Task 1 (def) and Tasks 2/3 (callers). ✅

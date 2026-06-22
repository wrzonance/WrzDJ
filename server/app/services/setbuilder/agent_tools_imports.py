"""Cross-surface import agent tools (#524, #442 Family 4a).

import_from_event / import_from_tidal / import_from_beatport pull a track pool
from a DJ-owned event or a connected-account playlist, resolving the source by
name or id. All three are in MUTATION_TOOLS and dispatched only through
apply_tool_call. Imports are additive (pool only) and undoable via the global
undo stack (#493/#494), which snapshots pool sources + tracks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
        db.query(Event).filter(Event.created_by_user_id == owner.id).order_by(Event.id.desc()).all()
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

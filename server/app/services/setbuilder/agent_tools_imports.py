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
from app.services import beatport, tidal
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
    owner = db.get(User, set_obj.owner_id)
    if owner is None:
        raise AgentToolError("Set owner not found.")
    return owner


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
        str(payload.get("event") or ""),
        events,
        id_of=lambda e: e.id,
        name_of=lambda e: e.name,
        what="event",
    )
    resolved = pool.candidates_from_event(db, owner, event.id)
    # Defensive: candidates_from_event re-validates owner scope; unreachable once
    # _resolve_one matched an owned event, but keeps the guard if that contract changes.
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
        str(payload.get("playlist") or ""),
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

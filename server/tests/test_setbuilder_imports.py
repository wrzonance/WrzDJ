"""Tests for the connected-service import agent tools (#524, #442 Family 4a)."""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder import pool
from app.services.setbuilder.agent_display import _tool_display_summary
from app.services.setbuilder.agent_tools_imports import _resolve_one
from app.services.setbuilder.pass2_agent import (
    MUTATION_TOOLS,
    AgentToolError,
    apply_tool_call,
)


def _mk_set(db: Session, user: User) -> Set:
    set_obj = Set(owner_id=user.id, name="Import Set")
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _mk_event(db: Session, user: User, name: str, code: str) -> Event:
    from datetime import timedelta

    from app.core.time import utcnow  # project's tz-aware now helper

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
    got = _resolve_one(
        "club", _items(), id_of=lambda i: i.id, name_of=lambda i: i.name, what="event"
    )
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
        return event, [
            pool.PoolCandidate(title="A", artist="X"),
            pool.PoolCandidate(title="B", artist="Y"),
        ]

    # Patch on the pool module object — agent_tools_imports calls
    # pool.candidates_from_event (attribute lookup), so this intercepts it.
    monkeypatch.setattr("app.services.setbuilder.pool.candidates_from_event", fake_candidates)

    result, positions = apply_tool_call(
        db,
        set_obj,
        "import_from_event",
        {"event": "wedding", "rationale": "Pull tonight's requests."},
    )

    assert positions == set()
    assert result == {
        "added": 2,
        "deduped": 0,
        "source_label": "Friday Wedding",
        "source_kind": "event",
    }
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
        dedupe_key="test_req_leaves_untouched",
    )
    db.add(req)
    db.commit()
    before_count = db.query(Request).count()

    result, _ = apply_tool_call(
        db, set_obj, "import_from_event", {"event": str(event.id), "rationale": "Import by id."}
    )

    # Two-sided pin: the pool actually grew (the import did real work) AND the
    # source requests table is untouched.
    assert result["added"] >= 1
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() >= 1
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
    assert (
        s == "Imported 18 tracks from event 'Friday Wedding' into the pool (3 duplicates skipped)."
    )


def test_import_from_event_missing_arg_errors(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    _mk_event(db, test_user, "Friday Wedding", "EVT900")
    with pytest.raises(AgentToolError, match="name or id"):
        apply_tool_call(db, set_obj, "import_from_event", {"rationale": "no event arg"})


# --- import_from_tidal -------------------------------------------------------


def _connect(db: Session, user: User, *, tidal: bool = False, beatport: bool = False) -> None:
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
        lambda d, u: [
            SimpleNamespace(id="pl-1", name="Peak Hours"),
            SimpleNamespace(id="pl-2", name="Warmup"),
        ],
    )
    monkeypatch.setattr(
        "app.services.setbuilder.pool.candidates_from_tidal",
        lambda d, u, pid: [
            pool.PoolCandidate(title="T1", artist="A1"),
            pool.PoolCandidate(title="T2", artist="A2"),
        ],
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


def test_import_from_tidal_fetch_error_maps_to_tool_error(
    db: Session, test_user: User, monkeypatch
):
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


# --- import_from_beatport ----------------------------------------------------


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
    monkeypatch.setattr(
        "app.services.setbuilder.pool.candidates_from_beatport", lambda d, u, pid: []
    )
    with pytest.raises(AgentToolError, match="no importable tracks"):
        apply_tool_call(db, set_obj, "import_from_beatport", {"playlist": "tech", "rationale": "r"})


def test_import_playlist_tools_in_mutation_tools():
    assert {"import_from_tidal", "import_from_beatport"} <= MUTATION_TOOLS


def test_import_from_tidal_no_playlists_errors(db: Session, test_user: User, monkeypatch):
    set_obj = _mk_set(db, test_user)
    _connect(db, test_user, tidal=True)
    monkeypatch.setattr("app.services.tidal.list_user_playlists", lambda d, u: [])
    with pytest.raises(AgentToolError, match="No Tidal playlists found"):
        apply_tool_call(db, set_obj, "import_from_tidal", {"playlist": "x", "rationale": "r"})

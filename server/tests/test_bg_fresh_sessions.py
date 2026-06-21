"""Regression tests for issue #505 — background tasks must not pin the
request-scoped DB connection.

FastAPI tears down the ``yield``-based ``get_db`` dependency only *after* all
background tasks finish, so passing the request ``db`` (or a live ORM row) to
``background_tasks.add_task`` keeps that pooled connection alive for the whole
duration of slow external API calls. Every call site is normalized to pass
**IDs only** and open a fresh ``SessionLocal()`` inside the task. These tests
prove (a) the fresh-session helpers close their session on success *and* on
exception, and (b) endpoints schedule IDs / lists-of-IDs, never ORM objects or
the request session.
"""

import pytest

import app.api.collect as collect_module
import app.api.events as events_module
import app.api.requests as requests_module
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus


class _SpySession:
    """Stand-in for a SessionLocal() instance that records close()."""

    def __init__(self) -> None:
        self.closed = False

    def query(self, *args, **kwargs):  # pragma: no cover - overridden per test
        raise AssertionError("query not stubbed")

    def get(self, *args, **kwargs):  # pragma: no cover - overridden per test
        raise AssertionError("get not stubbed")

    def close(self) -> None:
        self.closed = True


def _patch_session_local(monkeypatch, module, spy: _SpySession) -> None:
    """Make ``SessionLocal()`` inside *module*'s helpers return our spy.

    The helpers import ``SessionLocal`` lazily from ``app.db.session`` so we
    patch it at the source module.
    """
    import app.db.session as session_module

    monkeypatch.setattr(session_module, "SessionLocal", lambda: spy)


# --------------------------------------------------------------------------- #
# events.py helpers
# --------------------------------------------------------------------------- #


def test_enrich_helper_closes_session_on_success(monkeypatch):
    spy = _SpySession()
    _patch_session_local(monkeypatch, events_module, spy)
    monkeypatch.setattr(events_module, "enrich_request_metadata", lambda db, rid: None)

    events_module._enrich_with_fresh_session(123)

    assert spy.closed is True


def test_enrich_helper_closes_session_on_exception(monkeypatch):
    spy = _SpySession()
    _patch_session_local(monkeypatch, events_module, spy)

    def boom(db, rid):
        raise RuntimeError("enrich failed")

    monkeypatch.setattr(events_module, "enrich_request_metadata", boom)

    # Assert the error actually propagates — the helper must NOT swallow it — so
    # the regression also guards against a future try/except hiding failures.
    with pytest.raises(RuntimeError):
        events_module._enrich_with_fresh_session(123)

    assert spy.closed is True


def test_sync_collection_helper_passes_ids_and_closes(monkeypatch):
    """_sync_collection_requests_with_fresh_session re-queries by ID and closes."""
    spy = _SpySession()
    captured = {}

    rows = [object(), object()]
    user = object()
    event_with_user = type("E", (), {"created_by": user})()

    spy.get = lambda model, _id: event_with_user

    def fake_query(model):
        class _Q:
            def filter(self, *a, **k):
                return self

            def all(self):
                return rows

        return _Q()

    spy.query = fake_query
    _patch_session_local(monkeypatch, events_module, spy)

    def fake_sync(db, u, e, reqs):
        captured["args"] = (db, u, e, reqs)

    monkeypatch.setattr(events_module, "sync_collection_requests_batch", fake_sync)

    events_module._sync_collection_requests_with_fresh_session(7, [1, 2])

    assert spy.closed is True
    db_arg, user_arg, event_arg, reqs_arg = captured["args"]
    assert db_arg is spy
    assert user_arg is user
    assert event_arg is event_with_user
    assert reqs_arg == rows


def test_sync_collection_helper_noop_when_event_missing(monkeypatch):
    """A deleted event must short-circuit before any sync call."""
    spy = _SpySession()
    called = {"sync": False}
    spy.get = lambda model, _id: None
    _patch_session_local(monkeypatch, events_module, spy)
    monkeypatch.setattr(
        events_module,
        "sync_collection_requests_batch",
        lambda *a, **k: called.__setitem__("sync", True),
    )

    events_module._sync_collection_requests_with_fresh_session(404, [1])

    assert spy.closed is True
    assert called["sync"] is False


def test_remove_collection_tracks_helper_passes_ids_and_closes(monkeypatch):
    spy = _SpySession()
    captured = {}
    user = object()
    event_with_user = type("E", (), {"created_by": user})()

    spy.get = lambda model, _id: event_with_user
    _patch_session_local(monkeypatch, events_module, spy)

    def fake_remove(db, u, e, track_ids):
        captured["args"] = (db, u, e, track_ids)

    monkeypatch.setattr(events_module, "remove_collection_tracks_batch", fake_remove)

    events_module._remove_collection_tracks_with_fresh_session(7, ["t1", "t2"])

    assert spy.closed is True
    db_arg, user_arg, event_arg, track_ids = captured["args"]
    assert db_arg is spy
    assert user_arg is user
    assert event_arg is event_with_user
    assert track_ids == ["t1", "t2"]


# --------------------------------------------------------------------------- #
# requests.py helpers
# --------------------------------------------------------------------------- #


def test_requests_enrich_helper_closes_session(monkeypatch):
    spy = _SpySession()
    _patch_session_local(monkeypatch, requests_module, spy)
    monkeypatch.setattr(requests_module, "enrich_request_metadata", lambda db, rid: None)

    requests_module._enrich_with_fresh_session(5)

    assert spy.closed is True


def test_sync_request_helper_requeries_and_closes(monkeypatch):
    spy = _SpySession()
    captured = {}
    row = object()
    spy.get = lambda model, _id: row
    _patch_session_local(monkeypatch, requests_module, spy)

    def fake_sync(db, request):
        captured["args"] = (db, request)

    monkeypatch.setattr(requests_module, "sync_request_to_services", fake_sync)

    requests_module._sync_request_to_services_with_fresh_session(5)

    assert spy.closed is True
    db_arg, req_arg = captured["args"]
    assert db_arg is spy
    assert req_arg is row


def test_sync_request_helper_noop_when_missing(monkeypatch):
    """A deleted request must not blow up the background task."""
    spy = _SpySession()
    called = {"sync": False}
    spy.get = lambda model, _id: None
    _patch_session_local(monkeypatch, requests_module, spy)

    def fake_sync(db, request):
        called["sync"] = True

    monkeypatch.setattr(requests_module, "sync_request_to_services", fake_sync)

    requests_module._sync_request_to_services_with_fresh_session(5)

    assert spy.closed is True
    assert called["sync"] is False


def test_remove_collection_track_helper_requeries_and_closes(monkeypatch):
    spy = _SpySession()
    captured = {}
    user = object()
    event_obj = type("E", (), {"created_by": user})()
    row = type("R", (), {})()
    row.event = event_obj
    spy.get = lambda model, _id: row
    _patch_session_local(monkeypatch, requests_module, spy)

    def fake_remove(db, u, e, track_id):
        captured["args"] = (db, u, e, track_id)

    monkeypatch.setattr(requests_module, "remove_track_from_collection_playlist", fake_remove)

    requests_module._remove_collection_track_with_fresh_session(5, "trk-1")

    assert spy.closed is True
    db_arg, user_arg, event_arg, track_id = captured["args"]
    assert db_arg is spy
    assert user_arg is user
    assert event_arg is event_obj
    assert track_id == "trk-1"


# --------------------------------------------------------------------------- #
# collect.py helpers
# --------------------------------------------------------------------------- #


def test_collect_enrich_helper_closes_session(monkeypatch):
    spy = _SpySession()
    _patch_session_local(monkeypatch, collect_module, spy)
    monkeypatch.setattr(collect_module, "enrich_request_metadata", lambda db, rid: None)

    collect_module._enrich_with_fresh_session(9)

    assert spy.closed is True


def test_collect_sync_collection_helper_requeries_and_closes(monkeypatch):
    spy = _SpySession()
    captured = {}
    user = object()
    event_with_user = type("E", (), {"created_by": user})()
    rows = [object()]

    spy.get = lambda model, _id: event_with_user

    def fake_query(model):
        class _Q:
            def filter(self, *a, **k):
                return self

            def all(self):
                return rows

        return _Q()

    spy.query = fake_query
    _patch_session_local(monkeypatch, collect_module, spy)

    def fake_sync(db, u, e, reqs):
        captured["args"] = (db, u, e, reqs)

    monkeypatch.setattr(collect_module, "sync_collection_requests_batch", fake_sync)

    collect_module._sync_collection_requests_with_fresh_session(7, [1])

    assert spy.closed is True
    db_arg, user_arg, event_arg, reqs_arg = captured["args"]
    assert db_arg is spy
    assert user_arg is user
    assert event_arg is event_with_user
    assert reqs_arg == rows


# --------------------------------------------------------------------------- #
# Endpoint-level regressions: scheduled tasks receive IDs, not ORM objects, and
# bulk-review does not pin one task session per accepted row (issue #505).
# --------------------------------------------------------------------------- #


def _record_scheduled_tasks(monkeypatch):
    """Patch BackgroundTasks.add_task to capture (func, args) without running it."""
    from fastapi import BackgroundTasks

    scheduled: list[tuple] = []

    def fake_add_task(self, func, *args, **kwargs):
        scheduled.append((func, args, kwargs))

    monkeypatch.setattr(BackgroundTasks, "add_task", fake_add_task)
    return scheduled


def _assert_no_orm_or_session(args, kwargs):
    """Scheduled task args must be plain IDs/lists — never ORM rows or a Session."""
    from sqlalchemy.orm import Session

    from app.models.event import Event
    from app.models.user import User

    for value in (*args, *kwargs.values()):
        assert not isinstance(value, Session), "background task must not receive a Session"
        assert not isinstance(value, (SongRequest, Event, User)), (
            "background task must not receive a live ORM object"
        )
        if isinstance(value, list):
            for item in value:
                assert not isinstance(item, (SongRequest, Event, User)), (
                    "background task must not receive a list of ORM objects"
                )


def test_bulk_review_schedules_ids_not_orm_objects(
    client, db, auth_headers, test_event, collection_requests, monkeypatch
):
    """Accepting multiple rows schedules N enrich(ID) tasks + ONE batch-sync(list[ID]).

    Proves one accepted request does not pin N long-lived task sessions: the batch
    sync is a single task carrying a list of IDs, and every scheduled arg is a
    plain ID, never the request `db` or a live ORM row.
    """
    scheduled = _record_scheduled_tasks(monkeypatch)

    ids = [r.id for r in collection_requests]
    resp = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "accept_ids", "request_ids": ids},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    for func, args, kwargs in scheduled:
        _assert_no_orm_or_session(args, kwargs)

    enrich_tasks = [s for s in scheduled if s[0] is events_module._enrich_with_fresh_session]
    sync_tasks = [s for s in scheduled if s[0] is events_module._sync_requests_with_fresh_session]

    # One enrich task per accepted row, each carrying a single int ID.
    assert len(enrich_tasks) == len(ids)
    assert all(isinstance(s[1][0], int) for s in enrich_tasks)
    # Exactly ONE batch-sync task for all accepted rows — not one per row.
    assert len(sync_tasks) == 1
    sync_ids = sync_tasks[0][1][0]
    assert isinstance(sync_ids, list)
    assert sorted(sync_ids) == sorted(ids)


def test_patch_accept_schedules_request_id_not_orm(
    client, db, auth_headers, test_event, monkeypatch
):
    """PATCH accept schedules sync by request ID (not the request `db`/ORM row)."""
    row = SongRequest(
        event_id=test_event.id,
        song_title="Accept Me",
        artist="DJ Z",
        source="spotify",
        status=RequestStatus.NEW.value,
        dedupe_key="accept-me",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Force the "has connected adapters" branch so the sync task is scheduled.
    monkeypatch.setattr(requests_module, "get_connected_adapters", lambda user: ["tidal"])
    scheduled = _record_scheduled_tasks(monkeypatch)

    resp = client.patch(
        f"/api/requests/{row.id}",
        json={"status": "accepted"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    sync_tasks = [
        s for s in scheduled if s[0] is requests_module._sync_request_to_services_with_fresh_session
    ]
    assert len(sync_tasks) == 1
    func, args, kwargs = sync_tasks[0]
    _assert_no_orm_or_session(args, kwargs)
    assert args == (row.id,)

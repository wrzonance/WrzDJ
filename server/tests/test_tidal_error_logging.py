"""Regression tests for Tidal device-flow expiry and safe provider error logs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models.request import Request, RequestStatus
from app.services.providers import (
    tidal_account,
    tidal_catalog,
    tidal_playlists,
    tidal_request_sync,
    tidal_search,
)
from app.services.providers.tidal_catalog import TidalFetchError
from app.services.sync import orchestrator
from app.services.sync.base import TrackMatch


def test_expired_tidal_device_login_cannot_complete(db, test_user, monkeypatch):
    # Regression (57cfcdc6867f): local device-login TTL was only pruned when a new flow started.
    future = MagicMock()
    future.done.return_value = True
    future.result.return_value = None
    session = MagicMock()
    session.access_token = "expired-flow-access"
    session.refresh_token = "expired-flow-refresh"
    session.expiry_time = datetime.now(UTC) + timedelta(hours=1)
    session.user.id = "expired-flow-user"
    state = tidal_account.DeviceLoginState(
        user_id=test_user.id,
        session=session,
        login_info=MagicMock(),
        future=future,
        created_at=datetime.now(UTC)
        - timedelta(minutes=tidal_account.DEVICE_LOGIN_TTL_MINUTES + 1),
    )
    states = {test_user.id: state}
    monkeypatch.setattr(tidal_account, "_device_logins", states)

    result = tidal_account.check_device_login(db, test_user)

    assert result == {"complete": False, "error": "Tidal login expired. Please try again."}
    assert test_user.tidal_access_token is None
    assert test_user.tidal_refresh_token is None
    assert test_user.id not in states
    future.cancel.assert_called_once_with()
    future.result.assert_not_called()


def test_tidal_provider_error_logs_never_include_exception_text(
    db, test_user, test_event, caplog, monkeypatch
):
    # Regression (57cfcdc6867f): Tidal SDK exceptions may stringify request URLs or credentials.
    sentinel = "https://tidal.example/path?access_token=do-not-log"
    failure = RuntimeError(sentinel)
    session = MagicMock()
    caplog.set_level("WARNING")

    # Catalog list, search, and playlist fetch boundaries.
    monkeypatch.setattr(tidal_catalog, "get_tidal_session", lambda *_: session)
    session.user.playlists.side_effect = failure
    tidal_catalog.list_user_playlists(db, test_user)
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    session.search.side_effect = failure
    assert tidal_catalog.search_tidal_tracks(db, test_user, "search query") == []
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    session.playlist.side_effect = failure
    with pytest.raises(TidalFetchError) as raised:
        tidal_catalog.get_playlist_tracks(db, test_user, "playlist-id")
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text
    assert sentinel not in str(raised.value)

    # Provider-specific search and playlist mutation paths.
    caplog.clear()
    monkeypatch.setattr(tidal_search, "get_tidal_session", lambda *_: session)
    session.search.side_effect = failure
    assert tidal_search.search_track(db, test_user, "artist", "title") is None
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    monkeypatch.setattr(tidal_playlists, "get_tidal_session", lambda *_: session)
    session.user.create_playlist.side_effect = failure
    assert tidal_playlists.create_event_playlist(db, test_user, test_event) is None
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    assert tidal_playlists.ensure_collection_playlist(db, test_user, test_event) is None
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    assert tidal_playlists._playlist_exists(session, "playlist-id") is True
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    assert (
        tidal_playlists.add_tracks_to_playlist(db, test_user, "playlist-id", ["track-id"]) is False
    )
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    caplog.clear()
    test_event.tidal_collection_playlist_id = "playlist-id"
    assert (
        tidal_playlists.remove_track_from_collection_playlist(db, test_user, test_event, "track-id")
        is False
    )
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    # Background collection sync logs an escaped search failure with request context only.
    caplog.clear()
    row = Request(
        event_id=test_event.id,
        song_title="Example",
        artist="Artist",
        status=RequestStatus.NEW.value,
        submitted_during_collection=True,
        dedupe_key="artist:example-collection",
    )
    db.add(row)
    db.commit()
    monkeypatch.setattr(tidal_request_sync, "ensure_collection_playlist", lambda *_: "playlist-id")
    monkeypatch.setattr(tidal_request_sync, "search_tidal_tracks", MagicMock(side_effect=failure))
    tidal_request_sync.sync_collection_requests_batch(db, test_user, test_event, [row])
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    # Device-flow completion errors also retain class/context without SDK text.
    caplog.clear()
    future = MagicMock()
    future.done.return_value = True
    future.result.side_effect = failure
    state = tidal_account.DeviceLoginState(
        user_id=test_user.id,
        session=MagicMock(),
        login_info=MagicMock(),
        future=future,
    )
    monkeypatch.setattr(tidal_account, "_device_logins", {test_user.id: state})
    assert tidal_account.check_device_login(db, test_user)["complete"] is False
    assert "RuntimeError" in caplog.text and sentinel not in caplog.text

    # Polling must not persist an exception's raw text into the activity log either.
    caplog.clear()
    monkeypatch.setattr(
        tidal_playlists,
        "get_playlist_tracks",
        MagicMock(side_effect=TidalFetchError(sentinel)),
    )
    tidal_playlists.poll_tidal_collection_removals(db, test_event)
    assert sentinel not in caplog.text


def test_batch_add_logs_sanitize_provider_exception_text(
    db, test_event, test_user, caplog, monkeypatch
):
    # Regression (57cfcdc6867f): batch-add bypassed sanitize_sync_error in its log message.
    sentinel = "https://provider.example/add?refresh_token=do-not-log"
    failure = RuntimeError(sentinel)
    request = Request(
        event_id=test_event.id,
        song_title="Example",
        artist="Artist",
        status=RequestStatus.ACCEPTED.value,
        raw_search_query="Artist Example",
        dedupe_key="artist:example",
    )
    test_event.created_by = test_user
    db.add(request)
    db.commit()

    class RaisingBatchAdapter:
        service_name = "tidal"

        def is_sync_enabled(self, event):
            return True

        def search_track(self, *_args):
            return TrackMatch(
                service=self.service_name,
                track_id="track-id",
                title="Example",
                artist="Artist",
                match_confidence=1.0,
            )

        def ensure_playlist(self, *_args):
            return "playlist-id"

        def add_tracks_to_playlist(self, *_args):
            raise failure

    monkeypatch.setattr(
        orchestrator, "get_connected_adapters", lambda _user: [RaisingBatchAdapter()]
    )
    caplog.set_level("ERROR")

    orchestrator.sync_requests_batch(db, [request])

    assert "RuntimeError" in caplog.text
    assert sentinel not in caplog.text
    assert '"status": "error"' in request.sync_results_json

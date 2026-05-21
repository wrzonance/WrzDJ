"""Tests for sync orchestrator."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.sync.base import SyncResult, SyncStatus, TrackMatch
from app.services.sync.orchestrator import (
    MultiSyncResult,
    _extract_source_track_id,
    _find_best_match,
    _get_isrc_from_spotify,
    _is_already_synced,
    _persist_sync_result,
    enrich_request_metadata,
    sync_request_to_services,
    sync_requests_batch,
)
from app.services.sync.registry import _clear_adapters, register_adapter


@pytest.fixture
def tidal_user(db: Session) -> User:
    from app.services.auth import get_password_hash

    user = User(
        username="sync_orch_user",
        password_hash=get_password_hash("testpassword123"),
        tidal_access_token="test_access_token",
        tidal_refresh_token="test_refresh_token",
        tidal_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        tidal_user_id="12345",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def tidal_event(db: Session, tidal_user: User) -> Event:
    event = Event(
        code="ORCH01",
        join_code="ORCH01J",
        name="Orchestrator Test Event",
        created_by_user_id=tidal_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        tidal_sync_enabled=True,
        tidal_playlist_id="playlist_orch",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def accepted_request(db: Session, tidal_event: Event) -> Request:
    request = Request(
        event_id=tidal_event.id,
        song_title="Strobe",
        artist="deadmau5",
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="orch_test_dedupe_key",
        raw_search_query="deadmau5 Strobe",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@pytest.fixture
def accepted_request_no_query(db: Session, tidal_event: Event) -> Request:
    request = Request(
        event_id=tidal_event.id,
        song_title="Alive",
        artist="Daft Punk",
        source="manual",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="orch_test_no_query",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def _make_accepted_request(db: Session, event: Event, title: str, artist: str, key: str) -> Request:
    """Helper to create accepted requests for batch tests."""
    request = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key=key,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


class MockAdapter:
    """Mock adapter for testing."""

    def __init__(self, name="mock_service", connected=True, sync_result=None, sync_enabled=True):
        self._name = name
        self._connected = connected
        self._sync_result = sync_result
        self._sync_enabled = sync_enabled
        self.search_calls = []
        self.batch_add_calls = []

    @property
    def service_name(self):
        return self._name

    def is_connected(self, user):
        return self._connected

    def is_sync_enabled(self, event):
        return self._sync_enabled

    def sync_track(self, db, user, event, normalized, intent=None):
        if self._sync_result:
            return self._sync_result
        return SyncResult(
            service=self._name,
            status=SyncStatus.ADDED,
            track_match=TrackMatch(
                service=self._name,
                track_id="mock_track_123",
                title="Strobe",
                artist="deadmau5",
                match_confidence=0.95,
            ),
            playlist_id="mock_playlist_456",
        )

    def search_track(self, db, user, normalized, intent=None):
        self.search_calls.append(normalized)
        return TrackMatch(
            service=self._name,
            track_id=f"track_{normalized.raw_title.lower().replace(' ', '_')}",
            title=normalized.raw_title,
            artist=normalized.raw_artist,
            match_confidence=0.95,
        )

    def ensure_playlist(self, db, user, event):
        return event.tidal_playlist_id or "mock_playlist"

    def add_to_playlist(self, db, user, playlist_id, track_id):
        return True

    def add_tracks_to_playlist(self, db, user, playlist_id, track_ids):
        self.batch_add_calls.append(track_ids)
        return True


@pytest.fixture(autouse=True)
def clean_registry():
    _clear_adapters()
    yield
    _clear_adapters()


class TestMultiSyncResult:
    def test_any_added_true(self):
        r = MultiSyncResult(
            results=[
                SyncResult(service="a", status=SyncStatus.ADDED),
                SyncResult(service="b", status=SyncStatus.NOT_FOUND),
            ]
        )
        assert r.any_added is True

    def test_any_added_false(self):
        r = MultiSyncResult(
            results=[
                SyncResult(service="a", status=SyncStatus.NOT_FOUND),
            ]
        )
        assert r.any_added is False

    def test_all_not_found_true(self):
        r = MultiSyncResult(
            results=[
                SyncResult(service="a", status=SyncStatus.NOT_FOUND),
                SyncResult(service="b", status=SyncStatus.NOT_FOUND),
            ]
        )
        assert r.all_not_found is True

    def test_all_not_found_false_when_empty(self):
        r = MultiSyncResult(results=[])
        assert r.all_not_found is False


class TestSyncRequestToServices:
    def test_happy_path(self, db, accepted_request):
        adapter = MockAdapter("tidal")
        register_adapter(adapter)

        result = sync_request_to_services(db, accepted_request)

        assert len(result.results) == 1
        assert result.results[0].status == SyncStatus.ADDED
        assert result.any_added is True

        # Check JSON persisted
        db.refresh(accepted_request)
        assert accepted_request.sync_results_json is not None
        data = json.loads(accepted_request.sync_results_json)
        assert len(data) == 1
        assert data[0]["service"] == "tidal"
        assert data[0]["status"] == "added"
        assert data[0]["track_id"] == "mock_track_123"

    def test_no_connected_adapters(self, db, accepted_request):
        # No adapters registered
        result = sync_request_to_services(db, accepted_request)
        assert len(result.results) == 0

    def test_adapter_not_found(self, db, accepted_request):
        adapter = MockAdapter(
            "tidal",
            sync_result=SyncResult(service="tidal", status=SyncStatus.NOT_FOUND),
        )
        register_adapter(adapter)

        sync_request_to_services(db, accepted_request)

        db.refresh(accepted_request)
        data = json.loads(accepted_request.sync_results_json)
        assert data[0]["status"] == "not_found"

    def test_adapter_error(self, db, accepted_request):
        adapter = MockAdapter(
            "tidal",
            sync_result=SyncResult(
                service="tidal",
                status=SyncStatus.ERROR,
                error="Connection failed",
            ),
        )
        register_adapter(adapter)

        sync_request_to_services(db, accepted_request)

        db.refresh(accepted_request)
        data = json.loads(accepted_request.sync_results_json)
        assert data[0]["status"] == "error"

    def test_no_raw_search_query(self, db, accepted_request_no_query):
        """Intent should be None when no raw_search_query is set."""
        adapter = MockAdapter("tidal")
        register_adapter(adapter)

        result = sync_request_to_services(db, accepted_request_no_query)

        assert len(result.results) == 1
        assert result.any_added is True

    def test_multiple_adapters(self, db, accepted_request):
        """Multiple adapters sync independently."""
        tidal = MockAdapter("tidal")
        beatport = MockAdapter(
            "beatport",
            sync_result=SyncResult(service="beatport", status=SyncStatus.NOT_FOUND),
        )
        register_adapter(tidal)
        register_adapter(beatport)

        result = sync_request_to_services(db, accepted_request)

        assert len(result.results) == 2
        services = {r.service for r in result.results}
        assert services == {"tidal", "beatport"}

    def test_adapter_exception_caught(self, db, accepted_request):
        """Adapter exceptions are caught and converted to ERROR results."""

        class FailingAdapter(MockAdapter):
            def sync_track(self, db, user, event, normalized, intent=None):
                raise RuntimeError("Connection reset")

        adapter = FailingAdapter("tidal")
        register_adapter(adapter)

        result = sync_request_to_services(db, accepted_request)

        assert len(result.results) == 1
        assert result.results[0].status == SyncStatus.ERROR
        # Error is now sanitized — generic message instead of raw exception
        assert result.results[0].error == "Sync operation failed"

    def test_adapter_exception_error_is_sanitized(self, db, accepted_request):
        """httpx exceptions produce sanitized error messages."""
        import httpx

        class HttpxFailingAdapter(MockAdapter):
            def sync_track(self, db, user, event, normalized, intent=None):
                raise httpx.ConnectError("Bearer sk-secret at api.beatport.com")

        adapter = HttpxFailingAdapter("tidal")
        register_adapter(adapter)

        result = sync_request_to_services(db, accepted_request)

        assert len(result.results) == 1
        assert result.results[0].status == SyncStatus.ERROR
        assert "Bearer" not in result.results[0].error
        assert result.results[0].error == "External API connection failed"

    def test_disconnected_adapter_skipped(self, db, accepted_request):
        """Disconnected adapters are not included."""
        connected = MockAdapter("tidal", connected=True)
        disconnected = MockAdapter("beatport", connected=False)
        register_adapter(connected)
        register_adapter(disconnected)

        result = sync_request_to_services(db, accepted_request)

        assert len(result.results) == 1
        assert result.results[0].service == "tidal"

    def test_sync_disabled_adapter_skipped(self, db, accepted_request):
        """Adapters where sync is disabled for the event are skipped."""
        enabled = MockAdapter("tidal", sync_enabled=True)
        disabled = MockAdapter("beatport", sync_enabled=False)
        register_adapter(enabled)
        register_adapter(disabled)

        result = sync_request_to_services(db, accepted_request)

        assert len(result.results) == 1
        assert result.results[0].service == "tidal"


class TestIsAlreadySynced:
    def test_tidal_synced_via_json(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_synced")
        request.sync_results_json = json.dumps([{"service": "tidal", "status": "added"}])
        db.commit()
        assert _is_already_synced(request, "tidal") is True

    def test_tidal_not_synced(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_none")
        assert _is_already_synced(request, "tidal") is False

    def test_tidal_error_not_synced(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_err")
        request.sync_results_json = json.dumps([{"service": "tidal", "status": "error"}])
        db.commit()
        assert _is_already_synced(request, "tidal") is False

    def test_json_synced(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_json")
        request.sync_results_json = json.dumps([{"service": "beatport", "status": "added"}])
        db.commit()
        assert _is_already_synced(request, "beatport") is True

    def test_json_not_found_not_synced(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_nf")
        request.sync_results_json = json.dumps([{"service": "beatport", "status": "not_found"}])
        db.commit()
        assert _is_already_synced(request, "beatport") is False

    def test_different_service_not_synced(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_diff")
        request.sync_results_json = json.dumps([{"service": "tidal", "status": "added"}])
        db.commit()
        assert _is_already_synced(request, "beatport") is False

    def test_invalid_json_not_synced(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "dedup_bad")
        request.sync_results_json = "not json"
        db.commit()
        assert _is_already_synced(request, "tidal") is False


class TestPersistSyncResult:
    def test_persist_added(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "persist_add")
        result = SyncResult(
            service="tidal",
            status=SyncStatus.ADDED,
            track_match=TrackMatch(
                service="tidal",
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                match_confidence=0.95,
            ),
            playlist_id="playlist_abc",
        )
        _persist_sync_result(request, result)
        db.commit()

        data = json.loads(request.sync_results_json)
        assert len(data) == 1
        assert data[0]["service"] == "tidal"
        assert data[0]["status"] == "added"
        assert data[0]["track_id"] == "123"

    def test_persist_upserts_same_service(self, db, tidal_event):
        """Second result for same service replaces the first."""
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "persist_ups")
        # First: error
        _persist_sync_result(
            request, SyncResult(service="tidal", status=SyncStatus.ERROR, error="failed")
        )
        # Second: success
        _persist_sync_result(
            request,
            SyncResult(
                service="tidal",
                status=SyncStatus.ADDED,
                track_match=TrackMatch(
                    service="tidal",
                    track_id="456",
                    title="Strobe",
                    artist="deadmau5",
                    match_confidence=0.9,
                ),
            ),
        )
        db.commit()

        data = json.loads(request.sync_results_json)
        assert len(data) == 1  # Replaced, not appended
        assert data[0]["status"] == "added"
        assert data[0]["track_id"] == "456"

    def test_persist_multiple_services(self, db, tidal_event):
        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "persist_multi")
        _persist_sync_result(
            request,
            SyncResult(
                service="tidal",
                status=SyncStatus.ADDED,
                track_match=TrackMatch(
                    service="tidal",
                    track_id="1",
                    title="Strobe",
                    artist="deadmau5",
                    match_confidence=0.9,
                ),
            ),
        )
        _persist_sync_result(request, SyncResult(service="beatport", status=SyncStatus.NOT_FOUND))
        db.commit()

        data = json.loads(request.sync_results_json)
        assert len(data) == 2
        services = {d["service"] for d in data}
        assert services == {"tidal", "beatport"}


class TestSyncRequestsBatch:
    def test_batch_happy_path(self, db, tidal_event, tidal_user):
        """Batch sync: all tracks found, single batch add."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_1")
        r2 = _make_accepted_request(db, tidal_event, "Ghosts", "deadmau5", "batch_2")
        r3 = _make_accepted_request(db, tidal_event, "Faxing Berlin", "deadmau5", "batch_3")

        adapter = MockAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1, r2, r3])

        # Verify single batch add call with all 3 track IDs
        assert len(adapter.batch_add_calls) == 1
        assert len(adapter.batch_add_calls[0]) == 3

        # Verify all requests have synced status
        for r in [r1, r2, r3]:
            db.refresh(r)
            data = json.loads(r.sync_results_json)
            assert data[0]["status"] == "added"

    def test_batch_partial_not_found(self, db, tidal_event, tidal_user):
        """Some tracks found, some not — found tracks still batch-added."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_p1")
        r2 = _make_accepted_request(db, tidal_event, "Unknown", "Nobody", "batch_p2")

        class PartialAdapter(MockAdapter):
            def search_track(self, db, user, normalized, intent=None):
                if "Unknown" in normalized.raw_title:
                    return None
                return super().search_track(db, user, normalized, intent)

        adapter = PartialAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1, r2])

        # r1 synced, r2 not found
        db.refresh(r1)
        data1 = json.loads(r1.sync_results_json)
        assert data1[0]["status"] == "added"

        db.refresh(r2)
        data2 = json.loads(r2.sync_results_json)
        assert data2[0]["status"] == "not_found"

        # Only 1 track in batch add
        assert len(adapter.batch_add_calls) == 1
        assert len(adapter.batch_add_calls[0]) == 1

    def test_batch_skips_already_synced(self, db, tidal_event, tidal_user):
        """Requests already synced are skipped entirely."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_s1")
        r1.sync_results_json = json.dumps([{"service": "tidal", "status": "added"}])
        db.commit()

        r2 = _make_accepted_request(db, tidal_event, "Ghosts", "deadmau5", "batch_s2")

        adapter = MockAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1, r2])

        # Only r2 was searched (r1 skipped)
        assert len(adapter.search_calls) == 1
        assert adapter.search_calls[0].raw_title == "Ghosts"

        # Only 1 track in batch add
        assert len(adapter.batch_add_calls) == 1
        assert len(adapter.batch_add_calls[0]) == 1

    def test_batch_all_already_synced(self, db, tidal_event, tidal_user):
        """When all requests are already synced, no API calls made."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_a1")
        r1.sync_results_json = json.dumps([{"service": "tidal", "status": "added"}])
        db.commit()

        adapter = MockAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1])

        assert len(adapter.search_calls) == 0
        assert len(adapter.batch_add_calls) == 0

    def test_batch_add_failure(self, db, tidal_event, tidal_user):
        """When batch add fails, all found requests get ERROR status."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_f1")
        r2 = _make_accepted_request(db, tidal_event, "Ghosts", "deadmau5", "batch_f2")

        class FailAddAdapter(MockAdapter):
            def add_tracks_to_playlist(self, db, user, playlist_id, track_ids):
                self.batch_add_calls.append(track_ids)
                return False

        adapter = FailAddAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1, r2])

        for r in [r1, r2]:
            db.refresh(r)
            data = json.loads(r.sync_results_json)
            assert data[0]["status"] == "error"

    def test_batch_playlist_failure(self, db, tidal_event, tidal_user):
        """When playlist creation fails, all found tracks get ERROR."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_pl1")

        class NoPlaylistAdapter(MockAdapter):
            def ensure_playlist(self, db, user, event):
                return None

        adapter = NoPlaylistAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1])

        db.refresh(r1)
        data = json.loads(r1.sync_results_json)
        assert data[0]["status"] == "error"

    def test_batch_empty_list(self, db):
        """Empty request list is a no-op."""
        adapter = MockAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [])

        assert len(adapter.search_calls) == 0

    def test_batch_no_adapters(self, db, tidal_event, tidal_user):
        """No adapters registered — no-op."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_na1")
        sync_requests_batch(db, [r1])

        db.refresh(r1)
        assert r1.sync_results_json is None

    def test_batch_search_exception(self, db, tidal_event, tidal_user):
        """Search exception for one track doesn't block others."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_e1")
        r2 = _make_accepted_request(db, tidal_event, "BadTrack", "Error", "batch_e2")

        class PartialErrorAdapter(MockAdapter):
            def search_track(self, db, user, normalized, intent=None):
                self.search_calls.append(normalized)
                if "BadTrack" in normalized.raw_title:
                    raise RuntimeError("API timeout")
                return super().search_track(db, user, normalized, intent)

        adapter = PartialErrorAdapter("tidal")
        register_adapter(adapter)

        sync_requests_batch(db, [r1, r2])

        # r1 succeeded, r2 got error
        db.refresh(r1)
        data1 = json.loads(r1.sync_results_json)
        assert data1[0]["status"] == "added"

        db.refresh(r2)
        data2 = json.loads(r2.sync_results_json)
        assert data2[0]["status"] == "error"

    def test_batch_sync_disabled_skipped(self, db, tidal_event, tidal_user):
        """Adapters with sync disabled are skipped in batch mode too."""
        r1 = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "batch_dis1")

        adapter = MockAdapter("tidal", sync_enabled=False)
        register_adapter(adapter)

        sync_requests_batch(db, [r1])

        assert len(adapter.search_calls) == 0
        db.refresh(r1)
        assert r1.sync_results_json is None


class TestEnrichRequestMetadata:
    """Tests for enrich_request_metadata background task."""

    def test_skips_when_all_metadata_present(self, db, tidal_event):
        """Requests with genre, bpm, and key are skipped entirely."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Test Artist", "enrich_skip")
        request.genre = "country"
        request.bpm = 120.0
        request.musical_key = "8A"
        db.commit()

        enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "country"
        assert request.bpm == 120.0
        assert request.musical_key == "8A"

    def test_skips_nonexistent_request(self, db):
        """Non-existent request ID is a no-op."""
        enrich_request_metadata(db, 999999)  # Should not raise

    def test_musicbrainz_fills_genre_first(self, db, tidal_event):
        """MusicBrainz is tried first for genre (before Beatport)."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Radiohead", "enrich_mb")
        db.commit()

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value="alternative rock",
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "alternative rock"

    def test_musicbrainz_skipped_when_genre_present(self, db, tidal_event):
        """MusicBrainz is not called when genre already exists."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_mb_skip")
        request.genre = "country"
        db.commit()

        with patch("app.services.sync.enrichment_pipeline.lookup_artist_genre") as mock_mb:
            enrich_request_metadata(db, request.id)
            mock_mb.assert_not_called()

    def test_beatport_fills_bpm_key_and_backfills_genre(self, db, tidal_event, tidal_user):
        """Beatport fills BPM/key (and genre when MusicBrainz missed)."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "enrich_bp")
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_results = [
            BeatportSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                genre="Progressive House",
                bpm=128,
                key="F Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.beatport.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "Progressive House"  # Backfilled by Beatport
        assert request.bpm == 128.0
        assert request.musical_key == "4A"  # F Minor -> 4A in Camelot

    def test_beatport_skips_genre_when_musicbrainz_filled(self, db, tidal_event, tidal_user):
        """Beatport doesn't overwrite genre already set by MusicBrainz."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "enrich_bp_nogenre")
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_results = [
            BeatportSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                genre="Progressive House",
                bpm=128,
                key="F Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value="electronic",
        ):
            with patch(
                "app.services.beatport.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "electronic"  # MusicBrainz's genre kept
        assert request.bpm == 128.0  # Beatport's BPM used
        assert request.musical_key == "4A"  # Beatport's key used

    def test_tidal_fills_bpm_key_when_beatport_missing(self, db, tidal_event, tidal_user):
        """Tidal provides BPM/key when Beatport is not connected."""
        # User has Tidal but no Beatport
        assert tidal_user.beatport_access_token is None

        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_tidal")
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        mock_results = [
            TidalSearchResult(
                track_id="999",
                title="Test Song",
                artist="Artist",
                bpm=120.0,
                key="D Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value="pop",
        ):
            with patch(
                "app.services.tidal.search_tidal_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.genre == "pop"  # From MusicBrainz
        assert request.bpm == 120.0  # From Tidal
        assert request.musical_key == "7A"  # D Minor -> 7A from Tidal

    def test_tidal_skipped_when_beatport_filled_bpm_key(self, db, tidal_event, tidal_user):
        """Tidal is not called when Beatport already provided BPM + key."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(db, tidal_event, "Strobe", "deadmau5", "enrich_skip_tidal")
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_bp_results = [
            BeatportSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                genre="Progressive House",
                bpm=128,
                key="F Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.beatport.search_beatport_tracks",
                return_value=mock_bp_results,
            ):
                with patch(
                    "app.services.tidal.search_tidal_tracks",
                ) as mock_tidal:
                    enrich_request_metadata(db, request.id)
                    mock_tidal.assert_not_called()

    def test_tidal_enrichment_failure_is_graceful(self, db, tidal_event, tidal_user):
        """Tidal enrichment exceptions don't crash the task."""
        request = _make_accepted_request(db, tidal_event, "Song", "Artist", "enrich_tidal_fail")
        db.commit()

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.tidal.search_tidal_tracks",
                side_effect=RuntimeError("Tidal API down"),
            ):
                enrich_request_metadata(db, request.id)  # Should not raise

        db.refresh(request)
        assert request.bpm is None  # Gracefully degraded

    def test_normalizes_key_from_enrichment(self, db, tidal_event):
        """Musical key from enrichment is normalized to Camelot notation."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_key_norm")
        request.musical_key = "D Minor"
        db.commit()

        enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.musical_key == "7A"  # D Minor = 7A

    def test_musicbrainz_failure_is_graceful(self, db, tidal_event):
        """MusicBrainz exceptions don't crash the enrichment task."""
        request = _make_accepted_request(db, tidal_event, "Test Song", "Artist", "enrich_mb_fail")
        db.commit()

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            side_effect=RuntimeError("Network error"),
        ):
            enrich_request_metadata(db, request.id)  # Should not raise

        db.refresh(request)
        assert request.genre is None  # Gracefully degraded

    def test_beatport_enrichment_skips_non_matching_results(self, db, tidal_event, tidal_user):
        """Beatport results that don't match the requested song are skipped."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(
            db, tidal_event, "Feel The Beat", "Darude", "enrich_no_match"
        )
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        # Beatport returns a totally different track first
        mock_results = [
            BeatportSearchResult(
                track_id="999",
                title="Wrong Song",
                artist="Wrong Artist",
                genre="Techno",
                bpm=72,
                key="A Minor",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.beatport.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.bpm is None  # Should NOT take 72 BPM from wrong track
        assert request.genre is None
        assert request.musical_key is None

    def test_tidal_enrichment_skips_non_matching_results(self, db, tidal_event, tidal_user):
        """Tidal results that don't match the requested song are skipped."""
        request = _make_accepted_request(
            db, tidal_event, "Feel The Beat", "Darude", "enrich_tidal_no_match"
        )
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        mock_results = [
            TidalSearchResult(
                track_id="999",
                title="Totally Different Track",
                artist="Some Other Artist",
                bpm=72.0,
                key="C Major",
            )
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.tidal.search_tidal_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.bpm is None  # Should NOT take BPM from wrong track
        assert request.musical_key is None

    def test_beatport_enrichment_rejects_same_title_wrong_artist(self, db, tidal_event, tidal_user):
        """Beatport result with matching title but wrong artist is rejected.

        Real-world case: searching "Darude Feel The Beat" returns
        "Feel the Beat" by LB aka LABAT (72 BPM) as the first result.
        The title matches perfectly but the artist is completely different.
        """
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(
            db, tidal_event, "Feel The Beat", "Darude", "enrich_wrong_artist"
        )
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        mock_results = [
            BeatportSearchResult(
                track_id="16190399",
                title="Feel the Beat",
                artist="LB aka LABAT",
                genre="House",
                bpm=72,
                key="Gb Major",
            ),
            BeatportSearchResult(
                track_id="13280071",
                title="Darude",
                artist="Victor Vandale",
                genre="Techno (Peak Time / Driving)",
                bpm=124,
                key="F# Minor",
            ),
        ]

        with patch(
            "app.services.sync.enrichment_pipeline.lookup_artist_genre",
            return_value=None,
        ):
            with patch(
                "app.services.beatport.search_beatport_tracks",
                return_value=mock_results,
            ):
                enrich_request_metadata(db, request.id)

        db.refresh(request)
        assert request.bpm is None  # Must NOT take 72 BPM from LB aka LABAT
        assert request.genre is None  # Must NOT take "House" from wrong track
        assert request.musical_key is None

    def test_bpm_context_excludes_new_requests(self, db, tidal_event, tidal_user):
        """BPM context correction should only use accepted/played/playing requests."""
        # Create accepted requests with BPMs to form context (median ~130)
        for i, bpm_val in enumerate([128.0, 130.0, 132.0]):
            r = _make_accepted_request(db, tidal_event, f"Track {i}", f"Artist {i}", f"bpm_ctx_{i}")
            r.status = RequestStatus.ACCEPTED.value
            r.bpm = bpm_val
        db.commit()

        # Create a NEW request with BPM that should NOT be in context
        new_req = _make_accepted_request(db, tidal_event, "Troll Track", "Troll", "bpm_ctx_new")
        new_req.status = RequestStatus.NEW.value
        new_req.bpm = 200.0  # Would skew median if included
        db.commit()

        # Create the request to enrich — 65 BPM should double to 130
        # (within 15% of median 130). Leave musical_key=None so we don't
        # hit the "already complete" early-return.
        target = _make_accepted_request(
            db, tidal_event, "Half Time Track", "Artist", "bpm_ctx_target"
        )
        target.genre = "electronic"
        target.bpm = 65.0
        db.commit()

        # Mock external services to avoid network calls (Tidal fills missing key)
        with patch(
            "app.services.tidal.search_tidal_tracks",
            return_value=[],
        ):
            enrich_request_metadata(db, target.id)

        db.refresh(target)
        # With status filter: median = 130, 65*2 = 130 → corrected
        # Without status filter: median would include 200, skewing context
        assert target.bpm == 130.0


class TestFindBestMatchVersionPreference:
    """Tests for _find_best_match() version-aware scoring."""

    def test_beatport_original_beats_remix_on_tie(self):
        """When title/artist scores are equal, Original Mix wins over remix."""
        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Surrender",
                artist="Darude",
                mix_name="Hardstyle Remix",
                bpm=165,
            ),
            BeatportSearchResult(
                track_id="2",
                title="Surrender",
                artist="Darude",
                mix_name="Original Mix",
                bpm=132,
            ),
        ]
        best = _find_best_match(results, "Surrender", "Darude", prefer_original=True)
        assert best.track_id == "2"
        assert best.bpm == 132

    def test_beatport_remix_preferred_when_requested(self):
        """When request title contains remix, prefer_original=False lets remix win."""
        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Surrender",
                artist="Darude",
                mix_name="Hardstyle Remix",
                bpm=165,
            ),
            BeatportSearchResult(
                track_id="2",
                title="Surrender",
                artist="Darude",
                mix_name="Original Mix",
                bpm=132,
            ),
        ]
        # With prefer_original=False, no bonus/penalty — first result wins on tie
        best = _find_best_match(results, "Surrender", "Darude", prefer_original=False)
        # Both have identical scores, first one encountered wins
        assert best is not None

    def test_tidal_remix_penalized(self):
        """Tidal results with remix in title get penalized for non-remix queries."""
        from types import SimpleNamespace

        results = [
            SimpleNamespace(title="Surrender (Hardstyle Remix)", artist="Darude", bpm=165),
            SimpleNamespace(title="Surrender", artist="Darude", bpm=132),
        ]
        best = _find_best_match(results, "Surrender", "Darude", prefer_original=True)
        # Plain title should win over remix title
        assert best.title == "Surrender"
        assert best.bpm == 132

    def test_prefer_original_disabled(self):
        """With prefer_original=False, no version scoring applied."""
        from types import SimpleNamespace

        results = [
            SimpleNamespace(title="Surrender (Hardstyle Remix)", artist="Darude", bpm=165),
            SimpleNamespace(title="Surrender", artist="Darude", bpm=132),
        ]
        # Without prefer_original, both have similar scores — first wins
        best = _find_best_match(results, "Surrender", "Darude", prefer_original=False)
        assert best is not None

    def test_bpm_consensus_tiebreaker(self):
        """When title/artist scores are identical, modal BPM wins."""
        from types import SimpleNamespace

        # Tidal returns multiple "Surrender" — 3 at 132, 1 at 165
        results = [
            SimpleNamespace(title="Surrender", artist="Darude", bpm=165.0),
            SimpleNamespace(title="Surrender", artist="Darude", bpm=132.0),
            SimpleNamespace(title="Surrender", artist="Darude", bpm=132.0),
            SimpleNamespace(title="Surrender", artist="Darude", bpm=132.0),
        ]
        best = _find_best_match(results, "Surrender", "Darude", prefer_original=True)
        assert best.bpm == 132.0  # Modal BPM among results


class TestExtractSourceTrackId:
    """Tests for _extract_source_track_id()."""

    def test_spotify_url(self):
        svc, tid = _extract_source_track_id("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
        assert svc == "spotify"
        assert tid == "4uLU6hMCjMI75M1A2tKUQC"

    def test_beatport_url(self):
        svc, tid = _extract_source_track_id(
            "https://www.beatport.com/track/the-house-of-house/12345"
        )
        assert svc == "beatport"
        assert tid == "12345"

    def test_tidal_url(self):
        svc, tid = _extract_source_track_id("https://tidal.com/browse/track/67890")
        assert svc == "tidal"
        assert tid == "67890"

    def test_tidal_url_no_browse(self):
        svc, tid = _extract_source_track_id("https://tidal.com/track/99999")
        assert svc == "tidal"
        assert tid == "99999"

    def test_none_url(self):
        svc, tid = _extract_source_track_id(None)
        assert svc is None
        assert tid is None

    def test_non_music_url(self):
        svc, tid = _extract_source_track_id("https://example.com/page")
        assert svc is None
        assert tid is None

    def test_empty_string(self):
        svc, tid = _extract_source_track_id("")
        assert svc is None
        assert tid is None


class TestGetIsrcFromSpotify:
    """Tests for _get_isrc_from_spotify()."""

    def test_returns_isrc_for_spotify_url(self):
        with patch(
            "app.services.spotify._get_spotify_client",
        ) as mock_client:
            mock_client.return_value.track.return_value = {
                "external_ids": {"isrc": "USRC11700041"},
            }
            isrc = _get_isrc_from_spotify("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
            assert isrc == "USRC11700041"
            mock_client.return_value.track.assert_called_once_with("4uLU6hMCjMI75M1A2tKUQC")

    def test_returns_none_for_non_spotify_url(self):
        isrc = _get_isrc_from_spotify("https://tidal.com/browse/track/123")
        assert isrc is None

    def test_returns_none_on_api_error(self):
        with patch(
            "app.services.spotify._get_spotify_client",
            side_effect=RuntimeError("API down"),
        ):
            isrc = _get_isrc_from_spotify("https://open.spotify.com/track/abc123")
            assert isrc is None

    def test_returns_none_for_none_url(self):
        assert _get_isrc_from_spotify(None) is None


class TestDirectFetchEnrichment:
    """Tests for source URL direct fetch in enrich_request_metadata."""

    def test_direct_beatport_enrichment(self, db, tidal_event, tidal_user):
        """Beatport source URL triggers direct fetch, skipping fuzzy search."""
        tidal_user.beatport_access_token = "fake_bp_token"
        db.commit()

        request = _make_accepted_request(
            db, tidal_event, "The House of House", "Cherrymoon Trax", "enrich_bp_direct"
        )
        request.source_url = "https://www.beatport.com/track/the-house-of-house/99999"
        db.commit()

        from app.schemas.beatport import BeatportSearchResult

        direct_track = BeatportSearchResult(
            track_id="99999",
            title="The House Of House",
            artist="Cherrymoon Trax",
            genre="Trance",
            bpm=132,
            key="A Minor",
            mix_name="Original Mix",
        )

        with (
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value=None,
            ),
            patch(
                "app.services.beatport.get_beatport_track",
                return_value=direct_track,
            ) as mock_direct,
            patch(
                "app.services.beatport.search_beatport_tracks",
                return_value=[],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        # Direct fetch should have been called with the extracted track ID
        mock_direct.assert_called_once_with(db, tidal_user, "99999")
        assert request.bpm == 132.0
        assert request.genre == "Trance"

    def test_isrc_tidal_enrichment(self, db, tidal_event, tidal_user):
        """Spotify source URL triggers ISRC lookup → exact Tidal match."""
        request = _make_accepted_request(
            db, tidal_event, "The House of House", "Cherrymoon Trax", "enrich_isrc"
        )
        request.source_url = "https://open.spotify.com/track/abc123"
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        isrc_match = TidalSearchResult(
            track_id="777",
            title="The House Of House",
            artist="Cherrymoon Trax",
            bpm=132.0,
            key="A Minor",
        )

        with (
            patch(
                "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
                return_value="NLRD19800001",
            ),
            patch(
                "app.services.tidal.search_tidal_by_isrc",
                return_value=isrc_match,
            ) as mock_isrc,
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value="trance",
            ),
            patch(
                "app.services.tidal.search_tidal_tracks",
                return_value=[],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        mock_isrc.assert_called_once_with(db, tidal_user, "NLRD19800001")
        assert request.bpm == 132.0  # From ISRC match, not fuzzy search
        assert request.genre == "trance"  # From MusicBrainz

    def test_isrc_fallback_to_fuzzy_when_no_match(self, db, tidal_event, tidal_user):
        """When ISRC returns no Tidal match, falls through to fuzzy search."""
        request = _make_accepted_request(
            db, tidal_event, "Test Song", "Test Artist", "enrich_isrc_fallback"
        )
        request.source_url = "https://open.spotify.com/track/xyz789"
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        fuzzy_result = TidalSearchResult(
            track_id="888",
            title="Test Song",
            artist="Test Artist",
            bpm=120.0,
            key="C Major",
        )

        with (
            patch(
                "app.services.sync.enrichment_pipeline._get_isrc_from_spotify",
                return_value="TEST12345678",
            ),
            patch(
                "app.services.tidal.search_tidal_by_isrc",
                return_value=None,
            ),
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value=None,
            ),
            patch(
                "app.services.tidal.search_tidal_tracks",
                return_value=[fuzzy_result],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        # Should have fallen through to fuzzy Tidal search
        assert request.bpm == 120.0

    def test_direct_tidal_enrichment(self, db, tidal_event, tidal_user):
        """Tidal source URL triggers direct fetch by track ID."""
        request = _make_accepted_request(
            db, tidal_event, "Test Song", "Test Artist", "enrich_tidal_direct"
        )
        request.source_url = "https://tidal.com/browse/track/55555"
        db.commit()

        from app.schemas.tidal import TidalSearchResult

        direct_track = TidalSearchResult(
            track_id="55555",
            title="Test Song",
            artist="Test Artist",
            bpm=140.0,
            key="D Minor",
        )

        with (
            patch(
                "app.services.tidal.get_tidal_track_by_id",
                return_value=direct_track,
            ) as mock_direct,
            patch(
                "app.services.sync.enrichment_pipeline.lookup_artist_genre",
                return_value=None,
            ),
            patch(
                "app.services.tidal.search_tidal_tracks",
                return_value=[],
            ),
        ):
            enrich_request_metadata(db, request.id)

        db.refresh(request)
        mock_direct.assert_called_once_with(db, tidal_user, "55555")
        assert request.bpm == 140.0

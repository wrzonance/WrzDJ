"""Focused tests for sync orchestration."""

import json

from app.services.sync.base import SyncResult, SyncStatus, TrackMatch
from app.services.sync.orchestrator import (
    MultiSyncResult,
    _is_already_synced,
    _persist_sync_result,
    sync_request_to_services,
    sync_requests_batch,
)
from app.services.sync.registry import register_adapter
from tests.sync_orchestrator_fixtures import (
    MockAdapter,  # noqa: F401
    _fixture_accepted_request,  # noqa: F401
    _fixture_accepted_request_no_query,  # noqa: F401
    _fixture_clean_registry,  # noqa: F401
    _fixture_tidal_event,  # noqa: F401
    _fixture_tidal_user,  # noqa: F401
    _make_accepted_request,  # noqa: F401
)


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

    def test_activity_log_failure_does_not_rollback_sync_result(
        self, db, accepted_request, monkeypatch
    ):
        adapter = MockAdapter(
            "tidal",
            sync_result=SyncResult(service="tidal", status=SyncStatus.NOT_FOUND),
        )
        register_adapter(adapter)

        def fail_activity_log(activity_db, *_args, **_kwargs):
            activity_db.rollback()
            raise RuntimeError("activity insert failed")

        monkeypatch.setattr("app.services.activity_log.log_activity", fail_activity_log)

        sync_request_to_services(db, accepted_request)

        db.refresh(accepted_request)
        result = json.loads(accepted_request.sync_results_json)
        assert result[0]["service"] == "tidal"
        assert result[0]["status"] == "not_found"

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

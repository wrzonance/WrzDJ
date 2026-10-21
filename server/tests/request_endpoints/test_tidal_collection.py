"""Song request endpoint tests grouped by behavior."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event


class TestPatchRejectionTidalRemoval:
    """Tests for individual PATCH rejection firing Tidal collection removal."""

    def test_rejecting_synced_collection_request_queues_tidal_removal(
        self, client: TestClient, db: Session, auth_headers: dict, test_event: Event, monkeypatch
    ):
        """Rejecting a synced collection request queues removal from Tidal playlist."""
        from app.models.request import Request as SongRequest
        from app.models.request import RequestStatus

        test_event.tidal_sync_enabled = True
        test_event.tidal_collection_bidirectional = True
        db.commit()

        req = SongRequest(
            event_id=test_event.id,
            song_title="Synced Track",
            artist="DJ Y",
            status=RequestStatus.NEW.value,
            dedupe_key="synced-track-dj-y",
            submitted_during_collection=True,
            tidal_collection_track_id="tid-555",
        )
        db.add(req)
        db.commit()
        db.refresh(req)

        calls = []

        def mock_remove(*args, **kwargs):
            calls.append(args)

        import app.api.requests as requests_module

        monkeypatch.setattr(requests_module, "remove_track_from_collection_playlist", mock_remove)

        resp = client.patch(
            f"/api/requests/{req.id}",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(calls) == 1

    def test_rejecting_unsynced_collection_request_skips_tidal(
        self, client: TestClient, db: Session, auth_headers: dict, test_event: Event, monkeypatch
    ):
        """Rejecting a collection request with no tidal_collection_track_id skips removal."""
        from app.models.request import Request as SongRequest
        from app.models.request import RequestStatus

        test_event.tidal_sync_enabled = True
        test_event.tidal_collection_bidirectional = True
        db.commit()

        req = SongRequest(
            event_id=test_event.id,
            song_title="Unsynced Track",
            artist="DJ Z",
            status=RequestStatus.NEW.value,
            dedupe_key="unsynced-track-dj-z",
            submitted_during_collection=True,
            tidal_collection_track_id=None,
        )
        db.add(req)
        db.commit()
        db.refresh(req)

        calls = []

        def mock_remove(*args, **kwargs):
            calls.append(args)

        import app.api.requests as requests_module

        monkeypatch.setattr(requests_module, "remove_track_from_collection_playlist", mock_remove)

        resp = client.patch(
            f"/api/requests/{req.id}",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(calls) == 0

    def test_rejecting_synced_request_skips_tidal_when_bidirectional_disabled(
        self, client: TestClient, db: Session, auth_headers: dict, test_event: Event, monkeypatch
    ):
        """Rejection must NOT remove from Tidal when bidirectional sync is off (the default)."""
        from app.models.request import Request as SongRequest
        from app.models.request import RequestStatus

        test_event.tidal_sync_enabled = True
        test_event.tidal_collection_bidirectional = False  # explicit default
        db.commit()

        req = SongRequest(
            event_id=test_event.id,
            song_title="Guarded Track",
            artist="DJ Guard",
            status=RequestStatus.NEW.value,
            dedupe_key="guarded-track-dj-guard",
            submitted_during_collection=True,
            tidal_collection_track_id="tid-777",
        )
        db.add(req)
        db.commit()
        db.refresh(req)

        calls = []

        def mock_remove(*args, **kwargs):
            calls.append(args)

        import app.api.requests as requests_module

        monkeypatch.setattr(requests_module, "remove_track_from_collection_playlist", mock_remove)

        resp = client.patch(
            f"/api/requests/{req.id}",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(calls) == 0, "Tidal removal must not fire when bidirectional sync is disabled"

"""Tests for sync_results_json exposure in API responses."""

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus


class TestGetEventRequestsIncludesSyncFields:
    """GET /api/events/{code}/requests should return sync fields."""

    def test_includes_sync_results_json(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_event: Event,
        db: Session,
    ):
        """sync_results_json should be included in request responses."""
        sync_data = json.dumps(
            [
                {
                    "service": "tidal",
                    "status": "added",
                    "track_id": "123",
                    "track_title": "Strobe",
                    "track_artist": "deadmau5",
                    "confidence": 0.95,
                    "url": "https://tidal.com/track/123",
                    "duration_seconds": 300,
                    "playlist_id": "playlist_abc",
                    "error": None,
                }
            ]
        )
        request = Request(
            event_id=test_event.id,
            song_title="Strobe",
            artist="deadmau5",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="sync_expose_test_1",
            raw_search_query="deadmau5 Strobe",
            sync_results_json=sync_data,
        )
        db.add(request)
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        req = data[0]
        assert req["sync_results_json"] == sync_data
        assert req["raw_search_query"] == "deadmau5 Strobe"

    def test_null_sync_fields(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_event: Event,
        db: Session,
    ):
        """Null sync fields should be returned as null."""
        request = Request(
            event_id=test_event.id,
            song_title="Unknown",
            artist="Nobody",
            source="manual",
            status=RequestStatus.NEW.value,
            dedupe_key="sync_expose_test_2",
        )
        db.add(request)
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert response.status_code == 200
        req = response.json()[0]
        assert req["sync_results_json"] is None
        assert req["raw_search_query"] is None


class TestUpdateRequestIncludesSyncResultsJson:
    """PATCH /api/requests/{id} should return sync_results_json."""

    def test_update_includes_sync_results_json(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_event: Event,
        db: Session,
    ):
        """Updated request response includes sync_results_json and raw_search_query."""
        sync_data = json.dumps([{"service": "tidal", "status": "not_found"}])
        request = Request(
            event_id=test_event.id,
            song_title="Rare Track",
            artist="Unknown",
            source="manual",
            status=RequestStatus.NEW.value,
            dedupe_key="sync_expose_test_3",
            raw_search_query="Unknown Rare Track",
            sync_results_json=sync_data,
        )
        db.add(request)
        db.commit()

        response = client.patch(
            f"/api/requests/{request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["sync_results_json"] == sync_data
        assert data["raw_search_query"] == "Unknown Rare Track"


class TestPersistSyncResultIncludesUrlAndDuration:
    """_persist_sync_result should include url and duration_seconds in JSON."""

    def test_url_and_duration_persisted(self, db: Session):
        from app.services.sync.base import SyncResult, SyncStatus, TrackMatch
        from app.services.sync.orchestrator import _persist_sync_result

        event = Event(
            code="ENRICH",
            join_code="UY238A",
            name="Enrich Test",
            created_by_user_id=1,
            expires_at=datetime.now(UTC) + timedelta(hours=6),
        )
        db.add(event)
        db.flush()

        request = Request(
            event_id=event.id,
            song_title="Strobe",
            artist="deadmau5",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="enrich_test_1",
        )
        db.add(request)
        db.flush()

        result = SyncResult(
            service="tidal",
            status=SyncStatus.ADDED,
            track_match=TrackMatch(
                service="tidal",
                track_id="456",
                title="Strobe",
                artist="deadmau5",
                match_confidence=0.92,
                url="https://tidal.com/track/456",
                duration_seconds=612,
            ),
            playlist_id="playlist_xyz",
        )

        _persist_sync_result(request, result)

        data = json.loads(request.sync_results_json)
        assert len(data) == 1
        assert data[0]["url"] == "https://tidal.com/track/456"
        assert data[0]["duration_seconds"] == 612

    def test_url_and_duration_none_when_no_match(self, db: Session):
        from app.services.sync.base import SyncResult, SyncStatus
        from app.services.sync.orchestrator import _persist_sync_result

        event = Event(
            code="ENRICH2",
            join_code="FZ8V79",
            name="Enrich Test 2",
            created_by_user_id=1,
            expires_at=datetime.now(UTC) + timedelta(hours=6),
        )
        db.add(event)
        db.flush()

        request = Request(
            event_id=event.id,
            song_title="Missing",
            artist="Nobody",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="enrich_test_2",
        )
        db.add(request)
        db.flush()

        result = SyncResult(
            service="tidal",
            status=SyncStatus.NOT_FOUND,
        )

        _persist_sync_result(request, result)

        data = json.loads(request.sync_results_json)
        assert data[0]["url"] is None
        assert data[0]["duration_seconds"] is None

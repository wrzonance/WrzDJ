"""Song request endpoint tests grouped by behavior."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request


class TestSubmitRequest:
    """Tests for POST /api/events/{code}/requests endpoint."""

    def test_submit_request_success(self, client: TestClient, test_event: Event):
        """Test submitting a song request."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Test Artist",
                "title": "Test Song",
                "source": "spotify",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["artist"] == "Test Artist"
        assert data["song_title"] == "Test Song"
        assert data["status"] == "new"
        assert data["is_duplicate"] is False

    def test_submit_request_with_note(self, client: TestClient, test_event: Event):
        """Test submitting a request with a note."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Artist With Note",
                "title": "Song With Note",
                "source": "manual",
                "note": "Please play this for my birthday!",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["note"] == "Please play this for my birthday!"

    def test_submit_request_with_source_url(self, client: TestClient, test_event: Event):
        """Test submitting a request with source URL."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Spotify Artist",
                "title": "Spotify Song",
                "source": "spotify",
                "source_url": "https://open.spotify.com/track/abc123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["source_url"] == "https://open.spotify.com/track/abc123"

    def test_submit_request_with_beatport_source(self, client: TestClient, test_event: Event):
        """Regression: beatport source must be accepted (used by recommendation accept-all)."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Beatport Artist",
                "title": "Beatport Track",
                "source": "beatport",
                "source_url": "https://www.beatport.com/track/slug/12345",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "beatport"
        assert data["artist"] == "Beatport Artist"

    def test_submit_request_duplicate(self, client: TestClient, test_event: Event):
        """Test submitting a duplicate request."""
        # First request
        client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Dupe Artist", "title": "Dupe Song", "source": "manual"},
        )
        # Second request with same artist/title
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Dupe Artist", "title": "Dupe Song", "source": "manual"},
        )
        assert response.status_code == 200
        assert response.json()["is_duplicate"] is True

    def test_submit_request_event_not_found(self, client: TestClient):
        """Test submitting to nonexistent event."""
        response = client.post(
            "/api/events/NOTFOUND/requests",
            json={"artist": "Artist", "title": "Song", "source": "manual"},
        )
        assert response.status_code == 404

    def test_submit_request_missing_fields(self, client: TestClient, test_event: Event):
        """Test submitting request with missing required fields."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Only Artist"},
        )
        assert response.status_code == 422

    def test_submit_request_with_metadata(self, client: TestClient, test_event: Event):
        """Test submitting a request with genre/bpm/key metadata."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "DJ Pierre",
                "title": "Acid Phase",
                "source": "spotify",
                "genre": "Acid House",
                "bpm": 126,
                "musical_key": "F Minor",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["genre"] == "Acid House"
        assert data["bpm"] == 126.0
        assert data["musical_key"] == "4A"  # F Minor -> 4A in Camelot

    def test_submit_request_metadata_optional(self, client: TestClient, test_event: Event):
        """Test that metadata fields are optional and default to null."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Plain Artist", "title": "Plain Song"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["genre"] is None
        assert data["bpm"] is None
        assert data["musical_key"] is None

    def test_submit_request_key_normalization(self, client: TestClient, test_event: Event):
        """Test that musical key is normalized to Camelot notation."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Artist",
                "title": "Key Test",
                "musical_key": "D Minor",
            },
        )
        assert response.status_code == 200
        assert response.json()["musical_key"] == "7A"

    def test_submit_request_bpm_validation(self, client: TestClient, test_event: Event):
        """Test BPM validation boundaries."""
        # BPM too low
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "A", "title": "T", "bpm": 0},
        )
        assert response.status_code == 422

        # BPM too high
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "A", "title": "T", "bpm": 1000},
        )
        assert response.status_code == 422


def test_live_submit_persists_guest_id_from_cookie(client, test_event, db):
    """F1 regression: events.py submit_request() must capture guest_id from
    the wrzdj_guest cookie and persist it on the Request row.

    Before the fix, every live-event request was stored with guest_id=NULL.
    """
    from app.models.request import Request as SongRequest

    identify_resp = client.post(
        "/api/public/guest/identify",
        json={
            "fingerprint_hash": "fp_test_live_submit",
            "fingerprint_components": {"screen": "1170x2532"},
        },
    )
    assert identify_resp.status_code == 200
    guest_id = identify_resp.json()["guest_id"]

    submit_resp = client.post(
        f"/api/events/{test_event.code}/requests",
        json={
            "artist": "Test Artist",
            "title": "Test Song",
            "source": "manual",
        },
    )
    assert submit_resp.status_code == 200, submit_resp.json()
    request_id = submit_resp.json()["id"]

    row = db.query(SongRequest).filter(SongRequest.id == request_id).first()
    assert row is not None
    assert row.guest_id == guest_id, (
        f"Expected guest_id={guest_id} on persisted request, got {row.guest_id}"
    )


class TestSubmitRequestCollectionFlag:
    """The /join entry point and /collect entry point must produce equivalent
    rows during collection phase — otherwise /join submissions are invisible
    in the collect leaderboard.
    """

    def _enable_collection(self, db: Session, event: Event) -> None:
        from datetime import timedelta

        from app.core.time import utcnow

        now = utcnow()
        event.collection_opens_at = now - timedelta(hours=1)
        event.live_starts_at = now + timedelta(hours=1)
        db.commit()
        db.refresh(event)

    def test_submit_via_join_during_collection_flags_row(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """POST /api/events/{code}/requests during collection phase MUST set
        submitted_during_collection=True so the collect leaderboard sees it.
        """
        self._enable_collection(db, test_event)
        resp = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Nine Inch Nails",
                "title": "All The Love In The World",
                "source": "manual",
            },
        )
        assert resp.status_code == 200, resp.json()
        row = db.query(Request).filter(Request.id == resp.json()["id"]).one()
        assert row.submitted_during_collection is True, (
            "join-flow submissions during collection must be flagged so the "
            "collect leaderboard surfaces them"
        )

    def test_submit_via_join_during_live_does_not_flag_row(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """During live phase, submissions must NOT be flagged as collection."""
        # Default test_event has no collection_opens_at / live_starts_at,
        # so phase computes to "live".
        resp = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Live Artist",
                "title": "Live Song",
                "source": "manual",
            },
        )
        assert resp.status_code == 200
        row = db.query(Request).filter(Request.id == resp.json()["id"]).one()
        assert row.submitted_during_collection is False

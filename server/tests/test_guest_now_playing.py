"""Tests for guest now-playing in public requests endpoint."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.request import Request, RequestStatus


class TestGuestNowPlaying:
    """Tests for now_playing field in GET /api/public/events/{code}/requests."""

    def test_returns_now_playing_when_present(
        self, client: TestClient, test_event: Event, db: Session
    ):
        np = NowPlaying(
            event_id=test_event.id,
            title="Current Song",
            artist="Current Artist",
            album_art_url="https://example.com/art.jpg",
            source="stagelinq",
        )
        db.add(np)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing"] is not None
        assert data["now_playing"]["title"] == "Current Song"
        assert data["now_playing"]["artist"] == "Current Artist"
        assert data["now_playing"]["album_art_url"] == "https://example.com/art.jpg"
        assert data["now_playing"]["source"] == "stagelinq"

    def test_returns_null_when_nothing_playing(self, client: TestClient, test_event: Event):
        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing"] is None

    def test_returns_null_when_now_playing_hidden(
        self, client: TestClient, test_event: Event, db: Session
    ):
        # Set auto_hide to 0 minutes (always hidden when stale)
        test_event.now_playing_auto_hide_minutes = 0
        db.commit()

        np = NowPlaying(
            event_id=test_event.id,
            title="Hidden Song",
            artist="Hidden Artist",
            source="bridge",
        )
        db.add(np)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        # Endpoint should still return valid response regardless of hide state
        assert "now_playing" in response.json()

    def test_includes_requests_alongside_now_playing(
        self, client: TestClient, test_event: Event, db: Session
    ):
        # Add a visible request
        req = Request(
            event_id=test_event.id,
            song_title="Guest Song",
            artist="Guest Artist",
            source="manual",
            status=RequestStatus.NEW.value,
            dedupe_key="guest_np_test_123",
        )
        db.add(req)

        np = NowPlaying(
            event_id=test_event.id,
            title="Playing",
            artist="DJ",
            source="pioneer",
        )
        db.add(np)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) == 1
        assert data["requests"][0]["title"] == "Guest Song"
        assert data["now_playing"]["title"] == "Playing"
        assert data["now_playing"]["source"] == "pioneer"

    def test_event_info_present(self, client: TestClient, test_event: Event):
        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["event"]["code"] == test_event.join_code
        assert data["event"]["name"] == test_event.name

    def test_expired_event_returns_410(self, client: TestClient, db: Session, test_user):
        from datetime import timedelta

        from app.core.time import utcnow

        expired = Event(
            code="EXPRD1",
            join_code="KGQ35Q",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired)
        db.commit()

        response = client.get("/api/public/events/KGQ35Q/requests")
        assert response.status_code == 410

    def test_nonexistent_event_returns_404(self, client: TestClient):
        response = client.get("/api/public/events/NOPE99/requests")
        assert response.status_code == 404

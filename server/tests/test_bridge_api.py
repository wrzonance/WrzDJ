"""Integration tests for bridge API endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.play_history import PlayHistory
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.auth import get_password_hash


class TestGetBridgeApiKey:
    """Tests for GET /api/bridge/apikey endpoint (JWT-protected)."""

    def test_returns_401_without_jwt(self, client: TestClient):
        """Returns 401 when no Authorization header is provided."""
        response = client.get("/api/bridge/apikey")
        assert response.status_code == 401

    @patch("app.api.bridge.get_settings")
    def test_returns_api_key_with_admin_jwt(
        self, mock_settings, client: TestClient, admin_headers: dict
    ):
        """Returns the bridge API key for admin users."""
        mock_settings.return_value.bridge_api_key = "my-secret-bridge-key"

        response = client.get("/api/bridge/apikey", headers=admin_headers)
        assert response.status_code == 200
        assert response.json() == {"bridge_api_key": "my-secret-bridge-key"}

    def test_returns_403_for_non_admin(self, client: TestClient, auth_headers: dict):
        """Returns 403 when a non-admin user tries to get the API key."""
        response = client.get("/api/bridge/apikey", headers=auth_headers)
        assert response.status_code == 403

    @patch("app.api.bridge.get_settings")
    def test_returns_503_when_key_not_configured(
        self, mock_settings, client: TestClient, admin_headers: dict
    ):
        """Returns 503 when BRIDGE_API_KEY is not set on the server."""
        mock_settings.return_value.bridge_api_key = ""

        response = client.get("/api/bridge/apikey", headers=admin_headers)
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        password_hash=get_password_hash("testpassword123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_event(db: Session, test_user: User) -> Event:
    """Create a test event."""
    event = Event(
        code="TEST01",
        join_code="UG4BHD",
        name="Test Event",
        created_by_user_id=test_user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def expired_event(db: Session, test_user: User) -> Event:
    """Create an expired event."""
    event = Event(
        code="EXPIRE",
        join_code="2ZZN6B",
        name="Expired Event",
        created_by_user_id=test_user.id,
        expires_at=utcnow() - timedelta(hours=1),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def bridge_headers() -> dict:
    """Get bridge API key headers."""
    return {"X-Bridge-API-Key": "test-bridge-key"}


class TestBridgeAuth:
    """Tests for bridge API key authentication."""

    def test_missing_api_key(self, client: TestClient, test_event: Event):
        """Returns 422 when API key header missing."""
        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Test", "artist": "Test"},
        )
        assert response.status_code == 422

    @patch("app.core.bridge_auth.get_settings")
    def test_invalid_api_key(self, mock_settings, client: TestClient, test_event: Event):
        """Returns 401 for invalid API key."""
        mock_settings.return_value.bridge_api_key = "correct-key"

        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Test", "artist": "Test"},
            headers={"X-Bridge-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    @patch("app.core.bridge_auth.get_settings")
    def test_unconfigured_api_key(self, mock_settings, client: TestClient, test_event: Event):
        """Returns 401 when API key not configured on server (consistent with invalid key)."""
        mock_settings.return_value.bridge_api_key = ""

        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Test", "artist": "Test"},
            headers={"X-Bridge-API-Key": "any-key"},
        )
        # Returns 401 (same as invalid) to prevent enumeration
        assert response.status_code == 401


class TestPostNowPlaying:
    """Tests for POST /api/bridge/nowplaying endpoint."""

    @patch("app.core.bridge_auth.get_settings")
    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_creates_now_playing(
        self, mock_spotify, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Creates a now_playing record."""
        mock_settings.return_value.bridge_api_key = "test-key"
        mock_spotify.return_value = None

        response = client.post(
            "/api/bridge/nowplaying",
            json={
                "event_code": "TEST01",
                "title": "Blue Monday",
                "artist": "New Order",
                "album": "Power, Corruption & Lies",
                "deck": "1",
            },
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        # Verify in database
        now_playing = db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first()
        assert now_playing is not None
        assert now_playing.title == "Blue Monday"
        assert now_playing.artist == "New Order"
        assert now_playing.album == "Power, Corruption & Lies"
        assert now_playing.deck == "1"
        assert now_playing.source == "bridge"

    @patch("app.core.bridge_auth.get_settings")
    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_archives_previous_track(
        self, mock_spotify, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Archives previous track to history."""
        mock_settings.return_value.bridge_api_key = "test-key"
        mock_spotify.return_value = None

        # First track
        client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "First", "artist": "Artist"},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        # Second track
        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Second", "artist": "Artist"},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 200

        # Check history
        history = db.query(PlayHistory).filter(PlayHistory.event_id == test_event.id).all()
        assert len(history) == 1
        assert history[0].title == "First"
        assert history[0].ended_at is not None

    @patch("app.core.bridge_auth.get_settings")
    def test_event_not_found(self, mock_settings, client: TestClient):
        """Returns 404 for non-existent event."""
        mock_settings.return_value.bridge_api_key = "test-key"

        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "INVALID", "title": "Test", "artist": "Test"},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 404

    @patch("app.core.bridge_auth.get_settings")
    def test_validation_errors(self, mock_settings, client: TestClient, test_event: Event):
        """Returns 422 for validation errors."""
        mock_settings.return_value.bridge_api_key = "test-key"

        # Missing required field
        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Test"},  # Missing artist
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 422


class TestPostBridgeStatus:
    """Tests for POST /api/bridge/status endpoint."""

    @patch("app.core.bridge_auth.get_settings")
    def test_updates_status_connected(
        self, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Updates bridge status to connected."""
        mock_settings.return_value.bridge_api_key = "test-key"

        response = client.post(
            "/api/bridge/status",
            json={"event_code": "TEST01", "connected": True, "device_name": "SC6000"},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        now_playing = db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first()
        assert now_playing.bridge_connected is True
        assert now_playing.bridge_device_name == "SC6000"

    @patch("app.core.bridge_auth.get_settings")
    def test_updates_status_disconnected(
        self, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Updates bridge status to disconnected."""
        mock_settings.return_value.bridge_api_key = "test-key"

        response = client.post(
            "/api/bridge/status",
            json={"event_code": "TEST01", "connected": False},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 200

        now_playing = db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first()
        assert now_playing.bridge_connected is False


class TestDeleteNowPlaying:
    """Tests for DELETE /api/bridge/nowplaying/{code} endpoint."""

    @patch("app.core.bridge_auth.get_settings")
    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_clears_now_playing(
        self, mock_spotify, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Clears now_playing and archives to history."""
        mock_settings.return_value.bridge_api_key = "test-key"
        mock_spotify.return_value = None

        # Set up now_playing
        client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Test Track", "artist": "Test Artist"},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        # Clear it
        response = client.delete(
            "/api/bridge/nowplaying/TEST01",
            headers={"X-Bridge-API-Key": "test-key"},
        )

        assert response.status_code == 200

        # Check now_playing is cleared
        now_playing = db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first()
        assert now_playing.title == ""

        # Check history
        history = db.query(PlayHistory).filter(PlayHistory.event_id == test_event.id).all()
        assert len(history) == 1
        assert history[0].title == "Test Track"


class TestGetPublicNowPlaying:
    """Tests for GET /api/public/e/{code}/nowplaying endpoint."""

    @patch("app.services.now_playing.lookup_spotify_album_art")
    @patch("app.core.bridge_auth.get_settings")
    def test_returns_now_playing(
        self, mock_settings, mock_spotify, client: TestClient, test_event: Event, db: Session
    ):
        """Returns current now_playing data."""
        mock_settings.return_value.bridge_api_key = "test-key"
        mock_spotify.return_value = {
            "spotify_track_id": "sp123",
            "album_art_url": "https://example.com/art.jpg",
            "spotify_uri": "spotify:track:sp123",
        }

        # Set up now_playing
        client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Test Track", "artist": "Test Artist"},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        # Get public now_playing
        response = client.get("/api/public/e/UG4BHD/nowplaying")

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Track"
        assert data["artist"] == "Test Artist"
        assert data["source"] == "bridge"
        assert data["album_art_url"] == "https://example.com/art.jpg"

    def test_returns_null_when_empty(self, client: TestClient, test_event: Event):
        """Returns null when no track playing."""
        response = client.get("/api/public/e/UG4BHD/nowplaying")

        assert response.status_code == 200
        assert response.json() is None

    def test_event_not_found(self, client: TestClient):
        """Returns 404 for non-existent event."""
        response = client.get("/api/public/e/INVALID/nowplaying")
        assert response.status_code == 404

    def test_expired_event(self, client: TestClient, expired_event: Event):
        """Returns 410 for expired event."""
        response = client.get("/api/public/e/2ZZN6B/nowplaying")
        assert response.status_code == 410


class TestGetPublicBridgeStatus:
    """Tests for GET /api/public/e/{code}/bridge-status endpoint.

    This endpoint resolves by join_code (post PR #324 / #328 routing migration)
    because it serves the kiosk display + OBS overlay public pages.
    """

    def test_returns_default_status_when_no_now_playing(
        self, client: TestClient, test_event: Event
    ):
        """Returns default (disconnected) status when no track has ever played."""
        response = client.get("/api/public/e/UG4BHD/bridge-status")
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["device_name"] is None

    def test_event_not_found(self, client: TestClient):
        """Returns 404 for an unknown event code."""
        response = client.get("/api/public/e/INVALID/bridge-status")
        assert response.status_code == 404

    def test_collection_code_is_rejected(self, client: TestClient, test_event: Event):
        """Locks in the join_code routing contract: passing the collection
        code must 404. Prevents accidental regression to the pre-PR-#328
        get_event_by_code_with_status resolver."""
        response = client.get(f"/api/public/e/{test_event.code}/bridge-status")
        assert response.status_code == 404

    def test_expired_event(self, client: TestClient, expired_event: Event):
        """Returns 410 for an expired event (resolved via join_code)."""
        response = client.get("/api/public/e/2ZZN6B/bridge-status")
        assert response.status_code == 410


class TestGetPublicHistory:
    """Tests for GET /api/public/e/{code}/history endpoint."""

    def test_returns_empty_history(self, client: TestClient, test_event: Event):
        """Returns empty history."""
        response = client.get("/api/public/e/UG4BHD/history")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_returns_history(self, client: TestClient, test_event: Event, db: Session):
        """Returns play history."""
        # Add some history
        for i in range(5):
            history = PlayHistory(
                event_id=test_event.id,
                title=f"Track {i + 1}",
                artist="Artist",
                started_at=utcnow(),
                play_order=i + 1,
            )
            db.add(history)
        db.commit()

        response = client.get("/api/public/e/UG4BHD/history")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5
        assert data["items"][0]["title"] == "Track 5"  # Newest first

    def test_pagination(self, client: TestClient, test_event: Event, db: Session):
        """Supports pagination parameters."""
        # Add history
        for i in range(10):
            history = PlayHistory(
                event_id=test_event.id,
                title=f"Track {i + 1}",
                artist="Artist",
                started_at=utcnow(),
                play_order=i + 1,
            )
            db.add(history)
        db.commit()

        response = client.get("/api/public/e/UG4BHD/history?limit=3&offset=3")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert len(data["items"]) == 3

    def test_limit_capped(self, client: TestClient, test_event: Event):
        """Limit is capped at 100 via Query validation."""
        response = client.get("/api/public/e/UG4BHD/history?limit=200")
        assert response.status_code == 422  # FastAPI rejects limit > 100

        # Valid limit at the boundary works
        response = client.get("/api/public/e/UG4BHD/history?limit=100")
        assert response.status_code == 200

    def test_event_not_found(self, client: TestClient):
        """Returns 404 for non-existent event."""
        response = client.get("/api/public/e/INVALID/history")
        assert response.status_code == 404

    def test_expired_event(self, client: TestClient, expired_event: Event):
        """Returns 410 for expired event."""
        response = client.get("/api/public/e/2ZZN6B/history")
        assert response.status_code == 410


class TestRequestAutoMatch:
    """Tests for automatic request matching flow."""

    @patch("app.core.bridge_auth.get_settings")
    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_full_request_flow(
        self, mock_spotify, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Tests full flow: accept request → play matching track → next track."""
        mock_settings.return_value.bridge_api_key = "test-key"
        mock_spotify.return_value = None

        # Create an accepted request
        request = Request(
            event_id=test_event.id,
            song_title="Blue Monday",
            artist="New Order",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="blue_monday_new_order",
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        request_id = request.id

        # Play matching track via bridge
        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Blue Monday", "artist": "New Order"},
            headers={"X-Bridge-API-Key": "test-key"},
        )
        assert response.status_code == 200

        # Check request is now "playing"
        db.refresh(request)
        assert request.status == RequestStatus.PLAYING.value

        # Play next track
        response = client.post(
            "/api/bridge/nowplaying",
            json={"event_code": "TEST01", "title": "Sandstorm", "artist": "Darude"},
            headers={"X-Bridge-API-Key": "test-key"},
        )
        assert response.status_code == 200

        # Check request is now "played"
        db.refresh(request)
        assert request.status == RequestStatus.PLAYED.value

        # Check history has the matched request link
        history = db.query(PlayHistory).filter(PlayHistory.title == "Blue Monday").first()
        assert history is not None
        assert history.matched_request_id == request_id

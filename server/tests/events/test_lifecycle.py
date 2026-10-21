"""Event API tests grouped by behavior."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User


class TestCreateEvent:
    """Tests for POST /api/events endpoint."""

    def test_create_event_success(self, client: TestClient, auth_headers: dict):
        """Test creating an event succeeds."""
        response = client.post(
            "/api/events",
            json={"name": "My DJ Set", "expires_hours": 4},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My DJ Set"
        assert "code" in data
        assert len(data["code"]) == 6
        assert data["is_active"] is True

    def test_create_event_no_auth(self, client: TestClient):
        """Test creating an event without auth fails."""
        response = client.post(
            "/api/events",
            json={"name": "My DJ Set"},
        )
        assert response.status_code == 401

    def test_create_event_default_expiry(self, client: TestClient, auth_headers: dict):
        """Test creating an event with default expiry."""
        response = client.post(
            "/api/events",
            json={"name": "Default Expiry Event"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        # Default is 6 hours
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        assert expires_at > datetime.now(expires_at.tzinfo)


class TestListEvents:
    """Tests for GET /api/events endpoint."""

    def test_list_events_empty(self, client: TestClient, auth_headers: dict):
        """Test listing events when none exist."""
        response = client.get("/api/events", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_events_with_event(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test listing events returns user's events."""
        response = client.get("/api/events", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["code"] == test_event.code

    def test_list_events_no_auth(self, client: TestClient):
        """Test listing events without auth fails."""
        response = client.get("/api/events")
        assert response.status_code == 401


class TestGetEvent:
    """Tests for GET /api/events/{code} endpoint."""

    def test_get_event_success(self, client: TestClient, test_event: Event, auth_headers: dict):
        """Test getting an event by code."""
        response = client.get(f"/api/events/{test_event.code}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == test_event.code
        assert data["name"] == test_event.name

    def test_get_event_not_found(self, client: TestClient, auth_headers: dict):
        """Test getting a nonexistent event returns 404."""
        response = client.get("/api/events/NOTFND", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["detail"]


class TestUpdateEvent:
    """Tests for PATCH /api/events/{code} endpoint."""

    def test_update_event_name(self, client: TestClient, auth_headers: dict, test_event: Event):
        """Test updating event name."""
        response = client.patch(
            f"/api/events/{test_event.code}",
            json={"name": "Updated Name"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_update_event_expiry(self, client: TestClient, auth_headers: dict, test_event: Event):
        """Test updating event expiry."""
        new_expiry = (utcnow() + timedelta(hours=12)).isoformat()
        response = client.patch(
            f"/api/events/{test_event.code}",
            json={"expires_at": new_expiry},
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_update_event_no_auth(self, client: TestClient, test_event: Event):
        """Test updating event without auth fails."""
        response = client.patch(
            f"/api/events/{test_event.code}",
            json={"name": "Hacked Name"},
        )
        assert response.status_code == 401


class TestDeleteEvent:
    """Tests for DELETE /api/events/{code} endpoint."""

    def test_delete_event_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test deleting an event."""
        response = client.delete(
            f"/api/events/{test_event.code}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        # Verify event is deleted
        event = db.query(Event).filter(Event.code == test_event.code).first()
        assert event is None

    def test_delete_event_with_associated_data(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test deleting an event that has requests, votes, play history, and now_playing."""
        from app.models.now_playing import NowPlaying
        from app.models.play_history import PlayHistory
        from app.models.request_vote import RequestVote

        # Create event
        event = Event(
            code="DELME1",
            join_code="Y9B853",
            name="Event With Data",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.flush()

        # Add requests
        req1 = Request(
            event_id=event.id,
            song_title="Stayin Alive",
            artist="Bee Gees",
            source="manual",
            status=RequestStatus.PLAYING.value,
            dedupe_key="delme_dedupe_1",
        )
        req2 = Request(
            event_id=event.id,
            song_title="The End",
            artist="The Doors",
            source="manual",
            status=RequestStatus.PLAYED.value,
            dedupe_key="delme_dedupe_2",
        )
        db.add_all([req1, req2])
        db.flush()

        # Add votes on requests
        vote = RequestVote(
            request_id=req1.id,
        )
        db.add(vote)

        # Add now_playing record
        now_playing = NowPlaying(
            event_id=event.id,
            title="Stayin Alive",
            artist="Bee Gees",
            matched_request_id=req1.id,
            source="stagelinq",
        )
        db.add(now_playing)

        # Add play history
        play_entry = PlayHistory(
            event_id=event.id,
            title="The End",
            artist="The Doors",
            source="manual",
            matched_request_id=req2.id,
            started_at=utcnow(),
            play_order=1,
        )
        db.add(play_entry)
        db.commit()

        # Capture IDs before deletion (objects become stale after delete)
        event_id = event.id
        req1_id = req1.id

        # Delete should succeed (was 500 before fix)
        response = client.delete(
            f"/api/events/{event.code}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        # Expire session to force fresh reads from DB
        db.expire_all()

        # Verify everything is deleted
        assert db.query(Event).filter(Event.id == event_id).first() is None
        assert db.query(Request).filter(Request.event_id == event_id).all() == []
        assert db.query(NowPlaying).filter(NowPlaying.event_id == event_id).first() is None
        assert db.query(PlayHistory).filter(PlayHistory.event_id == event_id).all() == []
        assert db.query(RequestVote).filter(RequestVote.request_id == req1_id).all() == []

    def test_delete_event_no_auth(self, client: TestClient, test_event: Event):
        """Test deleting event without auth fails."""
        response = client.delete(f"/api/events/{test_event.code}")
        assert response.status_code == 401

    def test_delete_event_not_found(self, client: TestClient, auth_headers: dict):
        """Test deleting nonexistent event."""
        response = client.delete(
            "/api/events/NOTFND",
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestExpiredEvents:
    """Tests for expired event handling with 410 Gone status."""

    def test_get_expired_event_returns_410(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test that getting an expired event returns 410 Gone."""
        # Create an expired event
        expired_event = Event(
            code="EXPIR1",
            join_code="DL347H",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(f"/api/events/{expired_event.code}", headers=auth_headers)
        assert response.status_code == 410
        assert response.json()["detail"]

    def test_submit_request_to_expired_event_returns_410(
        self, client: TestClient, db: Session, test_user: User
    ):
        """Test that submitting a request to expired event returns 410."""
        expired_event = Event(
            code="EXPIR2",
            join_code="SMFZUG",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.post(
            f"/api/events/{expired_event.code}/requests",
            json={"artist": "Test Artist", "title": "Test Song"},
        )
        assert response.status_code == 410
        assert response.json()["detail"]

    def test_owner_can_view_requests_for_expired_event(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test that owner can still view requests for expired events."""
        expired_event = Event(
            code="EXPIR3",
            join_code="TKFJBW",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(
            f"/api/events/{expired_event.code}/requests",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_kiosk_display_expired_event_returns_410(
        self, client: TestClient, db: Session, test_user: User
    ):
        """Test that kiosk display for expired event returns 410."""
        expired_event = Event(
            code="EXPIR4",
            join_code="WTBZJZ",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(f"/api/public/events/{expired_event.join_code}/display")
        assert response.status_code == 410
        assert response.json()["detail"]

    def test_404_vs_410_distinction(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test that 404 is for not found and 410 is for expired."""
        # Non-existent event should be 404
        response = client.get("/api/events/NOEXST", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["detail"]

        # Expired event should be 410
        expired_event = Event(
            code="EXPIR5",
            join_code="WV769S",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(f"/api/events/{expired_event.code}", headers=auth_headers)
        assert response.status_code == 410
        assert response.json()["detail"]


class TestArchiveEvents:
    """Tests for event archiving functionality."""

    def test_archive_event_success(self, client: TestClient, auth_headers: dict, test_event: Event):
        """Test archiving an event."""
        response = client.post(
            f"/api/events/{test_event.code}/archive",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["archived_at"] is not None
        assert data["status"] == "archived"

    def test_archive_event_no_auth(self, client: TestClient, test_event: Event):
        """Test archiving without auth fails."""
        response = client.post(f"/api/events/{test_event.code}/archive")
        assert response.status_code == 401

    def test_archive_already_archived_event(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test archiving an already archived event returns 400."""
        test_event.archived_at = utcnow()
        db.commit()

        response = client.post(
            f"/api/events/{test_event.code}/archive",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]

    def test_unarchive_event_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test unarchiving an event."""
        # First archive it
        test_event.archived_at = utcnow()
        db.commit()

        response = client.post(
            f"/api/events/{test_event.code}/unarchive",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["archived_at"] is None

    def test_unarchive_not_archived_event(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test unarchiving a non-archived event returns 400."""
        response = client.post(
            f"/api/events/{test_event.code}/unarchive",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"]

    def test_get_archived_event_returns_410(
        self, client: TestClient, test_event: Event, db: Session, auth_headers: dict
    ):
        """Test that getting an archived event returns 410."""
        test_event.archived_at = utcnow()
        db.commit()

        response = client.get(f"/api/events/{test_event.code}", headers=auth_headers)
        assert response.status_code == 410
        assert response.json()["detail"]

    def test_submit_request_to_archived_event_returns_410(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that submitting to archived event returns 410."""
        test_event.archived_at = utcnow()
        db.commit()

        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Test Artist", "title": "Test Song"},
        )
        assert response.status_code == 410
        assert response.json()["detail"]

    def test_list_archived_events(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test listing archived and expired events."""
        # Create an archived event
        archived_event = Event(
            code="ARCHV1",
            join_code="JJ7MLN",
            name="Archived Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(archived_event)

        # Create an expired event
        expired_event = Event(
            code="EXPRD1",
            join_code="KGQ35Q",
            name="Expired Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get("/api/events/archived", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Should have both archived and expired events
        assert len(data) == 2
        codes = [e["code"] for e in data]
        assert "ARCHV1" in codes
        assert "EXPRD1" in codes

        # Verify status fields
        for event in data:
            assert event["status"] in ["archived", "expired"]
            assert "request_count" in event

    def test_archived_events_include_request_count(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that archived events listing includes request counts."""
        # Create an archived event with requests
        archived_event = Event(
            code="ARCHV2",
            join_code="D44QZS",
            name="Archived With Requests",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(archived_event)
        db.flush()

        # Add some requests
        for i in range(3):
            req = Request(
                event_id=archived_event.id,
                song_title=f"Song {i}",
                artist="Artist",
                source="manual",
                status=RequestStatus.NEW.value,
                dedupe_key=f"dedupe_key_{i}",
            )
            db.add(req)
        db.commit()

        response = client.get("/api/events/archived", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        archived = next(e for e in data if e["code"] == "ARCHV2")
        assert archived["request_count"] == 3

"""Tests for event endpoints."""

from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.schemas.search import SearchResult
from app.services.auth import get_password_hash


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


class TestCsvExport:
    """Tests for CSV export functionality."""

    def test_export_csv_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test exporting event requests as CSV."""
        # Add a request to the event
        req = Request(
            event_id=test_event.id,
            song_title="Export Test Song",
            artist="Export Artist",
            source="manual",
            status=RequestStatus.NEW.value,
            note="Test note",
            dedupe_key="export_dedupe_key_123",
        )
        db.add(req)
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert test_event.code in response.headers["content-disposition"]

        # Verify CSV content
        content = response.text
        assert "Request ID" in content
        assert "Song Title" in content
        assert "Export Test Song" in content
        assert "Export Artist" in content
        assert "Test note" in content

    def test_export_csv_no_auth(self, client: TestClient, test_event: Event):
        """Test exporting without auth fails."""
        response = client.get(f"/api/events/{test_event.code}/export/csv")
        assert response.status_code == 401

    def test_export_csv_not_owner(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test exporting event you don't own fails."""
        # Create another user and their event

        other_user = User(
            username="otheruser",
            password_hash=get_password_hash("otherpassword"),
        )
        db.add(other_user)
        db.flush()

        other_event = Event(
            code="OTHER1",
            join_code="WX8XQG",
            name="Other User Event",
            created_by_user_id=other_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(other_event)
        db.commit()

        response = client.get(
            f"/api/events/{other_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_export_csv_expired_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export CSV for expired events."""
        expired_event = Event(
            code="EXPCSV",
            join_code="8AQM9R",
            name="Expired CSV Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(
            f"/api/events/{expired_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_export_csv_archived_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export CSV for archived events."""
        archived_event = Event(
            code="ARCSV1",
            join_code="ZT548E",
            name="Archived CSV Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(archived_event)
        db.commit()

        response = client.get(
            f"/api/events/{archived_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_export_csv_empty_event(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test exporting an event with no requests."""
        response = client.get(
            f"/api/events/{test_event.code}/export/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content = response.text
        # Should have header row but no data rows
        assert "Request ID" in content
        lines = content.strip().split("\n")
        assert len(lines) == 1  # Just the header


class TestDisplaySettings:
    """Tests for display settings endpoints."""

    def test_get_display_settings_success(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test getting display settings."""
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "now_playing_hidden" in data

    def test_get_display_settings_no_auth(self, client: TestClient, test_event: Event):
        """Test getting display settings without auth fails."""
        response = client.get(f"/api/events/{test_event.code}/display-settings")
        assert response.status_code == 401

    def test_update_display_settings_hide(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test hiding now playing via display settings."""
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["now_playing_hidden"] is True

    def test_update_display_settings_show(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test showing now playing via display settings."""
        from app.models.now_playing import NowPlaying

        # First hide it
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            manual_hide_now_playing=True,
        )
        db.add(now_playing)
        db.commit()

        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["now_playing_hidden"] is False

        # Verify last_shown_at was updated
        db.refresh(now_playing)
        assert now_playing.last_shown_at is not None

    def test_update_display_settings_no_auth(self, client: TestClient, test_event: Event):
        """Test updating display settings without auth fails."""
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True},
        )
        assert response.status_code == 401

    def test_get_display_settings_returns_manual_setting_not_computed(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test GET display-settings returns manual hide setting, not computed state.

        When no track is playing but manual_hide is False, the endpoint should
        return now_playing_hidden=False (the DJ's intent), not True (the computed
        kiosk state that factors in empty title).
        """
        from app.models.now_playing import NowPlaying

        # Create a NowPlaying with empty title (no track) but manual_hide=False
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="",
            artist="",
            manual_hide_now_playing=False,
        )
        db.add(now_playing)
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should return the manual setting (False), not the computed state (True)
        assert data["now_playing_hidden"] is False

    def test_get_display_settings_hidden_persists_across_polls(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that toggling to hidden persists on subsequent GET calls.

        Regression test: previously the toggle would flip back on the next poll
        because GET returned the computed state instead of the manual setting.
        """
        # Toggle to hidden
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_hidden"] is True

        # Subsequent GET should still return hidden=True
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_hidden"] is True

    def test_get_display_settings_visible_persists_across_polls(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that toggling to visible persists on subsequent GET calls.

        Regression test: previously the toggle would flip back to hidden on the
        next poll when no track was playing.
        """
        # Toggle to hidden first, then to visible
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True},
            headers=auth_headers,
        )
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_hidden"] is False

        # Subsequent GET should still return hidden=False
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_hidden"] is False

    def test_get_display_settings_includes_auto_hide_minutes(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that GET display-settings includes auto_hide_minutes with default of 10."""
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing_auto_hide_minutes"] == 10

    def test_update_display_settings_auto_hide_minutes(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that PATCH persists auto_hide_minutes."""
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": False, "now_playing_auto_hide_minutes": 30},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing_auto_hide_minutes"] == 30

        # Verify it persists on GET
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_auto_hide_minutes"] == 30

    def test_update_display_settings_auto_hide_minutes_validation(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that auto_hide_minutes rejects 0 and 1441."""
        # 0 is below minimum (1)
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": False, "now_playing_auto_hide_minutes": 0},
            headers=auth_headers,
        )
        assert response.status_code == 422

        # 1441 is above maximum (1440)
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": False, "now_playing_auto_hide_minutes": 1441},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_update_display_settings_auto_hide_minutes_optional(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that omitting auto_hide_minutes doesn't change the value."""
        # First set it to a custom value
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": False, "now_playing_auto_hide_minutes": 30},
            headers=auth_headers,
        )

        # Then update only now_playing_hidden without auto_hide_minutes
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True},
            headers=auth_headers,
        )
        assert response.status_code == 200

        # auto_hide_minutes should still be 30
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_auto_hide_minutes"] == 30

    def test_update_auto_hide_only_does_not_change_hidden(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that PATCH with only auto_hide_minutes does not change now_playing_hidden.

        Regression test for multi-tab race: Tab A toggles visibility to hidden,
        Tab B saves auto-hide and should not silently undo the visibility change.
        """
        # Set hidden=True
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["now_playing_hidden"] is True

        # PATCH with only auto_hide_minutes (simulates Tab B saving auto-hide)
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_auto_hide_minutes": 5},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing_auto_hide_minutes"] == 5
        # Hidden should still be True — not reset by the auto-hide PATCH
        assert data["now_playing_hidden"] is True

    def test_kiosk_display_only_defaults_false(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that kiosk_display_only defaults to false."""
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["kiosk_display_only"] is False

    def test_update_kiosk_display_only(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test setting kiosk_display_only to true and verifying persistence."""
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"kiosk_display_only": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["kiosk_display_only"] is True

        # Verify it persists on GET
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["kiosk_display_only"] is True

    def test_kiosk_display_only_toggle_off(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test toggling kiosk_display_only back to false."""
        # Enable
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"kiosk_display_only": True},
            headers=auth_headers,
        )
        # Disable
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"kiosk_display_only": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["kiosk_display_only"] is False

    def test_kiosk_display_only_does_not_affect_other_settings(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that toggling kiosk_display_only doesn't change other display settings."""
        # Set some other settings first
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"now_playing_hidden": True, "now_playing_auto_hide_minutes": 20},
            headers=auth_headers,
        )

        # Toggle kiosk_display_only
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"kiosk_display_only": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["kiosk_display_only"] is True
        assert data["now_playing_hidden"] is True
        assert data["now_playing_auto_hide_minutes"] == 20

    def test_update_display_settings_not_owner(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test updating display settings for event you don't own fails."""

        other_user = User(
            username="otheruser_display",
            password_hash=get_password_hash("otherpassword"),
        )
        db.add(other_user)
        db.flush()

        other_event = Event(
            code="OTHER3",
            join_code="22LAZP",
            name="Other User Event",
            created_by_user_id=other_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(other_event)
        db.commit()

        response = client.patch(
            f"/api/events/{other_event.code}/display-settings",
            json={"now_playing_hidden": True},
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestRequestsOpen:
    """Tests for requests open/closed toggle."""

    def test_toggle_requests_open(self, client: TestClient, auth_headers: dict, test_event: Event):
        """Test PATCH requests_open to false returns requests_open: false."""
        response = client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"requests_open": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["requests_open"] is False

        # Verify it persists on GET
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["requests_open"] is False

    def test_submit_request_when_closed(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test submitting a request when requests are closed returns 403."""
        # Close requests
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"requests_open": False},
            headers=auth_headers,
        )

        # Try to submit a request
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Test Artist", "title": "Test Song"},
        )
        assert response.status_code == 403
        assert response.json()["detail"]

    def test_submit_request_when_reopened(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that closing then reopening requests allows submission."""
        # Close requests
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"requests_open": False},
            headers=auth_headers,
        )

        # Reopen requests
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"requests_open": True},
            headers=auth_headers,
        )

        # Submit should succeed
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Test Artist", "title": "Test Song"},
        )
        assert response.status_code == 200

    def test_kiosk_display_when_requests_closed(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test kiosk endpoint still returns 200 with requests_open: false."""
        # Close requests
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"requests_open": False},
            headers=auth_headers,
        )

        # Kiosk should still work (not 410)
        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["requests_open"] is False

    def test_requests_open_default_true(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that a new event has requests_open defaulting to true."""
        response = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["requests_open"] is True

        # Also check via EventOut
        response = client.get(f"/api/events/{test_event.code}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["requests_open"] is True


class TestKioskDisplayNowPlayingHidden:
    """Tests for now_playing_hidden field in kiosk display response."""

    def test_kiosk_display_includes_now_playing_hidden(self, client: TestClient, test_event: Event):
        """Test that kiosk display includes now_playing_hidden field."""
        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert "now_playing_hidden" in data

    def test_kiosk_display_hidden_when_manual_hide(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that kiosk display shows hidden when manual_hide is true."""
        from app.models.now_playing import NowPlaying

        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            manual_hide_now_playing=True,
        )
        db.add(now_playing)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing_hidden"] is True

    def test_kiosk_display_visible_when_track_playing(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that kiosk display shows visible when track is playing."""
        from app.models.now_playing import NowPlaying

        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow(),
            manual_hide_now_playing=False,
        )
        db.add(now_playing)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing_hidden"] is False


class TestKioskDisplayOnly:
    """Tests for kiosk_display_only in the public kiosk display endpoint."""

    def test_kiosk_display_includes_display_only_field(self, client: TestClient, test_event: Event):
        """Test that kiosk display response includes kiosk_display_only."""
        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert "kiosk_display_only" in data
        assert data["kiosk_display_only"] is False

    def test_kiosk_display_only_reflects_setting(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test that kiosk display endpoint reflects the display-only setting."""
        # Enable display-only mode
        client.patch(
            f"/api/events/{test_event.code}/display-settings",
            json={"kiosk_display_only": True},
            headers=auth_headers,
        )

        # Check public kiosk endpoint
        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        assert response.json()["kiosk_display_only"] is True


class TestPlayHistoryCsvExport:
    """Tests for play history CSV export functionality."""

    def test_export_play_history_csv_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test exporting play history as CSV."""
        from app.models.play_history import PlayHistory

        # Add play history entries
        entry1 = PlayHistory(
            event_id=test_event.id,
            title="First Song",
            artist="Artist One",
            album="Album One",
            source="stagelinq",
            matched_request_id=None,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=1,
        )
        entry2 = PlayHistory(
            event_id=test_event.id,
            title="Second Song",
            artist="Artist Two",
            album=None,
            source="manual",
            matched_request_id=42,
            started_at=utcnow(),
            ended_at=None,
            play_order=2,
        )
        db.add_all([entry1, entry2])
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert "play_history" in response.headers["content-disposition"]

        # Verify CSV content
        content = response.text
        assert "Title" in content
        assert "Artist" in content
        assert "Source" in content
        assert "Was Requested" in content
        assert "First Song" in content
        assert "Second Song" in content
        assert "Live" in content  # stagelinq -> Live
        assert "Manual" in content  # manual -> Manual

    def test_export_play_history_csv_no_auth(self, client: TestClient, test_event: Event):
        """Test exporting play history without auth fails."""
        response = client.get(f"/api/events/{test_event.code}/export/play-history/csv")
        assert response.status_code == 401

    def test_export_play_history_csv_not_owner(
        self, client: TestClient, db: Session, test_user: User, auth_headers: dict
    ):
        """Test exporting play history for event you don't own fails."""

        other_user = User(
            username="otheruser2",
            password_hash=get_password_hash("otherpassword"),
        )
        db.add(other_user)
        db.flush()

        other_event = Event(
            code="OTHER2",
            join_code="7PJBSF",
            name="Other User Event",
            created_by_user_id=other_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(other_event)
        db.commit()

        response = client.get(
            f"/api/events/{other_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_export_play_history_csv_includes_both_sources(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that export includes both stagelinq and manual sources."""
        from app.models.play_history import PlayHistory

        # Add stagelinq entry (live DJ tracking)
        stagelinq_entry = PlayHistory(
            event_id=test_event.id,
            title="Live Track",
            artist="DJ Artist",
            album=None,
            source="stagelinq",
            matched_request_id=None,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=1,
        )
        # Add manual entry (DJ marked request as played)
        manual_entry = PlayHistory(
            event_id=test_event.id,
            title="Requested Track",
            artist="Requested Artist",
            album=None,
            source="manual",
            matched_request_id=99,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=2,
        )
        db.add_all([stagelinq_entry, manual_entry])
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

        content = response.text
        lines = content.strip().split("\n")
        # Header + 2 data rows
        assert len(lines) == 3

        # Verify both sources are present
        assert "Live" in content  # stagelinq -> Live
        assert "Manual" in content  # manual -> Manual

    def test_export_play_history_csv_was_requested_column(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Test that Was Requested column shows Yes/No correctly."""
        from app.models.play_history import PlayHistory

        # Entry with matched request
        requested = PlayHistory(
            event_id=test_event.id,
            title="Requested Song",
            artist="Artist",
            album=None,
            source="stagelinq",
            matched_request_id=42,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=1,
        )
        # Entry without matched request
        not_requested = PlayHistory(
            event_id=test_event.id,
            title="DJ Choice",
            artist="Artist",
            album=None,
            source="stagelinq",
            matched_request_id=None,
            started_at=utcnow(),
            ended_at=utcnow(),
            play_order=2,
        )
        db.add_all([requested, not_requested])
        db.commit()

        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

        content = response.text
        # Both Yes and No should be present
        assert "Yes" in content
        assert "No" in content

    def test_export_play_history_csv_empty(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test exporting play history when no tracks played."""
        response = client.get(
            f"/api/events/{test_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content = response.text
        # Should have header row but no data rows
        assert "Title" in content
        lines = content.strip().split("\n")
        assert len(lines) == 1  # Just the header

    def test_export_play_history_csv_expired_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export play history CSV for expired events."""
        expired_event = Event(
            code="EXPHIS",
            join_code="UDD294",
            name="Expired Play History Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(
            f"/api/events/{expired_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_export_play_history_csv_archived_event(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        """Test that owner can export play history CSV for archived events."""
        archived_event = Event(
            code="ARCHIS",
            join_code="X9K3WM",
            name="Archived Play History Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(archived_event)
        db.commit()

        response = client.get(
            f"/api/events/{archived_event.code}/export/play-history/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestEventSearch:
    """Tests for GET /api/events/{code}/search endpoint."""

    @patch("app.services.spotify.search_songs")
    def test_event_search_returns_spotify_results(
        self, mock_search, client: TestClient, test_event: Event
    ):
        """Basic search returns Spotify results."""
        mock_search.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                album="For Lack of a Better Name",
                popularity=72,
                spotify_id="sp_strobe",
                source="spotify",
            )
        ]

        response = client.get(f"/api/events/{test_event.code}/search?q=deadmau5")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Strobe"
        assert data[0]["source"] == "spotify"

    @patch("app.services.beatport.search_beatport_tracks")
    @patch("app.services.spotify.search_songs")
    def test_event_search_includes_beatport_fallback(
        self, mock_spotify, mock_beatport, client: TestClient, db: Session, test_user: User
    ):
        """Event with Beatport-linked owner includes Beatport results."""
        # Give test_user Beatport tokens
        test_user.beatport_access_token = "bp_token"
        test_user.beatport_refresh_token = "bp_refresh"
        test_user.beatport_token_expires_at = utcnow() + timedelta(hours=1)
        db.flush()

        event = Event(
            code="BPSRCH",
            join_code="L8QGF8",
            name="BP Search Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            beatport_sync_enabled=True,
        )
        db.add(event)
        db.commit()

        mock_spotify.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                popularity=72,
                spotify_id="sp_strobe",
                source="spotify",
            )
        ]
        mock_beatport.return_value = [
            BeatportSearchResult(
                track_id="bp_99",
                title="Acid Phase",
                artist="DJ Pierre",
                beatport_url="https://www.beatport.com/track/acid-phase/99",
            )
        ]

        response = client.get(f"/api/events/{event.code}/search?q=acid+phase")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        sources = [r["source"] for r in data]
        assert "spotify" in sources
        assert "beatport" in sources

    @patch("app.services.spotify.search_songs")
    def test_event_search_no_beatport_when_not_linked(
        self, mock_search, client: TestClient, test_event: Event
    ):
        """DJ without Beatport linked -> Spotify only, no errors."""
        mock_search.return_value = [
            SearchResult(
                title="Levels",
                artist="Avicii",
                popularity=85,
                spotify_id="sp_levels",
                source="spotify",
            )
        ]

        response = client.get(f"/api/events/{test_event.code}/search?q=levels")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert all(r["source"] == "spotify" for r in data)

    def test_event_search_expired_event_returns_410(
        self, client: TestClient, db: Session, test_user: User
    ):
        """Expired event returns 410 for search."""
        expired_event = Event(
            code="EXPSRC",
            join_code="TM2WQM",
            name="Expired Search Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(f"/api/events/{expired_event.code}/search?q=test")
        assert response.status_code == 410

    def test_event_search_not_found_returns_404(self, client: TestClient):
        """Nonexistent event returns 404 for search."""
        response = client.get("/api/events/NOEXST/search?q=test")
        assert response.status_code == 404

    def test_event_search_query_too_short(self, client: TestClient, test_event: Event):
        """Query shorter than 2 characters returns 422."""
        response = client.get(f"/api/events/{test_event.code}/search?q=x")
        assert response.status_code == 422

    def test_event_search_query_too_long(self, client: TestClient, test_event: Event):
        """Query longer than 200 characters returns 422."""
        long_query = "a" * 201
        response = client.get(f"/api/events/{test_event.code}/search?q={long_query}")
        assert response.status_code == 422

    @patch("app.services.tidal.search_tidal_tracks")
    def test_event_search_tidal_primary(
        self, mock_tidal, client: TestClient, db: Session, test_user: User
    ):
        """Tidal is used as primary source when owner has Tidal linked."""
        from app.schemas.tidal import TidalSearchResult

        test_user.tidal_access_token = "tidal_token"
        db.flush()

        event = Event(
            code="TDSRCH",
            join_code="53VUXU",
            name="Tidal Search Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        mock_tidal.return_value = [
            TidalSearchResult(
                track_id="t123",
                title="Strobe",
                artist="deadmau5",
                tidal_url="https://tidal.com/browse/track/t123",
                popularity=80,
                isrc="USRC12345",
            )
        ]

        response = client.get(f"/api/events/{event.code}/search?q=strobe")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "tidal"
        assert data[0]["popularity"] == 80
        mock_tidal.assert_called_once()

    @patch("app.services.spotify.search_songs")
    @patch("app.services.tidal.search_tidal_tracks")
    def test_event_search_spotify_fallback_when_tidal_empty(
        self, mock_tidal, mock_spotify, client: TestClient, db: Session, test_user: User
    ):
        """Spotify is used when Tidal returns no results."""
        test_user.tidal_access_token = "tidal_token"
        db.flush()

        event = Event(
            code="FBSRCH",
            join_code="6DX252",
            name="Fallback Search Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        mock_tidal.return_value = []
        mock_spotify.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                popularity=72,
                spotify_id="sp_strobe",
                source="spotify",
            )
        ]

        response = client.get(f"/api/events/{event.code}/search?q=strobe")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "spotify"

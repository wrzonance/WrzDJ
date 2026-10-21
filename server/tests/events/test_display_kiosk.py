"""Event API tests grouped by behavior."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash


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

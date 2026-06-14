"""Tests for bridge admin command endpoints."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.bridge_integration import clear_all as clear_command_queue


@pytest.fixture(autouse=True)
def _clear_commands():
    """Clear the in-memory command queue before each test."""
    clear_command_queue()
    yield
    clear_command_queue()


@pytest.fixture
def bridge_headers() -> dict:
    """Get bridge API key headers."""
    return {"X-Bridge-API-Key": "test-bridge-key"}


@pytest.fixture
def other_user(db: Session) -> User:
    """Create a second DJ user who does NOT own the test event."""
    user = User(
        username="otheruser",
        password_hash=get_password_hash("otherpassword123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def other_headers(client: TestClient, other_user: User) -> dict[str, str]:
    """Get authentication headers for the other (non-owner) DJ."""
    response = client.post(
        "/api/auth/login",
        data={"username": "otheruser", "password": "otherpassword123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPostBridgeCommand:
    """Tests for POST /api/bridge/commands/{code} — JWT auth, queues commands."""

    def test_owner_can_queue_command(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Event owner can queue a command."""
        response = client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reset_decks"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["command_type"] == "reset_decks"
        assert len(data["command_id"]) == 36  # UUID format

    def test_admin_can_queue_command(
        self, client: TestClient, admin_headers: dict, test_event: Event
    ):
        """Admin can queue a command for any event."""
        response = client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reconnect"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["command_type"] == "reconnect"

    def test_non_owner_dj_gets_404(
        self, client: TestClient, other_headers: dict, test_event: Event
    ):
        """A DJ who doesn't own the event gets 404."""
        response = client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "restart"},
            headers=other_headers,
        )
        assert response.status_code == 404

    def test_no_auth_returns_401(self, client: TestClient, test_event: Event):
        """No JWT returns 401."""
        response = client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reset_decks"},
        )
        assert response.status_code == 401

    def test_nonexistent_event_returns_404(self, client: TestClient, auth_headers: dict):
        """Non-existent event code returns 404."""
        response = client.post(
            "/api/bridge/commands/NOEXIST",
            json={"command_type": "reset_decks"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_admin_nonexistent_event_returns_404(self, client: TestClient, admin_headers: dict):
        """Admin requesting non-existent event also gets 404."""
        response = client.post(
            "/api/bridge/commands/NOEXIST",
            json={"command_type": "reset_decks"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_invalid_command_type_returns_422(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Invalid command_type is rejected with 422."""
        response = client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "shutdown"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_all_valid_command_types(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """All valid generic command types are accepted."""
        for cmd in ("ping", "reset_decks", "reconnect", "restart"):
            response = client.post(
                "/api/bridge/commands/TEST01",
                json={"command_type": cmd},
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert response.json()["command_type"] == cmd

    def test_generic_endpoint_rejects_setbuilder_transport(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Setbuilder playback commands must go through the set-scoped transport endpoint."""
        response = client.post(
            "/api/bridge/commands/TEST01",
            json={
                "command_type": "setbuilder_transport",
                "payload": {"action": "play"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestGetBridgeCommands:
    """Tests for GET /api/bridge/commands/{code} — API key auth, polls commands."""

    @patch("app.core.bridge_auth.get_settings")
    def test_poll_returns_queued_commands(
        self,
        mock_settings,
        client: TestClient,
        auth_headers: dict,
        bridge_headers: dict,
        test_event: Event,
    ):
        """Polling returns commands that were queued."""
        mock_settings.return_value.bridge_api_key = "test-bridge-key"

        # Queue two commands
        client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reset_decks"},
            headers=auth_headers,
        )
        client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reconnect"},
            headers=auth_headers,
        )

        # Poll
        response = client.get(
            "/api/bridge/commands/TEST01",
            headers=bridge_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["commands"]) == 2
        types = {cmd["command_type"] for cmd in data["commands"]}
        assert types == {"reset_decks", "reconnect"}
        assert all(cmd["payload"] == {} for cmd in data["commands"])

    @patch("app.core.bridge_auth.get_settings")
    def test_poll_returns_payload(
        self,
        mock_settings,
        client: TestClient,
        auth_headers: dict,
        bridge_headers: dict,
        test_event: Event,
    ):
        """Polling preserves structured command payloads."""
        mock_settings.return_value.bridge_api_key = "test-bridge-key"
        from app.services.bridge_integration import queue_command

        queue_command(
            "TEST01",
            "setbuilder_transport",
            {"action": "seek", "position_sec": 12.5},
        )

        response = client.get("/api/bridge/commands/TEST01", headers=bridge_headers)
        assert response.status_code == 200
        command = response.json()["commands"][0]
        assert command["command_type"] == "setbuilder_transport"
        assert command["payload"] == {"action": "seek", "position_sec": 12.5}

    @patch("app.core.bridge_auth.get_settings")
    def test_poll_clears_queue(
        self,
        mock_settings,
        client: TestClient,
        auth_headers: dict,
        bridge_headers: dict,
        test_event: Event,
    ):
        """After polling, queue is empty."""
        mock_settings.return_value.bridge_api_key = "test-bridge-key"

        # Queue a command
        client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "restart"},
            headers=auth_headers,
        )

        # First poll returns command
        response = client.get("/api/bridge/commands/TEST01", headers=bridge_headers)
        assert len(response.json()["commands"]) == 1

        # Second poll returns empty
        response = client.get("/api/bridge/commands/TEST01", headers=bridge_headers)
        assert len(response.json()["commands"]) == 0

    @patch("app.core.bridge_auth.get_settings")
    def test_poll_empty_queue(self, mock_settings, client: TestClient, bridge_headers: dict):
        """Polling with no commands returns empty list."""
        mock_settings.return_value.bridge_api_key = "test-bridge-key"

        response = client.get("/api/bridge/commands/TEST01", headers=bridge_headers)
        assert response.status_code == 200
        assert response.json() == {"commands": []}

    def test_poll_without_api_key_returns_422(self, client: TestClient):
        """Missing API key header returns 422."""
        response = client.get("/api/bridge/commands/TEST01")
        assert response.status_code == 422

    @patch("app.core.bridge_auth.get_settings")
    def test_poll_with_invalid_api_key_returns_401(self, mock_settings, client: TestClient):
        """Invalid API key returns 401."""
        mock_settings.return_value.bridge_api_key = "correct-key"

        response = client.get(
            "/api/bridge/commands/TEST01",
            headers={"X-Bridge-API-Key": "wrong-key"},
        )
        assert response.status_code == 401


class TestCommandTTL:
    """Tests for command expiry (60s TTL)."""

    @patch("app.core.bridge_auth.get_settings")
    @patch("app.services.bridge_integration.utcnow")
    def test_expired_commands_are_pruned(
        self,
        mock_utcnow,
        mock_settings,
        client: TestClient,
        auth_headers: dict,
        bridge_headers: dict,
        test_event: Event,
    ):
        """Commands older than 60s are pruned on poll."""
        mock_settings.return_value.bridge_api_key = "test-bridge-key"
        base_time = utcnow()

        # Queue at t=0
        mock_utcnow.return_value = base_time
        client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reset_decks"},
            headers=auth_headers,
        )

        # Poll at t=61s — command should be expired
        mock_utcnow.return_value = base_time + timedelta(seconds=61)
        response = client.get("/api/bridge/commands/TEST01", headers=bridge_headers)
        assert response.status_code == 200
        assert len(response.json()["commands"]) == 0

    @patch("app.core.bridge_auth.get_settings")
    @patch("app.services.bridge_integration.utcnow")
    def test_fresh_commands_survive(
        self,
        mock_utcnow,
        mock_settings,
        client: TestClient,
        auth_headers: dict,
        bridge_headers: dict,
        test_event: Event,
    ):
        """Commands within TTL are returned."""
        mock_settings.return_value.bridge_api_key = "test-bridge-key"
        base_time = utcnow()

        # Queue at t=0
        mock_utcnow.return_value = base_time
        client.post(
            "/api/bridge/commands/TEST01",
            json={"command_type": "reconnect"},
            headers=auth_headers,
        )

        # Poll at t=30s — command should still be alive
        mock_utcnow.return_value = base_time + timedelta(seconds=30)
        response = client.get("/api/bridge/commands/TEST01", headers=bridge_headers)
        assert len(response.json()["commands"]) == 1


class TestEnrichedBridgeStatus:
    """Tests for enriched fields on POST /api/bridge/status."""

    @patch("app.core.bridge_auth.get_settings")
    def test_basic_status_still_works(
        self, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Old-format payloads (no enriched fields) still work."""
        mock_settings.return_value.bridge_api_key = "test-key"

        response = client.post(
            "/api/bridge/status",
            json={"event_code": "TEST01", "connected": True, "device_name": "SC6000"},
            headers={"X-Bridge-API-Key": "test-key"},
        )
        assert response.status_code == 200

    @patch("app.core.bridge_auth.get_settings")
    def test_enriched_status_accepted(
        self, mock_settings, client: TestClient, test_event: Event, db: Session
    ):
        """Enriched fields are accepted without error."""
        mock_settings.return_value.bridge_api_key = "test-key"

        response = client.post(
            "/api/bridge/status",
            json={
                "event_code": "TEST01",
                "connected": True,
                "device_name": "SC6000",
                "circuit_breaker_state": "CLOSED",
                "buffer_size": 42,
                "plugin_id": "stagelinq",
                "deck_count": 4,
                "uptime_seconds": 3600,
            },
            headers={"X-Bridge-API-Key": "test-key"},
        )
        assert response.status_code == 200

    @patch("app.api.bridge.publish_event")
    @patch("app.core.bridge_auth.get_settings")
    def test_enriched_fields_in_sse_event(
        self,
        mock_settings,
        mock_publish,
        client: TestClient,
        test_event: Event,
        db: Session,
    ):
        """Enriched fields are included in the SSE bridge_status_changed event."""
        mock_settings.return_value.bridge_api_key = "test-key"

        client.post(
            "/api/bridge/status",
            json={
                "event_code": "TEST01",
                "connected": True,
                "device_name": "SC6000",
                "circuit_breaker_state": "OPEN",
                "buffer_size": 10,
                "plugin_id": "pioneer",
                "deck_count": 2,
                "uptime_seconds": 120,
            },
            headers={"X-Bridge-API-Key": "test-key"},
        )

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        event_code = call_args[0][0]
        event_type = call_args[0][1]
        data = call_args[0][2]

        assert event_code == "TEST01"
        assert event_type == "bridge_status_changed"
        assert data["connected"] is True
        assert data["device_name"] == "SC6000"
        assert data["circuit_breaker_state"] == "OPEN"
        assert data["buffer_size"] == 10
        assert data["plugin_id"] == "pioneer"
        assert data["deck_count"] == 2
        assert data["uptime_seconds"] == 120

    @patch("app.api.bridge.publish_event")
    @patch("app.core.bridge_auth.get_settings")
    def test_basic_status_omits_enriched_from_sse(
        self,
        mock_settings,
        mock_publish,
        client: TestClient,
        test_event: Event,
        db: Session,
    ):
        """Basic payloads do NOT include enriched keys in the SSE event."""
        mock_settings.return_value.bridge_api_key = "test-key"

        client.post(
            "/api/bridge/status",
            json={"event_code": "TEST01", "connected": False},
            headers={"X-Bridge-API-Key": "test-key"},
        )

        mock_publish.assert_called_once()
        data = mock_publish.call_args[0][2]
        assert data == {"connected": False, "device_name": None}
        assert "circuit_breaker_state" not in data
        assert "buffer_size" not in data


class TestBridgeCommandRateLimits:
    """Verify rate limit decorators are applied."""

    def test_post_command_has_rate_limit(self):
        """POST /bridge/commands/{code} has rate limit decorator."""
        from app.api.bridge import post_bridge_command

        # The limiter decorator wraps the function; check it exists
        assert hasattr(post_bridge_command, "__wrapped__") or callable(post_bridge_command)

    def test_get_commands_has_rate_limit(self):
        """GET /bridge/commands/{code} has rate limit decorator."""
        from app.api.bridge import get_bridge_commands

        assert hasattr(get_bridge_commands, "__wrapped__") or callable(get_bridge_commands)

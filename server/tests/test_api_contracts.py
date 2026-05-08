"""API contract tests — verify response shapes match what the frontend expects.

These tests are the "vibe code insurance policy." When a future session adds or
removes a field from a Pydantic schema, these tests catch the mismatch before it
reaches production.

Each test asserts the exact set of keys in the JSON response, not the values.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request
from app.models.user import User


def _set_guest_cookie(client: TestClient, db: Session, suffix: str = "vote") -> Guest:
    g = Guest(
        token=suffix.ljust(64, "0"),
        fingerprint_hash=f"fp_{suffix}",
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    client.cookies.clear()
    client.cookies.set("wrzdj_guest", g.token)
    return g


# ── Helpers ──────────────────────────────────────────────────────────────────


def _assert_keys(data: dict, expected_keys: set, context: str = "") -> None:
    """Assert a dict contains exactly the expected keys."""
    actual = set(data.keys())
    missing = expected_keys - actual
    extra = actual - expected_keys
    msg_parts = []
    if missing:
        msg_parts.append(f"missing keys: {missing}")
    if extra:
        msg_parts.append(f"extra keys: {extra}")
    if msg_parts:
        pytest.fail(f"Key mismatch in {context}: {', '.join(msg_parts)}")


# ── Expected response shapes ────────────────────────────────────────────────

TOKEN_KEYS = {"access_token", "token_type"}

USER_OUT_KEYS = {
    "id",
    "username",
    "is_active",
    "email",
    "role",
    "created_at",
    "help_pages_seen",
    "pending_email",
}

EVENT_OUT_KEYS = {
    "id",
    "code",
    "name",
    "created_at",
    "expires_at",
    "is_active",
    "archived_at",
    "status",
    "join_url",
    "request_count",
    "tidal_sync_enabled",
    "tidal_playlist_id",
    "beatport_sync_enabled",
    "beatport_playlist_id",
    "banner_url",
    "banner_kiosk_url",
    "banner_colors",
    "requests_open",
    "collection_opens_at",
    "live_starts_at",
    "submission_cap_per_guest",
    "collection_phase_override",
}

REQUEST_OUT_KEYS = {
    "id",
    "event_id",
    "song_title",
    "artist",
    "source",
    "source_url",
    "artwork_url",
    "note",
    "nickname",
    "status",
    "created_at",
    "updated_at",
    "is_duplicate",
    "raw_search_query",
    "sync_results_json",
    "vote_count",
    "priority_score",
    "genre",
    "bpm",
    "musical_key",
}

ADMIN_USER_OUT_KEYS = {"id", "username", "is_active", "role", "created_at", "event_count"}

ADMIN_EVENT_OUT_KEYS = {
    "id",
    "code",
    "name",
    "owner_username",
    "owner_id",
    "created_at",
    "expires_at",
    "is_active",
    "request_count",
}

SYSTEM_STATS_KEYS = {
    "total_users",
    "active_users",
    "pending_users",
    "total_events",
    "active_events",
    "total_requests",
}

SYSTEM_SETTINGS_KEYS = {
    "registration_enabled",
    "search_rate_limit_per_minute",
    "spotify_enabled",
    "tidal_enabled",
    "beatport_enabled",
    "bridge_enabled",
    "human_verification_enforced",
    "llm_enabled",
    "llm_model",
    "llm_rate_limit_per_minute",
}

PUBLIC_SETTINGS_KEYS = {"registration_enabled", "turnstile_site_key"}

KIOSK_DISPLAY_KEYS = {
    "event",
    "qr_join_url",
    "accepted_queue",
    "now_playing",
    "now_playing_hidden",
    "requests_open",
    "updated_at",
    "banner_url",
    "banner_kiosk_url",
    "banner_colors",
    "kiosk_display_only",
}

PUBLIC_EVENT_INFO_KEYS = {"code", "name"}

PUBLIC_REQUEST_INFO_KEYS = {
    "id",
    "title",
    "artist",
    "artwork_url",
    "nickname",
    "vote_count",
    "bpm",
    "musical_key",
    "genre",
    "requester_verified",
}

GUEST_REQUEST_INFO_KEYS = PUBLIC_REQUEST_INFO_KEYS | {"status"}

VOTE_RESPONSE_KEYS = {"status", "vote_count", "has_voted"}

DISPLAY_SETTINGS_KEYS = {
    "status",
    "now_playing_hidden",
    "now_playing_auto_hide_minutes",
    "requests_open",
    "kiosk_display_only",
}

ACCEPT_ALL_KEYS = {"status", "accepted_count"}

PAGINATED_KEYS = {"items", "total", "page", "limit"}


# ── Auth contracts ───────────────────────────────────────────────────────────


class TestAuthContracts:
    def test_login_response_shape(self, client: TestClient, test_user: User):
        resp = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpassword123"},
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), TOKEN_KEYS, "POST /api/auth/login")

    def test_me_response_shape(self, client: TestClient, auth_headers: dict):
        resp = client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        _assert_keys(resp.json(), USER_OUT_KEYS, "GET /api/auth/me")

    def test_public_settings_shape(self, client: TestClient):
        resp = client.get("/api/auth/settings")
        assert resp.status_code == 200
        _assert_keys(resp.json(), PUBLIC_SETTINGS_KEYS, "GET /api/auth/settings")


# ── Event contracts ──────────────────────────────────────────────────────────


class TestEventContracts:
    def test_create_event_shape(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/api/events",
            json={"name": "Contract Test Event"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        _assert_keys(resp.json(), EVENT_OUT_KEYS, "POST /api/events")

    def test_list_events_shape(self, client: TestClient, auth_headers: dict, test_event: Event):
        resp = client.get("/api/events", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            _assert_keys(data[0], EVENT_OUT_KEYS, "GET /api/events[0]")

    def test_get_event_shape(self, client: TestClient, test_event: Event):
        resp = client.get(f"/api/events/{test_event.code}")
        assert resp.status_code == 200
        _assert_keys(resp.json(), EVENT_OUT_KEYS, "GET /api/events/{code}")

    def test_patch_event_shape(self, client: TestClient, auth_headers: dict, test_event: Event):
        resp = client.patch(
            f"/api/events/{test_event.code}",
            json={"name": "Updated Name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), EVENT_OUT_KEYS, "PATCH /api/events/{code}")

    def test_display_settings_response_shape(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        resp = client.get(
            f"/api/events/{test_event.code}/display-settings",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), DISPLAY_SETTINGS_KEYS, "GET /api/events/{code}/display-settings")


# ── Request contracts ────────────────────────────────────────────────────────


class TestRequestContracts:
    def test_submit_request_shape(self, client: TestClient, test_event: Event):
        resp = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"title": "Test Song", "artist": "Test Artist"},
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), REQUEST_OUT_KEYS, "POST /api/events/{code}/requests")

    def test_list_requests_shape(
        self, client: TestClient, auth_headers: dict, test_event: Event, test_request: Request
    ):
        resp = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            _assert_keys(data[0], REQUEST_OUT_KEYS, "GET /api/events/{code}/requests[0]")

    def test_update_request_shape(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        resp = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), REQUEST_OUT_KEYS, "PATCH /api/requests/{id}")

    def test_accept_all_shape(
        self, client: TestClient, auth_headers: dict, test_event: Event, test_request: Request
    ):
        resp = client.post(
            f"/api/events/{test_event.code}/requests/accept-all",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), ACCEPT_ALL_KEYS, "POST /api/events/{code}/requests/accept-all")


# ── Voting contracts ─────────────────────────────────────────────────────────


class TestVoteContracts:
    def test_vote_response_shape(self, client: TestClient, db: Session, test_request: Request):
        _set_guest_cookie(client, db, "v1")
        resp = client.post(f"/api/requests/{test_request.id}/vote")
        assert resp.status_code == 200
        _assert_keys(resp.json(), VOTE_RESPONSE_KEYS, "POST /api/requests/{id}/vote")

    def test_unvote_response_shape(self, client: TestClient, db: Session, test_request: Request):
        _set_guest_cookie(client, db, "v2")
        client.post(f"/api/requests/{test_request.id}/vote")
        resp = client.delete(f"/api/requests/{test_request.id}/vote")
        assert resp.status_code == 200
        _assert_keys(resp.json(), VOTE_RESPONSE_KEYS, "DELETE /api/requests/{id}/vote")


# ── Public / Kiosk contracts ────────────────────────────────────────────────


class TestPublicContracts:
    def test_kiosk_display_shape(self, client: TestClient, test_event: Event):
        resp = client.get(f"/api/public/events/{test_event.code}/display")
        assert resp.status_code == 200
        data = resp.json()
        _assert_keys(data, KIOSK_DISPLAY_KEYS, "GET /api/public/events/{code}/display")
        _assert_keys(data["event"], PUBLIC_EVENT_INFO_KEYS, "kiosk.event")

    def test_guest_requests_shape(self, client: TestClient, test_event: Event, test_request):
        resp = client.get(f"/api/public/events/{test_event.code}/requests")
        assert resp.status_code == 200
        data = resp.json()
        assert "event" in data
        assert "requests" in data
        _assert_keys(data["event"], PUBLIC_EVENT_INFO_KEYS, "guest.event")
        if data["requests"]:
            _assert_keys(data["requests"][0], GUEST_REQUEST_INFO_KEYS, "guest.requests[0]")

    def test_has_requested_shape(self, client: TestClient, test_event: Event):
        resp = client.get(f"/api/public/events/{test_event.code}/has-requested")
        assert resp.status_code == 200
        _assert_keys(resp.json(), {"has_requested"}, "GET /api/public/events/{code}/has-requested")


# ── Admin contracts ──────────────────────────────────────────────────────────


class TestAdminContracts:
    def test_stats_shape(self, client: TestClient, admin_headers: dict):
        resp = client.get("/api/admin/stats", headers=admin_headers)
        assert resp.status_code == 200
        _assert_keys(resp.json(), SYSTEM_STATS_KEYS, "GET /api/admin/stats")

    def test_users_list_shape(self, client: TestClient, admin_headers: dict):
        resp = client.get("/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_keys(data, PAGINATED_KEYS, "GET /api/admin/users")
        if data["items"]:
            _assert_keys(data["items"][0], ADMIN_USER_OUT_KEYS, "admin.users[0]")

    def test_create_user_shape(self, client: TestClient, admin_headers: dict):
        resp = client.post(
            "/api/admin/users",
            json={"username": "contractuser", "password": "password123"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        _assert_keys(resp.json(), ADMIN_USER_OUT_KEYS, "POST /api/admin/users")

    def test_update_user_shape(self, client: TestClient, admin_headers: dict, test_user: User):
        resp = client.patch(
            f"/api/admin/users/{test_user.id}",
            json={"role": "dj"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), ADMIN_USER_OUT_KEYS, "PATCH /api/admin/users/{id}")

    def test_events_list_shape(self, client: TestClient, admin_headers: dict, test_event: Event):
        resp = client.get("/api/admin/events", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        _assert_keys(data, PAGINATED_KEYS, "GET /api/admin/events")
        if data["items"]:
            _assert_keys(data["items"][0], ADMIN_EVENT_OUT_KEYS, "admin.events[0]")

    def test_settings_get_shape(self, client: TestClient, admin_headers: dict):
        resp = client.get("/api/admin/settings", headers=admin_headers)
        assert resp.status_code == 200
        _assert_keys(resp.json(), SYSTEM_SETTINGS_KEYS, "GET /api/admin/settings")

    def test_settings_update_shape(self, client: TestClient, admin_headers: dict):
        resp = client.patch(
            "/api/admin/settings",
            json={"registration_enabled": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        _assert_keys(resp.json(), SYSTEM_SETTINGS_KEYS, "PATCH /api/admin/settings")

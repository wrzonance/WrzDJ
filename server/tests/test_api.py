"""Basic API tests."""

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Test that the health endpoint works."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_invalid_credentials(client: TestClient):
    """Test that login fails with invalid credentials."""
    response = client.post(
        "/api/auth/login",
        data={"username": "nonexistent", "password": "wrong"},
    )
    assert response.status_code == 401


def test_events_requires_auth(client: TestClient):
    """Test that events endpoint requires authentication."""
    response = client.get("/api/events")
    assert response.status_code == 401


def test_search_requires_query(client: TestClient, auth_headers: dict):
    """Test that search requires a query parameter (auth required)."""
    response = client.get("/api/search", headers=auth_headers)
    assert response.status_code == 422  # Validation error


def test_global_exception_handler_returns_500():
    """Test that unhandled exceptions return 500 with generic message."""
    from app.main import create_app, no_background_lifespan

    test_app = create_app(lifespan_context=no_background_lifespan)

    with patch(
        "app.api.auth.get_system_settings",
        side_effect=RuntimeError("boom"),
    ):
        with TestClient(test_app, raise_server_exceptions=False) as c:
            response = c.get("/api/auth/settings")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert "debug" not in body

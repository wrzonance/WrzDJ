"""Dashboard session cookie + CSRF header (issue #754).

The DJ dashboard authenticates with an HttpOnly cookie instead of a JWT in
localStorage. The bearer path stays for the bridge-app, so both must work and
the cookie path must refuse requests that lack the CSRF header.
"""

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional
from app.core.session_cookie import (
    CSRF_HEADER_NAME,
    CSRF_HEADER_VALUE,
    SESSION_COOKIE_NAME,
)
from app.models.user import User
from app.services.auth import create_access_token
from tests.conftest import TEST_USER_PASSWORD

CSRF = {CSRF_HEADER_NAME: CSRF_HEADER_VALUE}


def _login(client: TestClient, username: str = "testuser", headers: dict | None = None):
    """Log in the way the dashboard does: with the CSRF header, so a cookie is issued."""
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": TEST_USER_PASSWORD},
        headers=CSRF if headers is None else headers,
    )


def _set_cookie_headers(response) -> list[str]:
    # httpx (TestClient) responses expose get_list; Starlette responses expose getlist.
    getter = getattr(response.headers, "get_list", None) or response.headers.getlist
    return getter("set-cookie")


def _session_cookie_header(response) -> str:
    set_cookie = [h for h in _set_cookie_headers(response) if SESSION_COOKIE_NAME in h]
    assert len(set_cookie) == 1, _set_cookie_headers(response)
    return set_cookie[0].lower()


def _token_for(user: User) -> str:
    return create_access_token(data={"sub": user.username, "tv": user.token_version})


class TestLoginSetsCookie:
    def test_login_sets_httponly_lax_session_cookie_and_still_returns_token(
        self, client: TestClient, test_user: User
    ):
        response = _login(client)
        assert response.status_code == 200
        assert response.json()["access_token"]  # bridge-app contract unchanged
        header = _session_cookie_header(response)
        assert "httponly" in header
        assert "samesite=lax" in header
        assert "path=/api/" in header
        assert "max-age=" in header
        assert "secure" not in header  # test env is not production

    def test_cookie_is_secure_in_production(self, monkeypatch):
        from fastapi import Response

        from app.core import session_cookie

        monkeypatch.setattr(session_cookie.get_settings(), "env", "production")
        response = Response()
        session_cookie.set_session_cookie(response, "tok")
        assert "secure" in _session_cookie_header(response)

    def test_login_without_csrf_header_returns_token_but_no_cookie(
        self, client: TestClient, test_user: User
    ):
        """Login CSRF defence: a cross-site form POST cannot carry the header, so it
        must not be able to plant a session cookie. Bearer clients (bridge-app) do
        not send the header either and simply get the body token."""
        response = _login(client, headers={})
        assert response.status_code == 200
        assert response.json()["access_token"]
        assert not any(SESSION_COOKIE_NAME in h for h in _set_cookie_headers(response))
        assert client.get("/api/auth/me", headers=CSRF).status_code == 401

    def test_failed_login_sets_no_cookie(self, client: TestClient, test_user: User):
        response = client.post(
            "/api/auth/login", data={"username": "testuser", "password": "wrong"}
        )
        assert response.status_code == 401
        assert not any(SESSION_COOKIE_NAME in h for h in response.headers.get_list("set-cookie"))


class TestCookieAuthentication:
    def test_cookie_with_csrf_header_authenticates(self, client: TestClient, test_user: User):
        _login(client)  # TestClient jar now holds the session cookie
        response = client.get("/api/auth/me", headers=CSRF)
        assert response.status_code == 200
        assert response.json()["username"] == "testuser"

    def test_cookie_without_csrf_header_is_rejected(self, client: TestClient, test_user: User):
        _login(client)
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_cookie_with_wrong_csrf_value_is_rejected(self, client: TestClient, test_user: User):
        _login(client)
        response = client.get("/api/auth/me", headers={CSRF_HEADER_NAME: "XMLHttpRequest"})
        assert response.status_code == 401

    def test_bearer_without_cookie_or_header_still_works(
        self, client: TestClient, auth_headers: dict[str, str]
    ):
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200

    def test_bearer_wins_over_cookie(
        self, client: TestClient, test_user: User, admin_user: User, db: Session
    ):
        _login(client)  # cookie = testuser
        response = client.get(
            "/api/auth/me",
            headers={**CSRF, "Authorization": f"Bearer {_token_for(admin_user)}"},
        )
        assert response.status_code == 200
        assert response.json()["username"] == admin_user.username

    def test_revoked_cookie_is_rejected(self, client: TestClient, test_user: User, db: Session):
        _login(client)
        test_user.token_version += 1
        db.commit()
        response = client.get("/api/auth/me", headers=CSRF)
        assert response.status_code == 401

    def test_garbage_cookie_is_rejected(self, client: TestClient, test_user: User):
        client.cookies.set(SESSION_COOKIE_NAME, "not-a-jwt")
        response = client.get("/api/auth/me", headers=CSRF)
        assert response.status_code == 401


class TestOptionalDependency:
    """get_current_user_optional must honour the cookie path with the same CSRF rule."""

    @staticmethod
    def _request(headers: dict[str, str]) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})

    def test_cookie_with_header_resolves_user(self, db: Session, test_user: User):
        request = self._request(
            {"cookie": f"{SESSION_COOKIE_NAME}={_token_for(test_user)}", **CSRF}
        )
        user = get_current_user_optional(request, db=db, bearer=None)
        assert user is not None and user.id == test_user.id

    def test_cookie_without_header_resolves_none(self, db: Session, test_user: User):
        request = self._request({"cookie": f"{SESSION_COOKIE_NAME}={_token_for(test_user)}"})
        assert get_current_user_optional(request, db=db, bearer=None) is None

    def test_no_credentials_resolves_none(self, db: Session):
        assert get_current_user_optional(self._request({}), db=db, bearer=None) is None


class TestEndingTheSession:
    def test_delete_session_clears_cookie_without_revoking_bearer_tokens(
        self, client: TestClient, test_user: User, db: Session
    ):
        _login(client)
        before = test_user.token_version
        response = client.delete("/api/auth/session", headers=CSRF)
        assert response.status_code == 200
        header = _session_cookie_header(response)
        assert "max-age=0" in header or "expires=" in header
        db.refresh(test_user)
        assert test_user.token_version == before  # bridge-app sessions survive
        assert client.get("/api/auth/me", headers=CSRF).status_code == 401

    def test_delete_session_is_fine_when_not_logged_in(self, client: TestClient):
        assert client.delete("/api/auth/session").status_code == 200

    def test_logout_also_clears_cookie(self, client: TestClient, test_user: User):
        _login(client)
        response = client.post("/api/auth/logout", headers=CSRF)
        assert response.status_code == 200
        header = _session_cookie_header(response)
        assert "max-age=0" in header or "expires=" in header

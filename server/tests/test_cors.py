"""Tests for CORS configuration.

Regression: PUT was missing from allow_methods for non-wildcard CORS origins,
causing preflight failures on the Tidal settings endpoint in production.
"""

from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from app import main
from app.main import CORS_ALLOW_METHODS, app


class TestCorsConfiguration:
    """Verify CORS allows all HTTP methods used by the API."""

    def test_cors_methods_cover_all_api_routes(self):
        """Every HTTP method used by an API route must be in CORS_ALLOW_METHODS."""
        api_methods = set()
        for route in app.routes:
            if hasattr(route, "methods") and route.methods:
                api_methods.update(route.methods)

        for method in api_methods:
            if method == "HEAD":
                continue  # HEAD is implicitly handled
            assert method in CORS_ALLOW_METHODS, (
                f"HTTP {method} is used by API routes but missing from CORS_ALLOW_METHODS"
            )

    def test_cors_middleware_is_configured(self):
        """CORSMiddleware must be present in the middleware stack."""
        cors_mw = next(
            (m for m in app.user_middleware if m.cls is CORSMiddleware),
            None,
        )
        assert cors_mw is not None, "CORSMiddleware not found on app"

    def test_cors_allows_kiosk_pair_nonce_preflight_in_production(self, monkeypatch):
        """Prod CORS must allow the X-Pair-Nonce header on the kiosk pair preflight.

        Regression: a browser pairing a kiosk POSTs /api/public/kiosk/pair with a
        custom X-Pair-Nonce header, which triggers a CORS preflight. Under
        non-wildcard (production) origins the header was absent from allow_headers,
        so the preflight returned 400 "Disallowed CORS headers" and the kiosk page
        surfaced "Failed to create pairing session" — the device could never
        create a fresh pairing after being unpaired.
        """
        monkeypatch.setattr(main.settings, "cors_origins", "https://app.wrzdj.com")
        prod_app = main.create_app()

        # No context manager → lifespan/background tasks stay off; the preflight is
        # short-circuited by CORSMiddleware before routing, so no DB is needed.
        client = TestClient(prod_app)
        resp = client.options(
            "/api/public/kiosk/pair",
            headers={
                "Origin": "https://app.wrzdj.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-pair-nonce",
            },
        )

        assert resp.status_code == 200, resp.text
        allowed = resp.headers.get("access-control-allow-headers", "").lower()
        assert "x-pair-nonce" in allowed, (
            f"X-Pair-Nonce not allowed by prod CORS; allow-headers={allowed!r}"
        )

    def test_cors_allows_csrf_header_preflight_in_production(self, monkeypatch):
        """Prod CORS must allow X-Requested-With: the cookie-auth CSRF header (#754)."""
        monkeypatch.setattr(main.settings, "cors_origins", "https://app.wrzdj.com")
        client = TestClient(main.create_app())
        resp = client.options(
            "/api/auth/me",
            headers={
                "Origin": "https://app.wrzdj.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-requested-with",
            },
        )
        assert resp.status_code == 200, resp.text
        allowed = resp.headers.get("access-control-allow-headers", "").lower()
        assert "x-requested-with" in allowed, allowed
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_wildcard_dev_cors_allows_credentials(self, monkeypatch):
        """CORS_ORIGINS=* (dev/LAN testing) must still let the session cookie flow (#754).

        Starlette echoes the request Origin when allow_origins is "*" and
        allow_credentials is True, which is what browsers require for cookies.
        """
        monkeypatch.setattr(main.settings, "cors_origins", "*")
        client = TestClient(main.create_app())
        resp = client.options(
            "/api/auth/me",
            headers={
                "Origin": "http://192.168.20.5:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-requested-with",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("access-control-allow-origin") == "http://192.168.20.5:3000"
        assert resp.headers.get("access-control-allow-credentials") == "true"

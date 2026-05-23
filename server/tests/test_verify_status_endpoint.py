"""Tests for GET /api/public/guest/verify-status."""

import hashlib
from datetime import timedelta  # noqa: F401

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest


def _make_guest(db: Session, suffix: str = "default") -> Guest:
    email = f"{suffix}@example.com"
    g = Guest(
        token="vs" + suffix.ljust(62, "0"),
        fingerprint_hash=f"fp_{suffix}",
        verified_email=email,
        email_hash=hashlib.sha256(email.encode()).hexdigest(),
        email_verified_at=utcnow(),
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


class TestVerifyStatusEndpoint:
    def test_no_cookie_returns_false(self, client: TestClient):
        client.cookies.clear()
        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        body = r.json()
        assert body == {"verified": False, "expires_in": 0}

    def test_cache_control_header_no_store(self, client: TestClient):
        client.cookies.clear()
        r = client.get("/api/public/guest/verify-status")
        cc = r.headers.get("cache-control", "").lower()
        assert "no-store" in cc
        assert "private" in cc

    def test_valid_cookie_returns_true_with_expires_in(self, client: TestClient, db: Session):
        from fastapi import Response

        from app.services.human_verification import COOKIE_NAME, issue_human_cookie

        guest = _make_guest(db, "valid")
        helper_resp = Response()
        issue_human_cookie(helper_resp, guest.id)
        raw = helper_resp.headers["set-cookie"]
        cookie_value = raw.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]

        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, cookie_value)

        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        body = r.json()
        assert body["verified"] is True
        # Sliding window is 60 min (3600s); expires_in must be near it
        assert 3500 < body["expires_in"] <= 3600

    def test_v1_cookie_returns_false(self, client: TestClient, db: Session):
        """Crafted v=1 (versionless) cookie must be silently rejected as if missing."""
        import base64 as _base64
        import hashlib as _hashlib
        import hmac as _hmac
        import json as _json

        from app.core.config import get_settings

        guest = _make_guest(db, "v1")
        key = get_settings().effective_human_cookie_secret
        payload = _json.dumps(
            {"guest_id": guest.id, "exp": 9999999999}, separators=(",", ":")
        ).encode()
        sig = _hmac.new(key, payload, _hashlib.sha256).digest()

        def b64enc(b: bytes) -> str:
            return _base64.urlsafe_b64encode(b).decode().rstrip("=")

        cookie_value = f"{b64enc(payload)}.{b64enc(sig)}"
        client.cookies.clear()
        client.cookies.set("wrzdj_human", cookie_value)

        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        assert r.json() == {"verified": False, "expires_in": 0}

    def test_tampered_signature_returns_false(self, client: TestClient, db: Session):
        from fastapi import Response

        from app.services.human_verification import COOKIE_NAME, issue_human_cookie

        guest = _make_guest(db, "tamper")
        helper_resp = Response()
        issue_human_cookie(helper_resp, guest.id)
        raw = helper_resp.headers["set-cookie"]
        cookie_value = raw.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        # Flip the last char of the signature portion
        bad = cookie_value[:-1] + ("A" if cookie_value[-1] != "A" else "B")

        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, bad)
        r = client.get("/api/public/guest/verify-status")
        assert r.status_code == 200
        assert r.json()["verified"] is False

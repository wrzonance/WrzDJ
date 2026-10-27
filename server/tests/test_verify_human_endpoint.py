"""Tests for POST /api/guest/verify-human."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.services.human_verification import COOKIE_NAME


def _create_guest(db: Session, token: str = "test-guest-token") -> Guest:
    guest = Guest(token=token)
    db.add(guest)
    db.commit()
    db.refresh(guest)
    return guest


class TestVerifyHumanEndpoint:
    @patch(
        "app.api.guest.verify_turnstile_token",
        new_callable=AsyncMock,
        return_value=True,
    )
    def test_success_sets_cookie(self, mock_turnstile, client: TestClient, db: Session):
        guest = _create_guest(db)
        client.cookies.set("wrzdj_guest", guest.token)

        response = client.post(
            "/api/public/guest/verify-human",
            json={"turnstile_token": "fake-token"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["verified"] is True
        assert body["expires_in"] == 3600
        assert COOKIE_NAME in response.cookies

        # Verify the cookie binds to THIS guest, not an arbitrary one
        from fastapi import Request as FastAPIRequest

        from app.services.human_verification import verify_human_cookie

        cookie_value = response.cookies[COOKIE_NAME]
        scope = {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": b"",
        }
        verify_request = FastAPIRequest(scope)
        verify_request._cookies = {COOKIE_NAME: cookie_value}
        assert verify_human_cookie(verify_request) == guest.id

    @patch(
        "app.api.guest.verify_turnstile_token",
        new_callable=AsyncMock,
        return_value=False,
    )
    def test_invalid_turnstile_token_400(self, mock_turnstile, client: TestClient, db: Session):
        guest = _create_guest(db)
        client.cookies.set("wrzdj_guest", guest.token)

        response = client.post(
            "/api/public/guest/verify-human",
            json={"turnstile_token": "bad-token"},
        )
        assert response.status_code == 400
        assert "CAPTCHA" in response.json()["detail"]
        assert COOKIE_NAME not in response.cookies

    @patch(
        "app.api.guest.verify_turnstile_token",
        new_callable=AsyncMock,
        return_value=True,
    )
    def test_success_records_pass_on_guest(self, mock_turnstile, client: TestClient, db: Session):
        guest = _create_guest(db)
        client.cookies.set("wrzdj_guest", guest.token)

        client.post("/api/public/guest/verify-human", json={"turnstile_token": "t"})
        client.post("/api/public/guest/verify-human", json={"turnstile_token": "t"})

        db.refresh(guest)
        assert guest.human_verify_count == 2
        assert guest.human_verified_at is not None

    @patch(
        "app.api.guest.verify_turnstile_token",
        new_callable=AsyncMock,
        return_value=False,
    )
    def test_failure_does_not_record_pass(self, mock_turnstile, client: TestClient, db: Session):
        guest = _create_guest(db)
        client.cookies.set("wrzdj_guest", guest.token)

        client.post("/api/public/guest/verify-human", json={"turnstile_token": "bad"})

        db.refresh(guest)
        assert guest.human_verify_count == 0
        assert guest.human_verified_at is None

    def test_missing_guest_cookie_400(self, client: TestClient, db: Session):
        # No wrzdj_guest cookie set
        response = client.post(
            "/api/public/guest/verify-human",
            json={"turnstile_token": "any"},
        )
        assert response.status_code == 400
        assert "Guest" in response.json()["detail"]

    def test_missing_token_field_422(self, client: TestClient, db: Session):
        guest = _create_guest(db)
        client.cookies.set("wrzdj_guest", guest.token)

        response = client.post("/api/public/guest/verify-human", json={})
        assert response.status_code == 422

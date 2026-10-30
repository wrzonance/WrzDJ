"""Integration tests for email verification endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.guest import Guest


def _identify(client: TestClient, fingerprint: str) -> dict:
    """Helper: identify a guest and return {guest_id, cookie}."""
    client.cookies.clear()
    resp = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": fingerprint, "fingerprint_components": {}},
    )
    assert resp.status_code == 200
    return {
        "guest_id": resp.json()["guest_id"],
        "cookie": resp.cookies.get("wrzdj_guest"),
    }


def test_request_code_returns_sent(client: TestClient, db: Session):
    """POST /verify/request -> 200 with {sent: true}."""
    guest = _identify(client, "verify_test_fp_1")
    client.cookies.set("wrzdj_guest", guest["cookie"])

    with patch("app.services.email_verification.send_verification_email"):
        resp = client.post(
            "/api/public/guest/verify/request",
            json={"email": "test@example.com", "turnstile_token": "test-token"},
        )
    assert resp.status_code == 200
    assert resp.json()["sent"] is True


def test_request_code_without_cookie_fails(client: TestClient):
    """No wrzdj_guest cookie -> error."""
    client.cookies.clear()
    resp = client.post(
        "/api/public/guest/verify/request",
        json={"email": "test@example.com", "turnstile_token": "test-token"},
    )
    assert resp.status_code in (400, 401)


def test_confirm_code_sets_email_on_guest(client: TestClient, db: Session):
    """Correct code -> email on Guest row."""
    guest_info = _identify(client, "verify_test_fp_2")
    client.cookies.set("wrzdj_guest", guest_info["cookie"])

    with patch("app.services.email_verification.send_verification_email"):
        client.post(
            "/api/public/guest/verify/request",
            json={"email": "verified@test.com", "turnstile_token": "test-token"},
        )

    from app.models.email_verification_code import EmailVerificationCode

    code_row = (
        db.query(EmailVerificationCode)
        .filter(EmailVerificationCode.guest_id == guest_info["guest_id"])
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    assert code_row is not None

    resp = client.post(
        "/api/public/guest/verify/confirm",
        json={"email": "verified@test.com", "code": code_row.code},
    )
    assert resp.status_code == 200
    assert resp.json()["verified"] is True

    guest = db.query(Guest).filter(Guest.id == guest_info["guest_id"]).one()
    assert guest.email_verified_at is not None


def test_confirm_code_returns_merged_true(client: TestClient, db: Session):
    """Second device verifies same email -> {merged: true}, new cookie."""
    # Device A
    device_a = _identify(client, "merge_device_a_fp")
    client.cookies.set("wrzdj_guest", device_a["cookie"])

    with patch("app.services.email_verification.send_verification_email"):
        client.post(
            "/api/public/guest/verify/request",
            json={"email": "shared@test.com", "turnstile_token": "test-token"},
        )

    from app.models.email_verification_code import EmailVerificationCode

    code_a = (
        db.query(EmailVerificationCode)
        .filter(EmailVerificationCode.guest_id == device_a["guest_id"])
        .first()
    )
    client.post(
        "/api/public/guest/verify/confirm",
        json={"email": "shared@test.com", "code": code_a.code},
    )

    # Device B
    device_b = _identify(client, "merge_device_b_fp")
    client.cookies.set("wrzdj_guest", device_b["cookie"])

    with patch("app.services.email_verification.send_verification_email"):
        client.post(
            "/api/public/guest/verify/request",
            json={"email": "shared@test.com", "turnstile_token": "test-token"},
        )

    code_b = (
        db.query(EmailVerificationCode)
        .filter(EmailVerificationCode.guest_id == device_b["guest_id"])
        .first()
    )
    resp = client.post(
        "/api/public/guest/verify/confirm",
        json={"email": "shared@test.com", "code": code_b.code},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["merged"] is True
    assert data["guest_id"] == device_a["guest_id"]


def test_confirm_wrong_code_returns_error(client: TestClient, db: Session):
    """Wrong code -> 400."""
    guest = _identify(client, "wrong_code_fp")
    client.cookies.set("wrzdj_guest", guest["cookie"])

    with patch("app.services.email_verification.send_verification_email"):
        client.post(
            "/api/public/guest/verify/request",
            json={"email": "wrong@test.com", "turnstile_token": "test-token"},
        )

    resp = client.post(
        "/api/public/guest/verify/confirm",
        json={"email": "wrong@test.com", "code": "000000"},
    )
    assert resp.status_code == 400


def _human_cookie_for(guest_id: int) -> str:
    """Mint a wrzdj_human cookie value bound to guest_id."""
    from fastapi import Response

    from app.services.human_verification import COOKIE_NAME, issue_human_cookie

    resp = Response()
    issue_human_cookie(resp, guest_id)
    raw = resp.headers["set-cookie"]
    return raw.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]


def _human_cookie_guest_id(cookie_value: str) -> int | None:
    """Return the guest id a wrzdj_human cookie value is bound to."""
    from fastapi import Request

    from app.services.human_verification import COOKIE_NAME, verify_human_cookie

    request = Request(
        {"type": "http", "headers": [], "method": "GET", "path": "/", "query_string": b""}
    )
    request._cookies = {COOKIE_NAME: cookie_value}
    return verify_human_cookie(request)


def _claim_email(client: TestClient, db: Session, guest_id: int, email: str):
    """Request and confirm a code for `email` as the client's current guest."""
    from app.models.email_verification_code import EmailVerificationCode

    with patch("app.services.email_verification.send_verification_email"):
        client.post(
            "/api/public/guest/verify/request",
            json={"email": email, "turnstile_token": "test-token"},
        )
    code = (
        db.query(EmailVerificationCode).filter(EmailVerificationCode.guest_id == guest_id).first()
    )
    return client.post(
        "/api/public/guest/verify/confirm",
        json={"email": email, "code": code.code},
    )


def test_confirm_merge_rebinds_human_cookie_to_surviving_guest(client: TestClient, db: Session):
    """#874: a merge rotates wrzdj_guest; the browser's proven human cookie must follow it."""
    device_a = _identify(client, "rebind_device_a_fp")
    client.cookies.set("wrzdj_guest", device_a["cookie"])
    assert _claim_email(client, db, device_a["guest_id"], "rebind@test.com").status_code == 200

    device_b = _identify(client, "rebind_device_b_fp")
    client.cookies.set("wrzdj_guest", device_b["cookie"])
    client.cookies.set("wrzdj_human", _human_cookie_for(device_b["guest_id"]))
    resp = _claim_email(client, db, device_b["guest_id"], "rebind@test.com")

    assert resp.status_code == 200
    assert resp.json()["merged"] is True
    assert _human_cookie_guest_id(resp.cookies["wrzdj_human"]) == device_a["guest_id"]


def test_confirm_merge_without_human_cookie_issues_none(client: TestClient, db: Session):
    """#874: a merge must not mint a human cookie the browser never earned."""
    device_a = _identify(client, "noearn_device_a_fp")
    client.cookies.set("wrzdj_guest", device_a["cookie"])
    assert _claim_email(client, db, device_a["guest_id"], "noearn@test.com").status_code == 200

    device_b = _identify(client, "noearn_device_b_fp")
    client.cookies.set("wrzdj_guest", device_b["cookie"])
    resp = _claim_email(client, db, device_b["guest_id"], "noearn@test.com")

    assert resp.json()["merged"] is True
    assert "wrzdj_human" not in resp.cookies


def test_confirm_merge_ignores_human_cookie_of_another_guest(client: TestClient, db: Session):
    """#874: a human cookie bound to some other guest must not be rebound on merge."""
    device_a = _identify(client, "foreign_device_a_fp")
    client.cookies.set("wrzdj_guest", device_a["cookie"])
    assert _claim_email(client, db, device_a["guest_id"], "foreign@test.com").status_code == 200

    bystander = _identify(client, "foreign_bystander_fp")
    device_b = _identify(client, "foreign_device_b_fp")
    client.cookies.set("wrzdj_guest", device_b["cookie"])
    client.cookies.set("wrzdj_human", _human_cookie_for(bystander["guest_id"]))
    resp = _claim_email(client, db, device_b["guest_id"], "foreign@test.com")

    assert resp.json()["merged"] is True
    assert "wrzdj_human" not in resp.cookies


def test_confirm_merge_cookie_max_age_follows_setting(client: TestClient, db: Session, monkeypatch):
    """The rotated wrzdj_guest cookie from a merge uses the same lifetime as identify."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "guest_cookie_max_age_seconds", 12 * 60 * 60)
    device_a = _identify(client, "max_age_device_a_fp")
    client.cookies.set("wrzdj_guest", device_a["cookie"])
    assert _claim_email(client, db, device_a["guest_id"], "maxage@test.com").status_code == 200

    device_b = _identify(client, "max_age_device_b_fp")
    client.cookies.set("wrzdj_guest", device_b["cookie"])
    resp = _claim_email(client, db, device_b["guest_id"], "maxage@test.com")

    assert resp.json()["merged"] is True
    (header,) = [h for h in resp.headers.get_list("set-cookie") if h.startswith("wrzdj_guest=")]
    assert "Max-Age=43200" in header

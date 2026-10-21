"""Shared per-test guest identity setup for collection API tests."""

import pytest

from app.core.time import utcnow
from app.models.guest import Guest


@pytest.fixture(autouse=True)
def _default_guest_cookie(client, db):
    """Most collect endpoints require a wrzdj_guest cookie (identity is guest_id only).

    After the 2026-05-20 collection-hardening change, the collect mutating
    endpoints also require a verified email and a valid wrzdj_human cookie.
    The default test guest is therefore pre-verified, and we issue a
    matching wrzdj_human cookie so the gate passes without an OTP roundtrip.

    See docs/RECOVERY-IP-IDENTITY.md and
    docs/superpowers/specs/2026-05-20-collection-vs-live-event-codes-design.md.
    """
    import hashlib

    from fastapi import Response

    from app.services.human_verification import COOKIE_NAME as HUMAN_COOKIE_NAME
    from app.services.human_verification import issue_human_cookie

    email = "default-test@example.com"
    guest = Guest(
        token="defaultguest" + "0" * 52,
        fingerprint_hash="fp_default",
        verified_email=email,
        email_hash=hashlib.sha256(email.encode()).hexdigest(),
        email_verified_at=utcnow(),
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)

    # Mint a valid wrzdj_human cookie tied to this guest_id.
    helper_resp = Response()
    issue_human_cookie(helper_resp, guest.id)
    raw = helper_resp.headers.get("set-cookie", "")
    human_value = raw.split("=", 1)[1].split(";", 1)[0] if "=" in raw else ""

    client.cookies.clear()
    client.cookies.set("wrzdj_guest", guest.token)
    if human_value:
        client.cookies.set(HUMAN_COOKIE_NAME, human_value)
    return guest

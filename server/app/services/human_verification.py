"""Human-verification signed cookie helpers.

Issues and validates wrzdj_human cookies after Turnstile verification.
HMAC-SHA256 signed payload with a sliding TTL.

Spec: docs/superpowers/specs/2026-05-01-public-page-human-verification-design.md
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.core.time import utcnow

if TYPE_CHECKING:
    from fastapi import Request, Response

logger = logging.getLogger(__name__)

COOKIE_NAME = "wrzdj_human"
HUMAN_COOKIE_VERSION = 2  # Bump on any breaking schema or policy change.


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload_bytes: bytes, key: bytes) -> bytes:
    return hmac.new(key, payload_bytes, hashlib.sha256).digest()


def issue_human_cookie(response: Response, guest_id: int) -> None:
    """Sign payload with HMAC-SHA256 and set the wrzdj_human cookie.

    The payload carries an integer `v` discriminator so a future invalidation
    can reject all prior cookies by bumping the constant. Older payloads
    without the field are silently rejected in verify_human_cookie().

    Sliding window: caller invokes this on every successful gated request to
    reset the cookie's exp to now + ttl.
    """
    settings = get_settings()
    key = settings.effective_human_cookie_secret
    ttl = settings.human_cookie_ttl_seconds
    exp = int(utcnow().timestamp()) + ttl

    payload = {"v": HUMAN_COOKIE_VERSION, "guest_id": int(guest_id), "exp": exp}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = _sign(payload_bytes, key)
    cookie_value = f"{_b64encode(payload_bytes)}.{_b64encode(sig)}"

    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=ttl,
        path="/api/",
    )


def verify_human_cookie(request: Request) -> int | None:
    """Return guest_id if the wrzdj_human cookie is valid, signed, version-matched, and unexpired.

    Returns None on any failure (missing, malformed, bad signature, wrong version, expired).
    """
    raw = request.cookies.get(COOKIE_NAME)
    if not raw or "." not in raw:
        return None

    try:
        payload_part, sig_part = raw.rsplit(".", 1)
        payload_bytes = _b64decode(payload_part)
        sig_bytes = _b64decode(sig_part)
    except (ValueError, binascii.Error):
        return None

    settings = get_settings()
    key = settings.effective_human_cookie_secret
    expected_sig = _sign(payload_bytes, key)

    if not hmac.compare_digest(expected_sig, sig_bytes):
        return None

    try:
        payload = json.loads(payload_bytes)
    except (ValueError, TypeError):
        return None

    # Reject cookies issued under prior schema versions (v=1 had no field;
    # the constant bump forces every pre-existing session to re-verify).
    if payload.get("v") != HUMAN_COOKIE_VERSION:
        return None

    try:
        guest_id_raw = payload["guest_id"]
        if not isinstance(guest_id_raw, int) or isinstance(guest_id_raw, bool):
            return None
        guest_id = guest_id_raw
        exp = payload["exp"]
        if not isinstance(exp, int) or isinstance(exp, bool):
            return None
    except (KeyError, TypeError):
        return None

    if exp < int(utcnow().timestamp()):
        return None

    return guest_id

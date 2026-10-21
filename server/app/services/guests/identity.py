"""Guest identity resolution service.

Resolves anonymous guests via a two-signal system:
1. Server-assigned HttpOnly cookie token (primary, canonical)
2. ThumbmarkJS browser fingerprint hash (reconciliation fallback)
"""

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest

_logger = logging.getLogger("app.guest.identity")

RECONCILE_QUIET_PERIOD = timedelta(hours=12)
RECONCILE_FRESHNESS_WINDOW = timedelta(days=90)


def _short_fp(fp: str | None) -> str:
    """Truncate the (already-hashed) browser fingerprint to 12 chars for log correlation.

    The fingerprint_hash from ThumbmarkJS is a hex string; this is a safe truncation
    for log correlation, never an IP. See docs/RECOVERY-IP-IDENTITY.md.
    """
    if not fp:
        return "-"
    return fp[:12]


@dataclass
class IdentifyResult:
    guest_id: int
    action: Literal["create", "cookie_hit", "reconcile"]
    token: str | None  # set only when a new cookie should be issued
    reconcile_hint: bool = False  # true when create happened but a FP match existed
    rejection_reason: str | None = None  # internal-only — never sent to clients


def _ua_signals_match(stored_ua: str | None, submitted_ua: str) -> bool:
    """Strict equality on UA family, platform, and ±1 major version.

    Replaces the weighted confidence score with hard-coded gates. Used by
    fingerprint reconciliation to decide whether two UA strings are
    consistent enough to plausibly be the same device.
    """
    if not stored_ua:
        return False
    s_family, s_platform, s_version = _parse_ua(stored_ua)
    n_family, n_platform, n_version = _parse_ua(submitted_ua)
    if s_family == "unknown" or n_family == "unknown":
        return False
    if s_family != n_family or s_platform != n_platform:
        return False
    if not s_version or not n_version:
        return False
    try:
        return abs(int(s_version) - int(n_version)) <= 1
    except ValueError:
        return s_version == n_version


def _parse_ua(ua: str) -> tuple[str, str, str]:
    """Extract (browser_family, platform, major_version) from UA string.

    Simple heuristic parser — covers the browsers that matter for mobile
    event guests (Safari, Chrome, Firefox, Samsung).
    """
    ua_lower = ua.lower()

    platform = "unknown"
    if "iphone" in ua_lower or "ipad" in ua_lower:
        platform = "ios"
    elif "android" in ua_lower:
        platform = "android"
    elif "windows" in ua_lower:
        platform = "windows"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        platform = "macos"
    elif "linux" in ua_lower:
        platform = "linux"

    family = "unknown"
    version = ""
    if "firefox/" in ua_lower:
        family = "firefox"
        version = _extract_version(ua, "Firefox/")
    elif "edg/" in ua_lower:
        family = "edge"
        version = _extract_version(ua, "Edg/")
    elif "samsungbrowser/" in ua_lower:
        family = "samsung"
        version = _extract_version(ua, "SamsungBrowser/")
    elif "crios/" in ua_lower:
        family = "chrome"
        version = _extract_version(ua, "CriOS/")
    elif "chrome/" in ua_lower and "safari/" in ua_lower:
        family = "chrome"
        version = _extract_version(ua, "Chrome/")
    elif "version/" in ua_lower and "safari/" in ua_lower:
        family = "safari"
        version = _extract_version(ua, "Version/")

    return family, platform, version


def _extract_version(ua: str, prefix: str) -> str:
    """Extract major version number after a prefix like 'Chrome/'."""
    idx = ua.find(prefix)
    if idx == -1:
        return ""
    start = idx + len(prefix)
    end = start
    while end < len(ua) and ua[end].isdigit():
        end += 1
    return ua[start:end]


def identify_guest(
    db: Session,
    *,
    token_from_cookie: str | None,
    fingerprint_hash: str,
    fingerprint_components: dict | None = None,
    user_agent: str,
) -> IdentifyResult:
    """Resolve a guest's identity using cookie token and/or browser fingerprint.

    Returns an IdentifyResult with the guest_id, the action taken, and
    optionally a new token (when a cookie must be set/refreshed).
    """
    components_json = json.dumps(fingerprint_components) if fingerprint_components else None
    now = utcnow()
    short_fp = _short_fp(fingerprint_hash)

    # --- Flow 2: Cookie present ---
    if token_from_cookie:
        guest = db.query(Guest).filter(Guest.token == token_from_cookie).first()
        if guest:
            old_fp = guest.fingerprint_hash
            guest.last_seen_at = now
            guest.user_agent = user_agent
            if fingerprint_hash and fingerprint_hash != guest.fingerprint_hash:
                _logger.warning(
                    "guest.identify action=fingerprint_drift guest_id=%s old_fp=%s new_fp=%s",
                    guest.id,
                    _short_fp(old_fp),
                    short_fp,
                )
                guest.fingerprint_hash = fingerprint_hash
                guest.fingerprint_components = components_json
            db.commit()
            _logger.info(
                "guest.identify action=cookie_hit guest_id=%s fp=%s source=cookie",
                guest.id,
                short_fp,
            )
            return IdentifyResult(guest_id=guest.id, action="cookie_hit", token=None)

    # --- LAYER 2: fingerprint reconciliation (gated by 4 rules) ---
    rejection_reason: str | None = None
    if fingerprint_hash:
        matches = (
            db.query(Guest)
            .filter(Guest.fingerprint_hash == fingerprint_hash)
            .filter(Guest.last_seen_at > now - RECONCILE_FRESHNESS_WINDOW)
            .all()
        )

        if len(matches) > 1:
            rejection_reason = "ambiguous_match"
        elif len(matches) == 1:
            existing = matches[0]
            if existing.email_verified_at is not None:
                rejection_reason = "verified_guest"
            elif existing.last_seen_at > now - RECONCILE_QUIET_PERIOD:
                rejection_reason = "concurrent_activity"
            elif not _ua_signals_match(existing.user_agent, user_agent):
                rejection_reason = "ua_mismatch"
            else:
                # All gates passed — reconcile
                existing.last_seen_at = now
                existing.user_agent = user_agent
                existing.fingerprint_components = components_json
                new_token = secrets.token_hex(32)
                existing.token = new_token
                db.commit()
                _logger.info(
                    "guest.identify action=reconcile guest_id=%s fp=%s",
                    existing.id,
                    short_fp,
                )
                return IdentifyResult(
                    guest_id=existing.id,
                    action="reconcile",
                    token=new_token,
                    reconcile_hint=False,
                    rejection_reason=None,
                )

        if rejection_reason is not None:
            _logger.warning(
                "guest.identify action=reconcile_rejected fp=%s reason=%s existing_guest=%s",
                short_fp,
                rejection_reason,
                matches[0].id if matches else None,
            )

    # --- LAYER 3: create new guest ---
    new_token = secrets.token_hex(32)
    guest = Guest(
        token=new_token,
        fingerprint_hash=fingerprint_hash,
        fingerprint_components=components_json,
        user_agent=user_agent,
        created_at=now,
        last_seen_at=now,
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)

    hint = rejection_reason is not None
    _logger.info(
        "guest.identify action=create guest_id=%s fp=%s hint=%s reason=%s",
        guest.id,
        short_fp,
        hint,
        rejection_reason or "no_match",
    )
    return IdentifyResult(
        guest_id=guest.id,
        action="create",
        token=new_token,
        reconcile_hint=hint,
        rejection_reason=rejection_reason,
    )

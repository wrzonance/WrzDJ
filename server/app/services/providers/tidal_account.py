"""Tidal account connection, device-login, and session lifecycle."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import tidalapi
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.providers.tidal_session import (
    get_tidal_session as _get_tidal_session,
)
from app.services.providers.tidal_session import (
    persist_tidal_token_refresh,
)

logger = logging.getLogger(__name__)

# Device login state expiration (10 minutes)
DEVICE_LOGIN_TTL_MINUTES = 10


@dataclass
class DeviceLoginState:
    """State for device OAuth flow."""

    user_id: int
    session: tidalapi.Session
    login_info: Any  # tidalapi.LinkLogin
    future: Any  # concurrent.futures.Future
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# In-memory device login storage
_device_logins: dict[int, DeviceLoginState] = {}
_login_lock = threading.Lock()


def _cleanup_expired_device_logins() -> None:
    """Remove device logins older than TTL."""
    cutoff = datetime.now(UTC) - timedelta(minutes=DEVICE_LOGIN_TTL_MINUTES)
    with _login_lock:
        expired = [uid for uid, state in _device_logins.items() if state.created_at < cutoff]
        for uid in expired:
            del _device_logins[uid]


def start_device_login(user: User) -> dict[str, str]:
    """Start Tidal device login flow.

    Returns dict with verification_url and user_code for the user to visit.
    """
    _cleanup_expired_device_logins()

    session = tidalapi.Session()
    login, future = session.login_oauth()

    with _login_lock:
        _device_logins[user.id] = DeviceLoginState(
            user_id=user.id,
            session=session,
            login_info=login,
            future=future,
        )

    # Ensure URL has https:// prefix (tidalapi may omit it)
    url = login.verification_uri_complete
    if url and not url.startswith("http"):
        url = f"https://{url}"

    return {
        "verification_url": url,
        "user_code": login.user_code,
    }


def check_device_login(db: Session, user: User) -> dict[str, Any]:
    """Check if device login is complete.

    Returns status dict with 'complete' bool and optionally 'error'.
    """
    expired_state: DeviceLoginState | None = None
    cutoff = datetime.now(UTC) - timedelta(minutes=DEVICE_LOGIN_TTL_MINUTES)
    with _login_lock:
        state = _device_logins.get(user.id)
        if state is not None:
            created_at = state.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if created_at < cutoff:
                expired_state = _device_logins.pop(user.id)
                state = None

    if expired_state is not None:
        # The SDK's Future may already be running its own provider-expiry poll.
        # cancel() only stops it if it has not started; it never interrupts a live SDK worker.
        expired_state.future.cancel()
        return {"complete": False, "error": "Tidal login expired. Please try again."}

    if not state:
        return {"complete": False, "error": "No pending login"}

    # Check if future is done
    if not state.future.done():
        url = state.login_info.verification_uri_complete
        if url and not url.startswith("http"):
            url = f"https://{url}"
        return {
            "complete": False,
            "pending": True,
            "verification_url": url,
            "user_code": state.login_info.user_code,
        }

    try:
        # Future completed - check result
        state.future.result(timeout=0)

        # Login succeeded - save tokens
        session = state.session
        user.tidal_access_token = session.access_token
        user.tidal_refresh_token = session.refresh_token
        user.tidal_token_expires_at = session.expiry_time
        user.tidal_user_id = str(session.user.id) if session.user else ""

        db.commit()
        logger.info(f"Tidal device login completed for user {user.id}")

        # Cleanup
        with _login_lock:
            _device_logins.pop(user.id, None)

        return {"complete": True, "user_id": user.tidal_user_id}

    except Exception as e:
        logger.error("Tidal device login failed for user %s (%s)", user.id, type(e).__name__)
        with _login_lock:
            _device_logins.pop(user.id, None)
        return {"complete": False, "error": "Tidal login failed. Please try again."}


def cancel_device_login(user: User) -> None:
    """Cancel a pending device login."""
    with _login_lock:
        _device_logins.pop(user.id, None)


def get_tidal_session(db: Session, user: User) -> tidalapi.Session | None:
    """Get an authenticated session; persist refreshed credentials separately.

    Refresh persistence uses its own transaction so this getter never commits
    unrelated pending changes held by the caller's SQLAlchemy session.
    """
    return _get_tidal_session(db, user, tidalapi.Session, persist_tidal_token_refresh)


def disconnect_tidal(db: Session, user: User) -> None:
    """Unlink Tidal account from user."""
    user.tidal_access_token = None
    user.tidal_refresh_token = None
    user.tidal_token_expires_at = None
    user.tidal_user_id = None
    db.commit()

    # Cancel any pending device login
    with _login_lock:
        _device_logins.pop(user.id, None)

    logger.info(f"Tidal disconnected for user {user.id}")

"""Authenticated Tidal session construction and isolated token persistence."""

import logging
from collections.abc import Callable
from datetime import datetime

import tidalapi
from sqlalchemy.orm import Session

from app.models.user import User

logger = logging.getLogger(__name__)


def persist_tidal_token_refresh(
    db: Session,
    user_id: int,
    access_token: str,
    refresh_token: str,
    expiry_time: datetime,
) -> None:
    """Persist refreshed credentials without committing the caller's work."""
    with Session(bind=db.get_bind()) as token_db:
        token_user = token_db.get(User, user_id)
        if token_user is None:
            return
        token_user.tidal_access_token = access_token
        token_user.tidal_refresh_token = refresh_token
        token_user.tidal_token_expires_at = expiry_time
        token_db.commit()


def get_tidal_session(
    db: Session,
    user: User,
    session_factory: Callable[[], tidalapi.Session],
    persist_refresh: Callable[[Session, int, str, str, datetime], None],
) -> tidalapi.Session | None:
    """Create an authenticated session and persist token refresh independently."""
    if not user.tidal_access_token:
        return None

    session = session_factory()
    try:
        session.load_oauth_session(
            token_type="Bearer",  # nosec B106
            access_token=user.tidal_access_token,
            refresh_token=user.tidal_refresh_token,
            expiry_time=user.tidal_token_expires_at,
        )
        if not session.check_login():
            if not session.token_refresh(user.tidal_refresh_token):
                logger.error("Failed to refresh Tidal session")
                return None

            user.tidal_access_token = session.access_token
            user.tidal_refresh_token = session.refresh_token
            user.tidal_token_expires_at = session.expiry_time
            persist_refresh(
                db,
                user.id,
                session.access_token,
                session.refresh_token,
                session.expiry_time,
            )
            logger.info("Tidal token refreshed")
        return session
    except Exception as exc:
        logger.error("Failed to load Tidal session: %s", type(exc).__name__)
        return None

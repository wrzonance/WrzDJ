"""Validation helpers for encrypted Apple Music connection data."""

import json
import re

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.provider_connection import UserProviderConnection
from app.models.user import User
from app.services.apple_music_tokens import AppleMusicNotConnected

_STOREFRONT_RE = re.compile(r"^[a-z]{2}$")
_USER_TOKEN_MIN_LENGTH = 20
_USER_TOKEN_MAX_LENGTH = 8192


def _valid_user_token(token: object) -> bool:
    return (
        isinstance(token, str)
        and _USER_TOKEN_MIN_LENGTH <= len(token) <= _USER_TOKEN_MAX_LENGTH
        and not any(ord(char) < 32 or ord(char) == 127 for char in token)
    )


def stored_user_token(connection: UserProviderConnection) -> str | None:
    """Parse the versioned token envelope without exposing corrupt stored data."""
    try:
        credentials = json.loads(connection.credential_payload or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(credentials, dict) or type(credentials.get("version")) is not int:
        return None
    if credentials["version"] != 1:
        return None
    token = credentials.get("music_user_token")
    return token if _valid_user_token(token) else None


def stored_storefront(connection: UserProviderConnection) -> str | None:
    """Parse the stored storefront and reject invalid metadata shapes."""
    try:
        metadata = json.loads(connection.metadata_json or "{}")
    except (TypeError, ValueError):
        return None
    storefront = metadata.get("storefront") if isinstance(metadata, dict) else None
    return (
        storefront if isinstance(storefront, str) and _STOREFRONT_RE.fullmatch(storefront) else None
    )


def read_stored_connection(db: Session, user: User) -> tuple[str, str]:
    """Return valid credentials or mark a corrupt connection for DJ reauthorization."""
    connection = (
        db.query(UserProviderConnection)
        .filter_by(user_id=user.id, provider_id="apple_music")
        .one_or_none()
    )
    if not connection or connection.connection_state != "connected":
        raise AppleMusicNotConnected
    token = stored_user_token(connection)
    storefront = stored_storefront(connection)
    expired = connection.expires_at is not None and connection.expires_at <= utcnow()
    if token is None or storefront is None or expired:
        connection.connection_state = "reauthorize"
        raise AppleMusicNotConnected
    return token, storefront

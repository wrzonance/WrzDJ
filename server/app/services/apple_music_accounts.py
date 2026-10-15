"""Apple Music DJ account authorization and encrypted connection storage."""

import json
import re

from sqlalchemy.orm import Session

from app.models.provider_connection import UserProviderConnection
from app.models.user import User
from app.services import apple_music_storage, apple_music_tokens

_STOREFRONT_RE = re.compile(r"^[a-z]{2}$")


def _connection(
    db: Session, user: User, *, populate_existing: bool = False
) -> UserProviderConnection | None:
    query = db.query(UserProviderConnection).filter_by(user_id=user.id, provider_id="apple_music")
    if populate_existing:
        query = query.populate_existing()
    return query.one_or_none()


def _lock_user(db: Session, user: User) -> None:
    """Serialize brief connection-state writes without holding locks over network requests."""
    db.query(User).filter_by(id=user.id).with_for_update().one()


def _begin_link_attempt(db: Session, user: User) -> int:
    _lock_user(db, user)
    connection = _connection(db, user)
    if connection is None:
        connection = UserProviderConnection(
            user_id=user.id,
            provider_id="apple_music",
            connection_state="disconnected",
            credential_type="music_user_token",
        )
        db.add(connection)
        db.flush()
    connection.authorization_generation += 1
    generation = connection.authorization_generation
    db.commit()
    return generation


def _complete_link_attempt(
    db: Session, user: User, generation: int, token: str, storefront: str
) -> UserProviderConnection:
    _lock_user(db, user)
    connection = _connection(db, user)
    if connection is None or connection.authorization_generation != generation:
        db.rollback()
        raise apple_music_tokens.AppleMusicLinkSuperseded
    connection.connection_state = "connected"
    connection.credential_type = "music_user_token"
    connection.credential_payload = json.dumps(
        {"version": 1, "music_user_token": token}, separators=(",", ":")
    )
    connection.metadata_json = json.dumps({"storefront": storefront}, separators=(",", ":"))
    connection.expires_at = None
    db.commit()
    db.refresh(connection)
    return connection


def _needs_reauthorization(db: Session, connection: UserProviderConnection) -> None:
    if connection.connection_state != "reauthorize":
        connection.connection_state = "reauthorize"
        db.commit()


def _apply_status_result(
    db: Session,
    user: User,
    generation: int,
    *,
    storefront: str | None = None,
    reauthorize: bool = False,
) -> bool:
    """Apply an Apple status result only if no newer link or disconnect won."""
    _lock_user(db, user)
    connection = _connection(db, user, populate_existing=True)
    if (
        connection is None
        or connection.connection_state != "connected"
        or connection.authorization_generation != generation
    ):
        db.rollback()
        return False
    if reauthorize:
        connection.connection_state = "reauthorize"
    elif storefront is not None:
        connection.metadata_json = json.dumps({"storefront": storefront}, separators=(",", ":"))
    db.commit()
    return True


def mark_reauthorization_if_current(db: Session, user: User, generation: int) -> bool:
    """Invalidate a rejected grant only when no newer link or disconnect has won."""
    return _apply_status_result(db, user, generation, reauthorize=True)


def link_account(db: Session, user: User, music_user_token: str) -> UserProviderConnection:
    """Validate Apple authorization, then persist only if no disconnect superseded it."""
    generation = _begin_link_attempt(db, user)
    developer_token, _ = apple_music_tokens.create_developer_token()
    storefront = fetch_user_storefront(music_user_token, developer_token)
    return _complete_link_attempt(db, user, generation, music_user_token, storefront)


def fetch_user_storefront(music_user_token: str, developer_token: str) -> str:
    """Validate a user token and return the storefront reported by Apple."""
    payload = apple_music_tokens.apple_get(
        "/me/storefront", developer_token, music_user_token=music_user_token
    )
    data = payload.get("data")
    storefront_item = data[0] if isinstance(data, list) and data else None
    if not isinstance(storefront_item, dict):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid storefront")
    storefront = storefront_item.get("id")
    if not isinstance(storefront, str) or not _STOREFRONT_RE.fullmatch(storefront):
        raise apple_music_tokens.AppleMusicError("Apple Music returned an invalid storefront")
    return storefront


def linked_account_status(connection: UserProviderConnection) -> dict[str, object]:
    """Build the immediate link response from the storefront validated by Apple."""
    return {
        "configured": True,
        "linked": connection.connection_state == "connected"
        and bool(connection.credential_payload),
        "requires_reauthorization": connection.connection_state == "reauthorize",
        "storefront": apple_music_storage.stored_storefront(connection),
    }


def disconnect_account(db: Session, user: User) -> None:
    """Invalidate in-flight links and clear user credentials, keeping a tombstone."""
    _lock_user(db, user)
    connection = _connection(db, user)
    if connection is None:
        connection = UserProviderConnection(
            user_id=user.id,
            provider_id="apple_music",
            connection_state="disconnected",
            credential_type="music_user_token",
        )
        db.add(connection)
        db.flush()
    connection.authorization_generation += 1
    connection.connection_state = "disconnected"
    connection.credential_payload = None
    connection.metadata_json = None
    connection.expires_at = None
    db.commit()


def account_status(db: Session, user: User) -> dict[str, object]:
    """Check stored authorization and mark corrupt or revoked tokens for relinking."""
    connection = _connection(db, user, populate_existing=True)
    configured = apple_music_tokens.is_configured()
    token = None
    storefront = None
    if connection and connection.connection_state == "connected":
        try:
            token, storefront = apple_music_storage.read_stored_connection(db, user)
        except apple_music_tokens.AppleMusicNotConnected:
            connection = _connection(db, user, populate_existing=True)
    if configured and token and connection and connection.connection_state == "connected":
        generation = connection.authorization_generation
        try:
            developer_token, _ = apple_music_tokens.create_developer_token()
            storefront = fetch_user_storefront(token, developer_token)
        except apple_music_tokens.AppleMusicUserAuthorizationError:
            _apply_status_result(db, user, generation, reauthorize=True)
        except apple_music_tokens.AppleMusicNotConfigured:
            configured = False
        except apple_music_tokens.AppleMusicError:
            raise
        else:
            _apply_status_result(db, user, generation, storefront=storefront)

    connection = _connection(db, user, populate_existing=True)
    state = connection.connection_state if connection else "disconnected"
    if connection and state == "connected":
        token = apple_music_storage.stored_user_token(connection)
        storefront = apple_music_storage.stored_storefront(connection)
        if token is None or storefront is None:
            _needs_reauthorization(db, connection)
            connection = _connection(db, user, populate_existing=True)
            state = connection.connection_state if connection else "disconnected"
    return {
        "configured": configured,
        "linked": state == "connected" and bool(token),
        "requires_reauthorization": state == "reauthorize",
        "storefront": storefront if state == "connected" else None,
    }


def stored_connection(db: Session, user: User) -> tuple[str, str]:
    """Return validated stored token and storefront, marking malformed credentials unusable."""
    return apple_music_storage.read_stored_connection(db, user)

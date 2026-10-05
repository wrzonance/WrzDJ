"""Spotify user authorization for playlist writes."""

import base64
import logging
import secrets
from datetime import UTC, datetime, timedelta
from time import time
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.spotify.com/authorize"
OAUTH_EXCHANGE_URL = "https://accounts.spotify.com/api/token"
SCOPES = "playlist-modify-private user-library-modify"
HTTP_TIMEOUT = 15.0


class SpotifyOAuthError(Exception):
    """Spotify authorization or token exchange failed."""


def _configured() -> bool:
    settings = get_settings()
    return bool(
        settings.spotify_client_id
        and settings.spotify_client_secret
        and settings.spotify_redirect_uri
        and settings.public_url
    )


def authorization_url(db: Session, user: User) -> str:
    """Persist a one-time CSRF state and return Spotify's authorization URL."""
    if not _configured():
        raise SpotifyOAuthError("Spotify OAuth is not configured")
    settings = get_settings()
    state = f"{user.id}.{int(time())}.{secrets.token_urlsafe(32)}"
    user.spotify_oauth_state = state
    db.commit()
    query = urlencode(
        {
            "client_id": settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": settings.spotify_redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def _basic_auth(client_id: str, client_secret: str) -> str:
    credentials = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(credentials).decode("ascii")


def _token_expiry(token_data: dict) -> datetime:
    try:
        expires_in = int(token_data.get("expires_in", 3600))
    except (ValueError, TypeError) as exc:
        raise SpotifyOAuthError("Spotify returned an invalid token expiry") from exc
    if not 1 <= expires_in <= 86400:
        raise SpotifyOAuthError("Spotify returned an invalid token expiry")
    return datetime.now(UTC) + timedelta(seconds=expires_in)


def _exchange_code(code: str) -> dict:
    settings = get_settings()
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                OAUTH_EXCHANGE_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.spotify_redirect_uri,
                },
                headers={
                    "Authorization": _basic_auth(
                        settings.spotify_client_id, settings.spotify_client_secret
                    )
                },
            )
            response.raise_for_status()
            token_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Spotify authorization code exchange failed: %s", type(exc).__name__)
        raise SpotifyOAuthError("Spotify authorization failed") from exc
    if (
        not isinstance(token_data, dict)
        or not isinstance(token_data.get("access_token"), str)
        or not token_data["access_token"]
        or not isinstance(token_data.get("refresh_token"), str)
        or not token_data["refresh_token"]
    ):
        raise SpotifyOAuthError("Spotify returned an incomplete token response")
    granted_scopes = set(str(token_data.get("scope", "")).split())
    if not set(SCOPES.split()).issubset(granted_scopes):
        raise SpotifyOAuthError("Spotify did not grant playlist write access")
    return token_data


def finish_authorization(db: Session, state: str, code: str) -> User:
    """Validate callback state, exchange the code, and store encrypted tokens."""
    user_id, issued_at, nonce = _parse_state(state)
    if not nonce or abs(time() - issued_at) > 600:
        raise SpotifyOAuthError("Spotify authorization state expired")
    user = db.get(User, user_id)
    if (
        user is None
        or not user.spotify_oauth_state
        or not secrets.compare_digest(user.spotify_oauth_state.encode(), state.encode())
    ):
        raise SpotifyOAuthError("Invalid Spotify authorization state")

    token_data = _exchange_code(code)
    user.spotify_access_token = token_data["access_token"]
    user.spotify_refresh_token = token_data["refresh_token"]
    user.spotify_token_expires_at = _token_expiry(token_data)
    user.spotify_oauth_state = None
    db.commit()
    return user


def cancel_authorization(db: Session, state: str) -> None:
    """Validate and clear a state when the user cancels at Spotify."""
    user_id, issued_at, nonce = _parse_state(state)
    if not nonce or abs(time() - issued_at) > 600:
        raise SpotifyOAuthError("Spotify authorization state expired")
    user = db.get(User, user_id)
    if (
        user is None
        or not user.spotify_oauth_state
        or not secrets.compare_digest(user.spotify_oauth_state.encode(), state.encode())
    ):
        raise SpotifyOAuthError("Invalid Spotify authorization state")
    user.spotify_oauth_state = None
    db.commit()


def _parse_state(state: str) -> tuple[int, int, str]:
    """Validate bounds and encoding before database access or constant-time comparison."""
    if not isinstance(state, str) or not state.isascii() or len(state) > 200:
        raise SpotifyOAuthError("Invalid Spotify authorization state")
    try:
        user_id_text, issued_text, nonce = state.split(".", maxsplit=2)
        user_id = int(user_id_text)
        issued_at = int(issued_text)
    except (ValueError, TypeError):
        raise SpotifyOAuthError("Invalid Spotify authorization state") from None
    if not 1 <= user_id <= 2_147_483_647 or not nonce or not nonce.isascii():
        raise SpotifyOAuthError("Invalid Spotify authorization state")
    return user_id, issued_at, nonce


def _clear_credentials(db: Session, user: User) -> None:
    user.spotify_access_token = None
    user.spotify_refresh_token = None
    user.spotify_token_expires_at = None
    db.commit()


def _grant_rejected(response: httpx.Response) -> bool:
    """Whether Spotify permanently rejected this user's refresh token (RFC 6749 §5.2).

    Only ``invalid_grant`` condemns the stored token. Outages (5xx/429) and
    ``invalid_client`` (our own app credentials) share the 400/401 statuses but
    must not unlink the user.
    """
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("error") == "invalid_grant"


def refresh_access_token(db: Session, user: User) -> bool:
    """Refresh an expired access token; return whether a valid token is available."""
    if not user.spotify_access_token:
        return False
    if user.spotify_token_expires_at:
        expires_at = user.spotify_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > datetime.now(UTC):
            return True
    if not user.spotify_refresh_token:
        _clear_credentials(db, user)
        return False

    settings = get_settings()
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                OAUTH_EXCHANGE_URL,
                data={"grant_type": "refresh_token", "refresh_token": user.spotify_refresh_token},
                headers={
                    "Authorization": _basic_auth(
                        settings.spotify_client_id, settings.spotify_client_secret
                    )
                },
            )
            response.raise_for_status()
            token_data = response.json()
        if not isinstance(token_data, dict) or not isinstance(token_data.get("access_token"), str):
            raise SpotifyOAuthError("Spotify returned an incomplete token response")
        user.spotify_access_token = token_data["access_token"]
        refreshed_token = token_data.get("refresh_token")
        if isinstance(refreshed_token, str) and refreshed_token:
            user.spotify_refresh_token = refreshed_token
        user.spotify_token_expires_at = _token_expiry(token_data)
        db.commit()
        return True
    except SpotifyOAuthError as exc:
        logger.warning("Spotify token refresh failed: %s", type(exc).__name__)
        _clear_credentials(db, user)
        return False
    except httpx.HTTPStatusError as exc:
        logger.warning("Spotify token refresh failed: %s", type(exc).__name__)
        if _grant_rejected(exc.response):
            _clear_credentials(db, user)
        return False
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        # Transient (network, timeout, malformed body): keep the tokens so the next call retries.
        logger.warning("Spotify token refresh failed: %s", type(exc).__name__)
        return False


def disconnect(db: Session, user: User) -> None:
    """Clear stored Spotify credentials and pending authorization state."""
    user.spotify_access_token = None
    user.spotify_refresh_token = None
    user.spotify_token_expires_at = None
    user.spotify_oauth_state = None
    db.commit()

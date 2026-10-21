"""Beatport authentication, token lifecycle, and account metadata."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User
from app.services.providers.beatport_common import (
    BEATPORT_API_BASE,
    DEFAULT_TOKEN_EXPIRY,
    HTTP_TIMEOUT,
)
from app.services.providers.beatport_token_response import (
    BeatportTokenResponse,
)
from app.services.providers.beatport_token_response import (
    parse_token_response as _parse_token_response,
)

logger = logging.getLogger(__name__)


def _auth_base() -> str:
    """Auth base URL derived from beatport_auth_base_url config."""
    return get_settings().beatport_auth_base_url


def _login_url() -> str:
    """Login URL for username/password authentication."""
    return f"{_auth_base()}/login/"


def _authorize_url() -> str:
    """Authorize URL for getting an authorization code."""
    return f"{_auth_base()}/o/authorize/"


def _token_url() -> str:  # nosec B105
    """Token URL for exchanging authorization code."""
    return f"{_auth_base()}/o/token/"


def _revoke_url() -> str:
    """Revoke URL for token revocation."""
    return f"{_auth_base()}/o/revoke_token/"


def login_and_get_tokens(username: str, password: str) -> BeatportTokenResponse:
    """Authenticate with Beatport using username/password and return tokens.

    This performs the full server-side OAuth flow:
    1. POST to /auth/login/ with credentials → session cookies
    2. GET /auth/o/authorize/ with cookies → 302 with auth code
    3. POST /auth/o/token/ with code → access + refresh tokens

    Raises httpx.HTTPStatusError on auth failure (401/403).
    Raises ValueError if the auth code cannot be extracted.
    """
    settings = get_settings()
    client_id = settings.beatport_client_id
    redirect_uri = settings.beatport_redirect_uri

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
        # Step 1: Login with username/password to get session cookies
        login_resp = client.post(
            _login_url(),
            json={"username": username, "password": password},
        )
        login_resp.raise_for_status()
        login_data = login_resp.json()

        if "username" not in login_data or "email" not in login_data:
            raise ValueError("Invalid Beatport credentials")

        # Step 2: Request authorization code using the session
        authorize_resp = client.get(
            _authorize_url(),
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            },
        )

        # The authorize endpoint should 302-redirect to redirect_uri?code=xxx
        if authorize_resp.status_code not in (301, 302):
            error_text = authorize_resp.text[:200] if authorize_resp.text else ""
            raise ValueError(
                f"Expected redirect from authorize, got {authorize_resp.status_code}: {error_text}"
            )

        location = authorize_resp.headers.get("location", "")
        parsed = urlparse(location if "://" in location else f"{BEATPORT_API_BASE}{location}")
        code_values = parse_qs(parsed.query).get("code")
        if not code_values:
            raise ValueError(f"No authorization code in redirect: {location[:200]}")

        auth_code = code_values[0]

        # Step 3: Exchange authorization code for tokens
        token_resp = client.post(
            _token_url(),
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
            },
        )
        token_resp.raise_for_status()
        return _parse_token_response(token_resp.json())


def ensure_beatport_token(db: Session, user: User) -> bool:
    """Refresh Beatport token if expired. Returns True if token is valid."""
    if not user.beatport_access_token:
        return False

    # Compare timezone-safe (SQLite returns naive datetimes)
    if user.beatport_token_expires_at:
        expires = user.beatport_token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires > datetime.now(UTC):
            return True

    if not user.beatport_refresh_token:
        return False

    settings = get_settings()
    try:
        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": user.beatport_refresh_token,
            "client_id": settings.beatport_client_id,
        }
        if settings.beatport_client_secret:
            data["client_secret"] = settings.beatport_client_secret
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                _token_url(),
                data=data,
            )
            response.raise_for_status()
            token_data = _parse_token_response(response.json())

        user.beatport_access_token = token_data["access_token"]
        if "refresh_token" in token_data:
            user.beatport_refresh_token = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", DEFAULT_TOKEN_EXPIRY)
        user.beatport_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        db.commit()
        return True
    except (httpx.HTTPError, ValueError) as e:
        logger.error("Beatport token refresh failed: %s", type(e).__name__)
        return False


def save_tokens(db: Session, user: User, token_data: BeatportTokenResponse) -> None:
    """Save Beatport OAuth tokens to the user model and fetch subscription."""
    user.beatport_access_token = token_data["access_token"]
    user.beatport_refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", DEFAULT_TOKEN_EXPIRY)
    user.beatport_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    # Clean up temporary PKCE values now that we have real tokens
    user.beatport_oauth_state = None
    user.beatport_oauth_code_verifier = None

    db.commit()

    # Best-effort subscription fetch on login
    fetch_subscription_type(db, user)


def disconnect_beatport(db: Session, user: User) -> None:
    """Revoke Beatport token and clear all tokens from user."""
    # Best-effort token revocation — don't fail if it errors
    if user.beatport_access_token:
        settings = get_settings()
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                client.post(
                    _revoke_url(),
                    data={
                        "client_id": settings.beatport_client_id,
                        "token": user.beatport_access_token,
                    },
                )
        except httpx.HTTPError as e:
            logger.error("Beatport token revocation failed: %s", type(e).__name__)

    user.beatport_access_token = None
    user.beatport_refresh_token = None
    user.beatport_token_expires_at = None
    user.beatport_subscription = None
    db.commit()


def fetch_subscription_type(db: Session, user: User) -> str | None:
    """Fetch the user's Beatport subscription type and store it."""
    if not ensure_beatport_token(db, user):
        return None

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/account/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()

        # Beatport account API has no explicit "subscription" field.
        # Detect streaming access via preferences.streaming_audio_format_id.
        streaming_format = data.get("preferences", {}).get("streaming_audio_format_id")
        subscription = "streaming" if streaming_format else None
        user.beatport_subscription = subscription
        db.commit()
        return subscription
    except httpx.HTTPError as e:
        logger.error("Beatport subscription fetch failed: %s", type(e).__name__)
        return None

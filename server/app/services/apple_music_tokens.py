"""Apple Music developer credentials and short-lived token signing."""

import logging
import re
import time

import httpx
import jwt

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEVELOPER_TOKEN_TTL_SECONDS = 15 * 60
APPLE_MUSIC_API_BASE = "https://api.music.apple.com/v1"
HTTP_TIMEOUT_SECONDS = 10
_APPLE_IDENTIFIER_RE = re.compile(r"^[A-Z0-9]{10}$")


class AppleMusicError(Exception):
    """Apple Music configuration or API failure."""


class AppleMusicNotConfigured(AppleMusicError):
    """Deployment credentials are incomplete or Apple's key cannot sign tokens."""


class AppleMusicUserAuthorizationError(AppleMusicError):
    """Apple rejected the DJ's Music User Token; the DJ must link again."""


class AppleMusicNotConnected(AppleMusicError):
    """The DJ has no usable connected Apple Music account."""


class AppleMusicNotFound(AppleMusicError):
    """Apple could not find a requested catalog resource."""


class AppleMusicLinkSuperseded(AppleMusicError):
    """A newer connect or disconnect operation invalidated this link attempt."""


class AppleMusicRequestUncertain(AppleMusicError):
    """A write request may have reached Apple but returned no reliable outcome."""


def apple_post(
    path: str,
    developer_token: str,
    *,
    music_user_token: str,
    json_body: dict[str, object],
) -> dict[str, object]:
    """Create an Apple resource once, preserving ambiguity after transport/server errors."""
    headers = {
        "Authorization": f"Bearer {developer_token}",
        "Music-User-Token": music_user_token,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(f"{APPLE_MUSIC_API_BASE}{path}", headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        raise AppleMusicRequestUncertain from exc
    if response.status_code == 401:
        raise AppleMusicNotConfigured
    if response.status_code == 403:
        raise AppleMusicUserAuthorizationError
    if response.status_code >= 500:
        raise AppleMusicRequestUncertain
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        if response.is_success:
            raise AppleMusicRequestUncertain from exc
        raise AppleMusicError("Apple Music rejected the playlist request") from exc
    if not isinstance(payload, dict):
        raise AppleMusicRequestUncertain
    return payload


def apple_get(
    path: str,
    developer_token: str,
    *,
    music_user_token: str | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    """Issue an Apple Music API request with deployment and optional user credentials."""
    headers = {"Authorization": f"Bearer {developer_token}"}
    if music_user_token:
        headers["Music-User-Token"] = music_user_token
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.get(f"{APPLE_MUSIC_API_BASE}{path}", headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise AppleMusicError("Apple Music request failed") from exc
    if response.status_code == 401:
        raise AppleMusicNotConfigured
    if response.status_code == 403 and music_user_token:
        raise AppleMusicUserAuthorizationError
    if response.status_code == 404:
        raise AppleMusicNotFound("Apple Music resource was not found")
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AppleMusicError("Apple Music request failed") from exc
    if not isinstance(payload, dict):
        raise AppleMusicError("Apple Music returned an invalid response")
    return payload


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        _APPLE_IDENTIFIER_RE.fullmatch(settings.apple_music_team_id)
        and _APPLE_IDENTIFIER_RE.fullmatch(settings.apple_music_key_id)
        and settings.apple_music_private_key
    )


def create_developer_token(
    settings: Settings | None = None, *, now: int | None = None
) -> tuple[str, int]:
    """Sign a short-lived Apple developer token without returning signing material."""
    settings = settings or get_settings()
    if not is_configured(settings):
        raise AppleMusicNotConfigured
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + DEVELOPER_TOKEN_TTL_SECONDS
    private_key = settings.apple_music_private_key.replace("\\n", "\n")
    claims: dict[str, object] = {
        "iss": settings.apple_music_team_id,
        "iat": issued_at,
        "exp": expires_at,
    }
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if origins and "*" not in origins:
        claims["origin"] = origins
    try:
        token = jwt.encode(
            claims,
            private_key,
            algorithm="ES256",
            headers={"kid": settings.apple_music_key_id},
        )
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        logger.warning("Apple Music developer token signing failed: %s", type(exc).__name__)
        raise AppleMusicNotConfigured from exc
    return token, expires_at

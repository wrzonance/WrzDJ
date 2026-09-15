"""Beatport API v4 integration for catalog search and playlist sync.

Uses server-side OAuth2 login flow: POST credentials to Beatport's login
endpoint, then exchange the resulting authorization code for tokens.
This avoids the cross-origin postMessage issues with Beatport's popup flow
(which is designed for Swagger UI only).

Track search, catalog access, and playlist CRUD are supported.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request as SongRequest
from app.models.search_cache import SearchCache
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult

logger = logging.getLogger(__name__)

BEATPORT_API_BASE = "https://api.beatport.com/v4"
BEATPORT_TRACK_URL = "https://www.beatport.com/track/{slug}/{track_id}"

# HTTP timeout for Beatport API calls
HTTP_TIMEOUT = 15.0

# Default token lifetime (Beatport docs say 600s / 10 min)
DEFAULT_TOKEN_EXPIRY = 600


_BEATPORT_ID_RE = re.compile(r"^[0-9]{1,20}$")


def _is_valid_beatport_id(value: str) -> bool:
    """Beatport catalog and playlist IDs are decimal integers.

    Anything else must never be interpolated into an API path: a value such as
    ``../search/?q=`` would redirect the caller's bearer token to a different
    Beatport endpoint (CodeQL py/partial-ssrf).
    """
    return bool(_BEATPORT_ID_RE.fullmatch(str(value)))


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


def login_and_get_tokens(username: str, password: str) -> dict:  # nosec B107
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
        return token_resp.json()


def _refresh_token_if_needed(db: Session, user: User) -> bool:
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
            token_data = response.json()

        user.beatport_access_token = token_data["access_token"]
        if "refresh_token" in token_data:
            user.beatport_refresh_token = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", DEFAULT_TOKEN_EXPIRY)
        user.beatport_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        db.commit()
        return True
    except httpx.HTTPError as e:
        logger.error("Beatport token refresh failed: %s", type(e).__name__)
        return False


def save_tokens(db: Session, user: User, token_data: dict) -> None:
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


@dataclass
class BeatportPlaylistInfo:
    """Beatport playlist metadata."""

    id: str
    name: str
    num_tracks: int
    description: str | None = None
    cover_url: str | None = None
    source: str = "beatport"


def list_user_playlists(db: Session, user: User) -> list[BeatportPlaylistInfo]:
    """List user's Beatport playlists."""
    if not _refresh_token_if_needed(db, user):
        return []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/playlists/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport playlist listing failed: %s", type(e).__name__)
        return []

    results = []
    for p in data.get("results", []):
        cover_url = None
        if p.get("image"):
            cover_url = p["image"].get("uri")
        results.append(
            BeatportPlaylistInfo(
                id=str(p.get("id", "")),
                name=p.get("name", ""),
                num_tracks=p.get("track_count", 0),
                description=p.get("description"),
                cover_url=cover_url,
            )
        )
    return results


def get_playlist_tracks(db: Session, user: User, playlist_id: str) -> list[BeatportSearchResult]:
    """Get all tracks from a Beatport playlist as BeatportSearchResult objects."""
    if not _is_valid_beatport_id(playlist_id):
        logger.warning("Rejected malformed Beatport playlist id")
        return []
    if not _refresh_token_if_needed(db, user):
        return []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/playlists/{playlist_id}/tracks/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport playlist tracks fetch failed: %s", type(e).__name__)
        return []

    results = []
    for entry in data.get("results", []):
        track = entry.get("track", entry)
        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
        genre_name = None
        if track.get("genre"):
            genre_name = track["genre"].get("name")

        track_id = str(track.get("id", ""))
        slug = track.get("slug", "untitled")
        beatport_url = BEATPORT_TRACK_URL.format(slug=slug, track_id=track_id)

        cover_url = None
        if track.get("image"):
            cover_url = track["image"].get("uri")

        results.append(
            BeatportSearchResult(
                track_id=track_id,
                title=track.get("name", ""),
                artist=artists,
                mix_name=track.get("mix_name"),
                label=track.get("label", {}).get("name") if track.get("label") else None,
                genre=genre_name,
                bpm=track.get("bpm"),
                key=track.get("key", {}).get("name") if track.get("key") else None,
                duration_seconds=_parse_duration(track.get("length")),
                cover_url=cover_url,
                beatport_url=beatport_url,
                release_date=track.get("new_release_date") or track.get("publish_date"),
            )
        )
    return results


def search_beatport_tracks(
    db: Session, user: User, query: str, limit: int = 10
) -> list[BeatportSearchResult]:
    """Search Beatport catalog for tracks with caching."""
    settings = get_settings()
    cache_key = query.strip().lower()

    # Check cache first
    cached = (
        db.query(SearchCache)
        .filter(
            SearchCache.query == cache_key,
            SearchCache.source == "beatport",
            SearchCache.expires_at > utcnow(),
        )
        .first()
    )
    if cached:
        results_data = json.loads(cached.results_json)
        return [BeatportSearchResult(**r) for r in results_data]

    if not _refresh_token_if_needed(db, user):
        return []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/catalog/search/",
                params={"q": query, "per_page": limit, "type": "tracks"},
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport search failed: %s", type(e).__name__)
        return []

    results = []
    for track in data.get("tracks", []):
        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
        genre_name = None
        if track.get("genre"):
            genre_name = track["genre"].get("name")

        # Build Beatport URL from slug and ID
        track_id = str(track.get("id", ""))
        slug = track.get("slug", "untitled")
        beatport_url = BEATPORT_TRACK_URL.format(slug=slug, track_id=track_id)

        # Cover art
        cover_url = None
        if track.get("image"):
            cover_url = track["image"].get("uri")

        results.append(
            BeatportSearchResult(
                track_id=track_id,
                title=track.get("name", ""),
                artist=artists,
                mix_name=track.get("mix_name"),
                label=track.get("label", {}).get("name") if track.get("label") else None,
                genre=genre_name,
                bpm=track.get("bpm"),
                key=track.get("key", {}).get("name") if track.get("key") else None,
                duration_seconds=_parse_duration(track.get("length")),
                cover_url=cover_url,
                beatport_url=beatport_url,
                release_date=track.get("new_release_date") or track.get("publish_date"),
            )
        )

    # Cache the results
    if results:
        expires_at = utcnow() + timedelta(hours=settings.search_cache_hours)
        results_json = json.dumps([r.model_dump() for r in results])

        existing = (
            db.query(SearchCache)
            .filter(SearchCache.query == cache_key, SearchCache.source == "beatport")
            .first()
        )
        if existing:
            existing.results_json = results_json
            existing.expires_at = expires_at
            existing.created_at = utcnow()
        else:
            cache_entry = SearchCache(
                query=cache_key,
                source="beatport",
                results_json=results_json,
                expires_at=expires_at,
            )
            db.add(cache_entry)
        db.commit()

    return results


def browse_beatport_tracks(
    db: Session,
    user: User,
    genre_id: int,
    bpm_min: int | None = None,
    bpm_max: int | None = None,
    key: str | None = None,
    limit: int = 10,
) -> list[BeatportSearchResult]:
    """Browse Beatport catalog with structured genre/BPM/key filters.

    Uses GET /v4/catalog/tracks/ instead of text search for precise filtering.
    Results are cached like search results.
    """
    settings = get_settings()

    # Build cache key from structured params
    parts = [f"browse:g{genre_id}"]
    if bpm_min is not None and bpm_max is not None:
        parts.append(f"b{bpm_min}-{bpm_max}")
    if key:
        parts.append(f"k{key}")
    cache_key = ":".join(parts)

    # Check cache first
    cached = (
        db.query(SearchCache)
        .filter(
            SearchCache.query == cache_key,
            SearchCache.source == "beatport",
            SearchCache.expires_at > utcnow(),
        )
        .first()
    )
    if cached:
        results_data = json.loads(cached.results_json)
        return [BeatportSearchResult(**r) for r in results_data]

    if not _refresh_token_if_needed(db, user):
        return []

    params: dict[str, str | int] = {
        "genre_id": genre_id,
        "per_page": limit,
        "order_by": "-publish_date",
    }
    if bpm_min is not None:
        params["bpm_min"] = bpm_min
    if bpm_max is not None:
        params["bpm_max"] = bpm_max
    if key:
        params["key"] = key

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/catalog/tracks/",
                params=params,
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport browse failed: %s", type(e).__name__)
        return []

    results = []
    for track in data.get("results", []):
        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
        genre_name = None
        if track.get("genre"):
            genre_name = track["genre"].get("name")

        track_id_str = str(track.get("id", ""))
        slug = track.get("slug", "untitled")
        beatport_url = BEATPORT_TRACK_URL.format(slug=slug, track_id=track_id_str)

        cover_url = None
        if track.get("image"):
            cover_url = track["image"].get("uri")

        # Beatport browse returns key as nested object with camelot fields
        key_data = track.get("key")
        key_str = None
        if key_data:
            camelot_num = key_data.get("camelot_number")
            camelot_let = key_data.get("camelot_letter")
            if camelot_num and camelot_let:
                key_str = f"{camelot_num}{camelot_let}"
            elif key_data.get("name"):
                key_str = key_data["name"]

        results.append(
            BeatportSearchResult(
                track_id=track_id_str,
                title=track.get("name", ""),
                artist=artists,
                mix_name=track.get("mix_name"),
                label=track.get("label", {}).get("name") if track.get("label") else None,
                genre=genre_name,
                bpm=track.get("bpm"),
                key=key_str,
                duration_seconds=_parse_duration(track.get("length")),
                cover_url=cover_url,
                beatport_url=beatport_url,
                release_date=track.get("new_release_date") or track.get("publish_date"),
            )
        )

    # Cache the results
    if results:
        expires_at = utcnow() + timedelta(hours=settings.search_cache_hours)
        results_json = json.dumps([r.model_dump() for r in results])

        existing = (
            db.query(SearchCache)
            .filter(SearchCache.query == cache_key, SearchCache.source == "beatport")
            .first()
        )
        if existing:
            existing.results_json = results_json
            existing.expires_at = expires_at
            existing.created_at = utcnow()
        else:
            cache_entry = SearchCache(
                query=cache_key,
                source="beatport",
                results_json=results_json,
                expires_at=expires_at,
            )
            db.add(cache_entry)
        db.commit()

    return results


def get_beatport_track(db: Session, user: User, track_id: str) -> BeatportSearchResult | None:
    """Fetch a single track from Beatport by ID."""
    if not _is_valid_beatport_id(track_id):
        logger.warning("Rejected malformed Beatport track id")
        return None
    if not _refresh_token_if_needed(db, user):
        return None

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/catalog/tracks/{track_id}/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            track = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport track fetch failed: %s", type(e).__name__)
        return None

    artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
    genre_name = None
    if track.get("genre"):
        genre_name = track["genre"].get("name")

    slug = track.get("slug", "untitled")
    beatport_url = BEATPORT_TRACK_URL.format(slug=slug, track_id=track_id)

    cover_url = None
    if track.get("image"):
        cover_url = track["image"].get("uri")

    return BeatportSearchResult(
        track_id=str(track.get("id", track_id)),
        title=track.get("name", ""),
        artist=artists,
        mix_name=track.get("mix_name"),
        label=track.get("label", {}).get("name") if track.get("label") else None,
        genre=genre_name,
        bpm=track.get("bpm"),
        key=track.get("key", {}).get("name") if track.get("key") else None,
        duration_seconds=_parse_duration(track.get("length")),
        cover_url=cover_url,
        beatport_url=beatport_url,
        release_date=track.get("new_release_date") or track.get("publish_date"),
    )


def _parse_duration(length_str: str | None) -> int | None:
    """Parse Beatport duration string (e.g., '5:30' or '05:30') to seconds."""
    if not length_str:
        return None
    try:
        parts = length_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        pass
    return None


def create_beatport_playlist(db: Session, user: User, event: Event) -> str | None:
    """Create a Beatport playlist for an event. Returns playlist ID or None."""
    if event.beatport_playlist_id:
        return event.beatport_playlist_id

    if not _refresh_token_if_needed(db, user):
        return None

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{BEATPORT_API_BASE}/my/playlists/",
                json={"name": f"WrzDJ: {event.name}"},
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()

        playlist_id = str(data["id"])
        event.beatport_playlist_id = playlist_id
        db.commit()
        logger.info("Created Beatport playlist %s for event %s", playlist_id, event.code)
        return playlist_id
    except httpx.HTTPError as e:
        logger.error("Beatport playlist creation failed: %s", type(e).__name__)
        return None


def _get_playlist_track_ids(user: User, playlist_id: str) -> set[str]:
    """Fetch the set of track IDs already on a Beatport playlist."""
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/playlists/{playlist_id}/tracks/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
        return {str(entry["track"]["id"]) for entry in data.get("results", [])}
    except (httpx.HTTPError, KeyError, TypeError) as e:
        logger.error("Beatport playlist fetch failed: %s", type(e).__name__)
        return set()


def add_track_to_beatport_playlist(
    db: Session, user: User, playlist_id: str, track_id: str
) -> bool:
    """Add a single track to a Beatport playlist. Skips if already present."""
    if not _refresh_token_if_needed(db, user):
        return False

    existing = _get_playlist_track_ids(user, playlist_id)
    if track_id in existing:
        logger.info("Track %s already on Beatport playlist %s, skipping", track_id, playlist_id)
        return True

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{BEATPORT_API_BASE}/my/playlists/{playlist_id}/tracks/",
                json={"track_id": int(track_id)},
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
        logger.info("Added track %s to Beatport playlist %s", track_id, playlist_id)
        return True
    except httpx.HTTPError as e:
        logger.error("Beatport add track failed: %s", type(e).__name__)
        return False


def add_tracks_to_beatport_playlist(
    db: Session, user: User, playlist_id: str, track_ids: list[str]
) -> bool:
    """Add multiple tracks to a Beatport playlist (one request per track)."""
    if not track_ids:
        return True

    return all(add_track_to_beatport_playlist(db, user, playlist_id, tid) for tid in track_ids)


def fetch_subscription_type(db: Session, user: User) -> str | None:
    """Fetch the user's Beatport subscription type and store it."""
    if not _refresh_token_if_needed(db, user):
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


def manual_link_beatport_track(
    db: Session,
    request: SongRequest,
    track: BeatportSearchResult,
) -> None:
    """Manually link a Beatport track to a request.

    Updates the sync_results_json with a 'matched' entry for Beatport,
    replacing any existing Beatport entry.
    """
    existing: list[dict] = []
    if request.sync_results_json:
        try:
            parsed = json.loads(request.sync_results_json)
            existing = parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            existing = []

    # Remove old Beatport entry if any
    existing = [r for r in existing if r.get("service") != "beatport"]
    existing.append(
        {
            "service": "beatport",
            "status": "matched",
            "track_id": track.track_id,
            "track_title": track.title,
            "track_artist": track.artist,
            "confidence": 1.0,
            "url": track.beatport_url,
            "duration_seconds": track.duration_seconds,
            "playlist_id": None,
            "error": None,
        }
    )
    request.sync_results_json = json.dumps(existing)
    db.commit()

"""Beatport track search, structured browse, and direct catalog lookup."""

import json
import logging
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models.search_cache import SearchCache
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.services.providers.beatport_account import ensure_beatport_token
from app.services.providers.beatport_common import (
    BEATPORT_API_BASE,
    HTTP_TIMEOUT,
    is_valid_beatport_id,
)
from app.services.providers.beatport_mapping import beatport_track_to_result

logger = logging.getLogger(__name__)


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

    if not ensure_beatport_token(db, user):
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

    results = [beatport_track_to_result(track) for track in data.get("tracks", [])]

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

    if not ensure_beatport_token(db, user):
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
        # Browse returns a Camelot key rather than the nested `name` used by
        # search/detail/playlist payloads. Normalize a copy before common mapping.
        key_data = track.get("key")
        key_name = None
        if key_data:
            camelot_num = key_data.get("camelot_number")
            camelot_let = key_data.get("camelot_letter")
            if camelot_num and camelot_let:
                key_name = f"{camelot_num}{camelot_let}"
            elif key_data.get("name"):
                key_name = key_data["name"]
        normalized_track = {**track, "key": {"name": key_name}} if key_data else track
        results.append(beatport_track_to_result(normalized_track))

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
    track_id = str(track_id)
    if not is_valid_beatport_id(track_id):
        logger.warning("Rejected malformed Beatport track id")
        return None
    if not ensure_beatport_token(db, user):
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

    return beatport_track_to_result(track, fallback_track_id=track_id, url_track_id=track_id)

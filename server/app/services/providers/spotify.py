import json
import logging
import threading
import time
from datetime import timedelta

import spotipy
from requests.exceptions import ReadTimeout, Timeout
from spotipy.oauth2 import SpotifyClientCredentials
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models.search_cache import SearchCache
from app.schemas.search import SearchResult

logger = logging.getLogger(__name__)

# Timeout settings (connect, read)
SPOTIFY_TIMEOUT = (5, 10)  # 5s connect, 10s read
MAX_RETRIES = 2
INITIAL_BACKOFF = 0.5  # seconds
SEARCH_PAGE_SIZE = 10  # Spotify Development Mode limit since February 2026
SEARCH_RESULT_LIMIT = 20
# Share the former single-page connect/read and backoff allowance across both pages.
SEARCH_TIME_BUDGET = (MAX_RETRIES + 1) * sum(SPOTIFY_TIMEOUT) + INITIAL_BACKOFF * (
    2**MAX_RETRIES - 1
)

# Initialize Spotify client with client credentials flow (thread-safe)
_sp: spotipy.Spotify | None = None
_sp_lock = threading.Lock()


def get_spotify_client() -> spotipy.Spotify:
    """Get or create the Spotify client (double-checked locking)."""
    global _sp
    settings = get_settings()
    if _sp is not None:
        return _sp
    with _sp_lock:
        if _sp is not None:
            return _sp
        if not settings.spotify_client_id or not settings.spotify_client_secret:
            raise ValueError(
                "Spotify credentials not configured. "
                "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env file."
            )
        auth_manager = SpotifyClientCredentials(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
        )
        _sp = spotipy.Spotify(
            auth_manager=auth_manager,
            requests_timeout=SPOTIFY_TIMEOUT,
        )
    return _sp


def search_songs(db: Session, query: str) -> list[SearchResult]:
    """Search for songs using Spotify API with caching."""
    settings = get_settings()
    query = query.strip().lower()
    if not query:
        return []

    # Check cache first
    cached = (
        db.query(SearchCache)
        .filter(
            SearchCache.query == query,
            SearchCache.source == "spotify",
            SearchCache.expires_at > utcnow(),
        )
        .first()
    )
    if cached:
        results_data = json.loads(cached.results_json)
        # Older versions cached API failures as empty results. Retry those immediately.
        if results_data:
            return [SearchResult(**r) for r in results_data]

    # Call Spotify API
    results = search_spotify_api(query)
    if not results:
        return []

    # Cache the results
    expires_at = utcnow() + timedelta(hours=settings.search_cache_hours)
    results_json = json.dumps([r.model_dump() for r in results])

    # Upsert cache entry
    existing = (
        db.query(SearchCache)
        .filter(SearchCache.query == query, SearchCache.source == "spotify")
        .first()
    )
    if existing:
        existing.results_json = results_json
        existing.expires_at = expires_at
        existing.created_at = utcnow()
    else:
        cache_entry = SearchCache(
            query=query, source="spotify", results_json=results_json, expires_at=expires_at
        )
        db.add(cache_entry)
    db.commit()

    return results


def search_spotify_api(query: str) -> list[SearchResult]:
    """Fetch up to 20 candidates using Spotify's 10-result search pages."""
    sp = get_spotify_client()
    deadline = time.monotonic() + SEARCH_TIME_BUDGET
    tracks = []
    for offset in range(0, SEARCH_RESULT_LIMIT, SEARCH_PAGE_SIZE):
        response = _fetch_spotify_page(sp, query, offset, deadline)
        if response is None:
            # Do not cache an incomplete search as the full result set.
            return []
        page = response.get("tracks", {})
        items = page.get("items", [])
        tracks.extend(items)
        if not items or not page.get("next"):
            break
    return _parse_spotify_tracks(tracks)


def _fetch_spotify_page(
    sp: spotipy.Spotify, query: str, offset: int, deadline: float
) -> dict | None:
    """Retry only the current page so earlier results are not requested again."""
    response = None
    last_exception_type: str | None = None

    for attempt in range(MAX_RETRIES + 1):
        # Reserve a full connect/read allowance before starting another request.
        if time.monotonic() + sum(SPOTIFY_TIMEOUT) > deadline:
            logger.warning("Spotify search time budget exhausted")
            return None
        try:
            response = sp.search(q=query, type="track", limit=SEARCH_PAGE_SIZE, offset=offset)
            break
        except (Timeout, ReadTimeout) as e:
            last_exception_type = type(e).__name__
            if attempt < MAX_RETRIES:
                backoff = INITIAL_BACKOFF * (2**attempt)
                logger.warning(
                    f"Spotify API timeout (attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                    f"retrying in {backoff}s ({last_exception_type})"
                )
                time.sleep(backoff)
            else:
                logger.error(
                    "Spotify API timeout after %s attempts (%s)",
                    MAX_RETRIES + 1,
                    last_exception_type,
                )
        except Exception as e:
            logger.error("Spotify API error: %s", type(e).__name__)
            return None

    if response is None:
        logger.error("Spotify API failed after retries: %s", last_exception_type)
    return response


def _parse_spotify_tracks(tracks: list[dict]) -> list[SearchResult]:
    """Preserve Spotify's candidate order and the existing metadata mapping."""
    results = []
    for track in tracks:
        title = track.get("name", "")
        spotify_id = track.get("id")
        popularity = track.get("popularity", 0)
        preview_url = track.get("preview_url")

        # Get artist name (join all artists, not just first)
        artists = track.get("artists", [])
        artist = (
            ", ".join(a.get("name", "") for a in artists if a.get("name"))
            if artists
            else "Unknown Artist"
        ) or "Unknown Artist"

        # Get album info
        album = track.get("album", {})
        album_name = album.get("name")

        # Get album art (prefer 300x300, fall back to first available)
        album_art = None
        images = album.get("images", [])
        if images:
            # Images are sorted by size descending, try to get medium size
            for img in images:
                if img.get("width") == 300 or img.get("height") == 300:
                    album_art = img.get("url")
                    break
            if not album_art:
                album_art = images[0].get("url")

        if title and artist:
            url = f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None
            isrc = track.get("external_ids", {}).get("isrc")
            results.append(
                SearchResult(
                    artist=artist,
                    title=title,
                    album=album_name,
                    popularity=popularity,
                    spotify_id=spotify_id,
                    album_art=album_art,
                    preview_url=preview_url,
                    url=url,
                    isrc=isrc,
                )
            )

    return results

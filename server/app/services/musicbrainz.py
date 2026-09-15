"""MusicBrainz API client for artist genre enrichment.

Provides artist-level genre tags from MusicBrainz's community-contributed
database. Used as a fallback when search results (e.g., from Spotify/Tidal)
don't include genre metadata.

MusicBrainz API:
- Base URL: https://musicbrainz.org/ws/2/
- Auth: None (free, public)
- Rate limit: 1 request/second (must include User-Agent per TOS)
- Format: JSON via ?fmt=json
"""

import logging
import threading
import time

import httpx

from app.services.track_normalizer import fuzzy_match_score
from app.services.track_normalizer import primary_artist as _primary_artist

logger = logging.getLogger(__name__)

MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "WrzDJ/1.0 (https://github.com/wrzdjband/WrzDJ)"
HTTP_TIMEOUT = 10.0


class _Throttle:
    """Thread-safe pacing for MusicBrainz's 1 request/second limit."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_request_time = 0.0

    def wait(self) -> None:
        with self.lock:
            elapsed = time.monotonic() - self.last_request_time
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            self.last_request_time = time.monotonic()


_throttle = _Throttle()


def _throttled_get(url: str, params: dict) -> dict | None:
    """GET with 1 req/sec throttle and User-Agent header.

    Returns parsed JSON or None on any error.
    """
    _throttle.wait()

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.warning("MusicBrainz request failed: %s", type(e).__name__)
        return None


def check_artist_exists(artist_name: str) -> tuple[bool, str | None]:
    """Check if an artist exists on MusicBrainz (search only, no genre detail).

    Returns (True, mbid) if an artist with score >= 90 is found,
    otherwise (False, None).  Uses a single API call.
    """
    if not artist_name or not artist_name.strip():
        return False, None

    search_data = _throttled_get(
        f"{MUSICBRAINZ_BASE}/artist/",
        {"query": f"artist:{artist_name}", "fmt": "json", "limit": "3"},
    )
    if not search_data:
        return False, None

    # Known false-positive names that MB returns with high scores for almost any query
    _FALSE_POSITIVE_NAMES = {"various artists", "[unknown]"}

    # Disambiguation strings that indicate stock/library music producers
    _STOCK_DISAMBIGUATIONS = {
        "royalty-free",
        "royalty free",
        "production music",
        "stock music",
        "library music",
        "background music",
    }

    for artist in search_data.get("artists", []):
        if artist.get("score", 0) >= 90:
            result_name = artist.get("name", "")
            # Reject known false-positive entries
            if result_name.lower() in _FALSE_POSITIVE_NAMES:
                continue
            # Reject if the result name doesn't actually match the query
            # (MB's score measures index relevance, not name similarity)
            if fuzzy_match_score(artist_name, result_name) < 0.7:
                continue
            # Reject stock/library music producers by disambiguation field
            disambiguation = artist.get("disambiguation", "").lower()
            if any(kw in disambiguation for kw in _STOCK_DISAMBIGUATIONS):
                continue
            mbid = artist.get("id")
            if mbid:
                return True, mbid

    return False, None


def lookup_artist_genre(artist_name: str) -> str | None:
    """Search MusicBrainz for an artist and return their top genre tag.

    Returns the genre with the highest vote count, or None if not found.
    """
    genres = lookup_artist_genres(artist_name)
    return genres[0] if genres else None


def lookup_artist_genres(artist_name: str) -> list[str]:
    """Return all genres for an artist, sorted by vote count descending.

    Steps:
    1. Search for artist by name
    2. Pick the best match (score > 90)
    3. Lookup artist record with genre includes
    4. Return genres sorted by count
    """
    if not artist_name or not artist_name.strip():
        return []

    # Step 1: Search for artist
    search_data = _throttled_get(
        f"{MUSICBRAINZ_BASE}/artist/",
        {"query": f"artist:{_primary_artist(artist_name)}", "fmt": "json", "limit": "3"},
    )
    if not search_data:
        return []

    artists = search_data.get("artists", [])
    if not artists:
        return []

    # Step 2: Pick best match (score > 90)
    best = None
    for artist in artists:
        score = artist.get("score", 0)
        if score >= 90:
            best = artist
            break

    if not best:
        return []

    mbid = best.get("id")
    if not mbid:
        return []

    # Step 3: Lookup artist with genres
    artist_data = _throttled_get(
        f"{MUSICBRAINZ_BASE}/artist/{mbid}",
        {"inc": "genres", "fmt": "json"},
    )
    if not artist_data:
        return []

    # Step 4: Sort genres by count and return names
    genres = artist_data.get("genres", [])
    if not genres:
        return []

    sorted_genres = sorted(genres, key=lambda g: g.get("count", 0), reverse=True)
    return [g["name"] for g in sorted_genres if g.get("name")]

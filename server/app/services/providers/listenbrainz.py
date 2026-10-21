"""ListenBrainz API client for artist popularity and discovery.

Provides:
- Batch artist popularity lookups (stock/AI detection)
- LB Radio discovery (similar artists + tag-based track recommendations)

ListenBrainz API:
- Base URL: https://api.listenbrainz.org
- Auth: User token required for explore/radio endpoints
- Rate limit: generous (no explicit per-second throttle needed)
- Format: JSON
"""

import logging
from dataclasses import dataclass

import httpx

from app.services.providers.identity import WRZDJ_USER_AGENT

logger = logging.getLogger(__name__)

LISTENBRAINZ_BASE = "https://api.listenbrainz.org"
HTTP_TIMEOUT = 15.0
USER_AGENT = WRZDJ_USER_AGENT


@dataclass(frozen=True)
class LBRadioTrack:
    """A track discovered via ListenBrainz Radio."""

    title: str
    artist: str
    recording_mbid: str | None = None


def fetch_artist_popularity(mbids: list[str]) -> dict[str, dict]:
    """Batch-fetch artist popularity from ListenBrainz.

    Args:
        mbids: List of MusicBrainz artist IDs (up to 100).

    Returns:
        Mapping of mbid -> {"total_listen_count": int|None, "total_user_count": int|None}.
        Returns empty dict on any error (callers treat missing as pass-through).
    """
    if not mbids:
        return {}

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{LISTENBRAINZ_BASE}/1/popularity/artists",
                json={"artist_mbids": mbids[:100]},
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ListenBrainz popularity request failed: %s", type(e).__name__)
        return {}

    if not isinstance(data, list):
        logger.warning("ListenBrainz returned unexpected format: %s", type(data).__name__)
        return {}

    result: dict[str, dict] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        mbid = entry.get("artist_mbid")
        if not mbid:
            continue
        result[mbid] = {
            "total_listen_count": entry.get("total_listen_count"),
            "total_user_count": entry.get("total_user_count"),
        }

    return result


def _get_lb_token() -> str | None:
    """Get the ListenBrainz user token from settings."""
    from app.core.config import get_settings

    token = get_settings().listenbrainz_user_token
    return token if token else None


def lb_radio_discover(
    prompt: str,
    mode: str = "easy",
) -> list[LBRadioTrack]:
    """Discover tracks via ListenBrainz Radio.

    Prompt formats:
    - "artist:(Darude)" — similar artists to Darude
    - "tag:(trance)" — tracks tagged with trance
    - "artist:(Darude) tag:(trance)" — combined

    Modes: "easy" (popular tracks), "medium", "hard" (deeper cuts).

    Returns list of discovered tracks. Returns empty list on any error.
    """
    token = _get_lb_token()
    if not token:
        logger.debug("ListenBrainz token not configured, skipping LB Radio")
        return []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{LISTENBRAINZ_BASE}/1/explore/lb-radio",
                params={"prompt": prompt, "mode": mode},
                headers={
                    "Authorization": f"Token {token}",
                    "User-Agent": USER_AGENT,
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("LB Radio request failed: %s", type(e).__name__)
        return []

    if not isinstance(data, dict):
        logger.warning("LB Radio returned unexpected format: %s", type(data).__name__)
        return []

    payload = data.get("payload")
    jspf = payload.get("jspf") if isinstance(payload, dict) else None
    playlist = jspf.get("playlist") if isinstance(jspf, dict) else None
    if not isinstance(playlist, dict):
        logger.warning("LB Radio returned unexpected playlist format")
        return []

    entries = playlist.get("track", [])
    if not isinstance(entries, list):
        logger.warning("LB Radio returned unexpected track format: %s", type(entries).__name__)
        return []

    tracks: list[LBRadioTrack] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        artist = entry.get("creator")
        if not isinstance(title, str) or not title or not isinstance(artist, str) or not artist:
            continue

        # Extract recording MBID from identifier URLs
        recording_mbid = None
        identifiers = entry.get("identifier", [])
        if isinstance(identifiers, list):
            for ident in identifiers:
                if isinstance(ident, str) and "/recording/" in ident:
                    recording_mbid = ident.rsplit("/", 1)[-1]
                    break

        tracks.append(
            LBRadioTrack(
                title=title,
                artist=artist,
                recording_mbid=recording_mbid,
            )
        )

    logger.info("LB Radio discovered %d tracks for prompt=%s mode=%s", len(tracks), prompt, mode)
    return tracks

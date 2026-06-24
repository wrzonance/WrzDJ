"""Soundcharts API client for genre/BPM/key-filtered song discovery.

Uses the POST /api/v2/top/songs endpoint to find tracks matching an
event's musical profile. Returns artist+title pairs for resolution
to playable Tidal track IDs.

API docs: https://developers.soundcharts.com/documentation/reference/song/get-songs
Free tier: 1000 calls/month (1 call per recommendation generation).
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.services.recommendation.camelot import parse_key

logger = logging.getLogger(__name__)

BASE_URL = "https://customer.api.soundcharts.com"
REQUEST_TIMEOUT = 15

# Song endpoints (audio features, ISRC lookup) live under the v2.25 API.
SONG_API_BASE = f"{BASE_URL}/api/v2.25/song"


# Camelot position → (pitch_class 0-11, mode 0=minor/1=major)
# Derived from _KEY_DEFINITIONS in camelot.py
_CAMELOT_TO_PITCH: dict[tuple[int, str], tuple[int, int]] = {
    # Minor keys (A ring) — mode=0
    (1, "A"): (8, 0),  # Ab/G# minor
    (2, "A"): (3, 0),  # Eb/D# minor
    (3, "A"): (10, 0),  # Bb/A# minor
    (4, "A"): (5, 0),  # F minor
    (5, "A"): (0, 0),  # C minor
    (6, "A"): (7, 0),  # G minor
    (7, "A"): (2, 0),  # D minor
    (8, "A"): (9, 0),  # A minor
    (9, "A"): (4, 0),  # E minor
    (10, "A"): (11, 0),  # B minor
    (11, "A"): (6, 0),  # F#/Gb minor
    (12, "A"): (1, 0),  # Db/C# minor
    # Major keys (B ring) — mode=1
    (1, "B"): (11, 1),  # B major
    (2, "B"): (6, 1),  # F#/Gb major
    (3, "B"): (1, 1),  # Db/C# major
    (4, "B"): (8, 1),  # Ab/G# major
    (5, "B"): (3, 1),  # Eb/D# major
    (6, "B"): (10, 1),  # Bb/A# major
    (7, "B"): (5, 1),  # F major
    (8, "B"): (0, 1),  # C major
    (9, "B"): (7, 1),  # G major
    (10, "B"): (2, 1),  # D major
    (11, "B"): (9, 1),  # A major
    (12, "B"): (4, 1),  # E major
}

# Reverse mapping: (pitch_class, mode) → human-readable key string
_NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


@dataclass(frozen=True)
class SoundchartsTrack:
    """A track discovered via Soundcharts."""

    title: str
    artist: str
    soundcharts_uuid: str


@dataclass(frozen=True)
class SoundchartsAudioFeatures:
    """Audio features for one track, resolved by ISRC (#544).

    ``energy`` is normalized to WrzDJ's 0–10 integer scale; the remaining
    perceptual features keep Soundcharts' native 0.0–1.0 floats. ``key`` is a
    pitch class (-1 unknown, 0–11), ``mode`` is 0 minor / 1 major. ``genres``
    is a flattened, de-duplicated tuple of the sub-genre strings. Any field is
    ``None`` when the provider did not supply it (e.g. no audio analysis).
    """

    isrc: str
    soundcharts_uuid: str
    energy: int | None
    danceability: float | None
    valence: float | None
    acousticness: float | None
    instrumentalness: float | None
    speechiness: float | None
    liveness: float | None
    loudness_db: float | None
    tempo_bpm: float | None
    key: int | None
    mode: int | None
    time_signature: int | None
    explicit: bool | None
    duration_sec: int | None
    genres: tuple[str, ...]


def key_to_soundcharts_filter(key_str: str) -> tuple[int, int] | None:
    """Convert a key string to Soundcharts (pitch_class, mode) filter values.

    Returns (pitch_class 0-11, mode 0=minor/1=major) or None if unparseable.
    """
    pos = parse_key(key_str)
    if pos is None:
        return None
    return _CAMELOT_TO_PITCH.get((pos.number, pos.letter))


def pitch_class_to_key_string(pitch_class: int, mode: int) -> str:
    """Convert Soundcharts pitch_class + mode back to a key string like 'D Minor'."""
    note = _NOTE_NAMES[pitch_class % 12]
    quality = "Major" if mode == 1 else "Minor"
    return f"{note} {quality}"


def _normalize_energy_0_10(value: float | None) -> int | None:
    """Convert a Soundcharts 0.0–1.0 energy value to WrzDJ's 0–10 integer scale.

    Returns None when no value is available. Uses standard rounding (not
    Python's banker's ``round``) and clamps defensively to [0, 10] so a
    provider value outside the documented range can never escape the scale.
    """
    if value is None:
        return None
    scaled = int(value * 10 + 0.5)
    return max(0, min(10, scaled))


def _build_request_body(
    genres: list[str],
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    keys: list[str] | None = None,
) -> dict:
    """Build the POST body for /api/v2/top/songs."""
    filters = []

    if genres:
        filters.append(
            {
                "type": "songGenres",
                "data": {"values": genres, "operator": "in"},
            }
        )

    if bpm_min is not None and bpm_max is not None:
        filters.append(
            {
                "type": "tempo",
                "data": {"min": int(bpm_min), "max": int(bpm_max)},
            }
        )

    if keys:
        pitch_classes: set[int] = set()
        modes: set[int] = set()
        for key_str in keys:
            result = key_to_soundcharts_filter(key_str)
            if result:
                pitch_classes.add(result[0])
                modes.add(result[1])
        if pitch_classes:
            filters.append(
                {
                    "type": "songKey",
                    "data": {"values": sorted(pitch_classes), "operator": "in"},
                }
            )
        if modes:
            filters.append(
                {
                    "type": "songMode",
                    "data": {"values": sorted(modes), "operator": "in"},
                }
            )

    return {
        "sort": {
            "platform": "spotify",
            "metricType": "streams",
            "period": "month",
            "sortBy": "total",
            "order": "desc",
        },
        "filters": filters,
    }


def discover_songs(
    genres: list[str],
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    keys: list[str] | None = None,
    limit: int = 50,
) -> list[SoundchartsTrack]:
    """Discover songs via Soundcharts filtered by genre, BPM, and key.

    Returns up to `limit` tracks sorted by Spotify streams (popularity).
    Returns empty list if Soundcharts is not configured or API fails.
    """
    settings = get_settings()
    if not settings.soundcharts_app_id or not settings.soundcharts_api_key:
        logger.debug("Soundcharts not configured, skipping discovery")
        return []

    body = _build_request_body(genres, bpm_min, bpm_max, keys)

    try:
        response = httpx.post(
            f"{BASE_URL}/api/v2/top/songs",
            params={"offset": 0, "limit": limit},
            json=body,
            headers={
                "x-app-id": settings.soundcharts_app_id,
                "x-api-key": settings.soundcharts_api_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "Soundcharts API error %s: %s", e.response.status_code, e.response.text[:200]
        )
        return []
    except httpx.HTTPError as e:
        logger.warning("Soundcharts request failed: %s", e)
        return []

    data = response.json()
    tracks = []
    for item in data.get("items", []):
        song = item.get("song", {})
        name = song.get("name")
        artist_raw = song.get("creditName")
        artist = artist_raw.get("name", "") if isinstance(artist_raw, dict) else artist_raw
        uuid = song.get("uuid")
        if name and artist and uuid:
            tracks.append(
                SoundchartsTrack(
                    title=name,
                    artist=artist,
                    soundcharts_uuid=uuid,
                )
            )

    logger.info(
        "Soundcharts discovered %d tracks (genres=%s, bpm=%s-%s, keys=%s)",
        len(tracks),
        genres,
        bpm_min,
        bpm_max,
        keys,
    )
    return tracks


def _normalize_isrc(isrc: str | None) -> str | None:
    """Uppercase, trim, and strip hyphens so the ISRC matches Soundcharts' key."""
    if not isrc:
        return None
    cleaned = isrc.strip().upper().replace("-", "")
    return cleaned or None


def _flatten_genres(genres: list | None) -> tuple[str, ...]:
    """Flatten Soundcharts' [{root, sub:[...]}] genre list to ordered unique subs."""
    out: list[str] = []
    for entry in genres or []:
        for sub in entry.get("sub", []) or []:
            if sub and sub not in out:
                out.append(sub)
    return tuple(out)


def _fetch_song_object(url: str, settings) -> dict | None:
    """GET a Soundcharts song endpoint and return its ``object`` dict (or None)."""
    try:
        response = httpx.get(
            url,
            headers={
                "x-app-id": settings.soundcharts_app_id,
                "x-api-key": settings.soundcharts_api_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(
            "Soundcharts song API error %s: %s", e.response.status_code, e.response.text[:200]
        )
        return None
    except httpx.HTTPError as e:
        logger.warning("Soundcharts song request failed: %s", e)
        return None

    obj = response.json().get("object")
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    return obj if isinstance(obj, dict) else None


def _parse_song_features(obj: dict, isrc: str) -> SoundchartsAudioFeatures:
    """Build an audio-features record from a Soundcharts song object."""
    audio = obj.get("audio") or {}
    return SoundchartsAudioFeatures(
        isrc=isrc,
        soundcharts_uuid=obj.get("uuid", ""),
        energy=_normalize_energy_0_10(audio.get("energy")),
        danceability=audio.get("danceability"),
        valence=audio.get("valence"),
        acousticness=audio.get("acousticness"),
        instrumentalness=audio.get("instrumentalness"),
        speechiness=audio.get("speechiness"),
        liveness=audio.get("liveness"),
        loudness_db=audio.get("loudness"),
        tempo_bpm=audio.get("tempo"),
        key=audio.get("key"),
        mode=audio.get("mode"),
        time_signature=audio.get("timeSignature"),
        explicit=obj.get("explicit"),
        duration_sec=obj.get("duration"),
        genres=_flatten_genres(obj.get("genres")),
    )


def get_song_features_by_isrc(isrc: str) -> SoundchartsAudioFeatures | None:
    """Resolve a track's audio features (energy/danceability/valence/…) by ISRC.

    Dark by default: returns None unless ``soundcharts_audio_features_enabled``
    is set AND credentials are configured. Resolves ISRC → song UUID → metadata
    (two calls), but skips the second call when the ISRC lookup already carries
    the audio block. Returns None on miss or API failure.
    """
    settings = get_settings()
    if not settings.soundcharts_audio_features_enabled:
        logger.debug("Soundcharts audio-features disabled, skipping lookup")
        return None
    if not settings.soundcharts_app_id or not settings.soundcharts_api_key:
        logger.debug("Soundcharts not configured, skipping audio-features lookup")
        return None

    normalized = _normalize_isrc(isrc)
    if not normalized:
        return None

    obj = _fetch_song_object(f"{SONG_API_BASE}/by-isrc/{normalized}", settings)
    if not obj or not obj.get("uuid"):
        return None

    if "audio" not in obj:
        obj = _fetch_song_object(f"{SONG_API_BASE}/{obj['uuid']}", settings)
        if not obj:
            return None

    return _parse_song_features(obj, normalized)

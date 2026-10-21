"""Map tidalapi track objects into provider-neutral search results."""

import tidalapi

from app.schemas.tidal import TidalSearchResult


def get_artist_name(track: tidalapi.Track) -> str:
    """Return all credited artist names, preserving multi-artist tracks."""
    if hasattr(track, "artists") and track.artists:
        names = [artist.name for artist in track.artists if artist and artist.name]
        if names:
            return ", ".join(names)
    return track.artist.name if track.artist else "Unknown"


def track_to_result(track: tidalapi.Track) -> TidalSearchResult:
    """Convert tidalapi Track to the provider-neutral result schema."""
    cover_url = None
    try:
        if track.album:
            cover_url = track.album.image(640)
    except Exception:
        # Album artwork is optional and should not block track metadata.
        cover_url = None

    try:
        bpm = float(track.bpm) if hasattr(track, "bpm") and track.bpm else None
    except (TypeError, ValueError):
        bpm = None

    try:
        key = track.key if hasattr(track, "key") and track.key else None
    except (TypeError, AttributeError):
        key = None

    raw_popularity = getattr(track, "popularity", None)
    popularity = int(raw_popularity) if isinstance(raw_popularity, (int, float)) else 0
    raw_isrc = getattr(track, "isrc", None)
    isrc = raw_isrc if isinstance(raw_isrc, str) and raw_isrc else None
    raw_version = getattr(track, "version", None)
    version = raw_version if isinstance(raw_version, str) and raw_version else None
    raw_explicit = getattr(track, "explicit", None)
    explicit = raw_explicit if isinstance(raw_explicit, bool) else False

    return TidalSearchResult(
        track_id=str(track.id),
        title=track.name or "Unknown",
        artist=get_artist_name(track),
        album=track.album.name if track.album else None,
        bpm=bpm,
        key=key,
        duration_seconds=track.duration if track.duration else None,
        cover_url=cover_url,
        tidal_url=f"https://tidal.com/browse/track/{track.id}",
        popularity=popularity,
        isrc=isrc,
        version=version,
        explicit=explicit,
    )

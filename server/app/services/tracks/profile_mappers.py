"""Map provider results into the shared track metadata model."""

from app.schemas.beatport import BeatportSearchResult
from app.schemas.tidal import TidalSearchResult
from app.services.tracks.profile import TrackProfile


def beatport_result_to_profile(result: BeatportSearchResult) -> TrackProfile:
    """Map one Beatport result consistently across search and playlist paths."""
    return TrackProfile(
        title=result.title,
        artist=result.artist,
        bpm=float(result.bpm) if result.bpm else None,
        key=result.key,
        genre=result.genre,
        source="beatport",
        track_id=result.track_id,
        url=result.beatport_url,
        cover_url=result.cover_url,
        duration_seconds=result.duration_seconds,
    )


def tidal_result_to_profile(
    result: TidalSearchResult, *, inferred_genre: str | None = None
) -> TrackProfile:
    """Map one Tidal result, optionally carrying recommendation-inferred genre."""
    return TrackProfile(
        title=result.title,
        artist=result.artist,
        bpm=float(result.bpm) if result.bpm else None,
        key=result.key,
        genre=inferred_genre,
        source="tidal",
        track_id=result.track_id,
        url=result.tidal_url,
        cover_url=result.cover_url,
        duration_seconds=result.duration_seconds,
    )

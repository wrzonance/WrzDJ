"""Convert Beatport catalog records into the provider search result schema."""

from typing import Any

from app.schemas.beatport import BeatportSearchResult
from app.services.providers.beatport_common import BEATPORT_TRACK_URL, parse_duration


def beatport_track_to_result(
    track: dict[str, Any],
    *,
    fallback_track_id: str | None = None,
    url_track_id: str | None = None,
) -> BeatportSearchResult:
    """Map a Beatport API track record, preserving the source-specific fallbacks."""
    track_id_value = track.get("id", fallback_track_id if fallback_track_id is not None else "")
    track_id = str(track_id_value)
    url_id = str(url_track_id) if url_track_id is not None else track_id
    slug = track.get("slug", "untitled")
    artists = ", ".join(artist.get("name", "") for artist in track.get("artists", []))

    genre_name = None
    if track.get("genre"):
        genre_name = track["genre"].get("name")

    cover_url = None
    if track.get("image"):
        cover_url = track["image"].get("uri")

    return BeatportSearchResult(
        track_id=track_id,
        title=track.get("name", ""),
        artist=artists,
        mix_name=track.get("mix_name"),
        label=track.get("label", {}).get("name") if track.get("label") else None,
        genre=genre_name,
        bpm=track.get("bpm"),
        key=track.get("key", {}).get("name") if track.get("key") else None,
        duration_seconds=parse_duration(track.get("length")),
        cover_url=cover_url,
        beatport_url=BEATPORT_TRACK_URL.format(slug=slug, track_id=url_id),
        release_date=track.get("new_release_date") or track.get("publish_date"),
    )

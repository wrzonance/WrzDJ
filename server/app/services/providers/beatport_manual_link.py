"""Manual Beatport track linking for existing song requests."""

import json

from sqlalchemy.orm import Session

from app.models.request import Request as SongRequest
from app.schemas.beatport import BeatportSearchResult


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

"""Tidal adapter — wraps existing tidal.py service functions.

Does NOT modify tidal.py. Adds version filtering and fuzzy scoring
on top of the existing search.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.providers import tidal as tidal_service
from app.services.sync.base import PlaylistSyncAdapter, TrackMatch
from app.services.track_normalizer import fuzzy_match_score
from app.services.version_filter import is_unwanted_version

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.event import Event
    from app.models.user import User
    from app.services.intent_parser import IntentContext
    from app.services.track_normalizer import NormalizedTrack

logger = logging.getLogger(__name__)

# Minimum fuzzy match score to accept a track
MATCH_THRESHOLD = 0.5


class TidalSyncAdapter(PlaylistSyncAdapter):
    """Playlist sync adapter for Tidal."""

    @property
    def service_name(self) -> str:
        return "tidal"

    def is_connected(self, user: User) -> bool:
        return bool(user.tidal_access_token)

    def is_sync_enabled(self, event: Event) -> bool:
        return bool(event.tidal_sync_enabled)

    def search_track(
        self,
        db: Session,
        user: User,
        normalized: NormalizedTrack,
        intent: IntentContext | None = None,
    ) -> TrackMatch | None:
        """Search Tidal with version filtering and fuzzy scoring.

        1. Calls tidal_service.search_tidal_tracks() for candidates
        2. Filters through is_unwanted_version()
        3. Scores with fuzzy_match_score (title*0.7 + artist*0.3)
        4. Returns best match above threshold
        """
        candidates = tidal_service.search_tidal_tracks(
            db, user, f"{normalized.raw_artist} {normalized.raw_title}", limit=10
        )

        if not candidates:
            return None

        best_match: TrackMatch | None = None
        best_score = 0.0

        for candidate in candidates:
            # Version filter: reject unwanted versions
            if is_unwanted_version(candidate.title, intent):
                continue

            # Fuzzy score: title matters more than artist
            title_score = fuzzy_match_score(normalized.title, candidate.title)
            artist_score = fuzzy_match_score(normalized.artist, candidate.artist)
            combined = title_score * 0.7 + artist_score * 0.3

            if combined > best_score and combined >= MATCH_THRESHOLD:
                best_score = combined
                best_match = TrackMatch(
                    service="tidal",
                    track_id=candidate.track_id,
                    title=candidate.title,
                    artist=candidate.artist,
                    match_confidence=combined,
                    url=candidate.tidal_url,
                    duration_seconds=candidate.duration_seconds,
                )

        if best_match:
            logger.info(
                f"Tidal match: '{best_match.title}' by '{best_match.artist}' "
                f"(confidence: {best_match.match_confidence:.2f})"
            )

        return best_match

    def ensure_playlist(
        self,
        db: Session,
        user: User,
        event: Event,
    ) -> str | None:
        return tidal_service.create_event_playlist(db, user, event)

    def add_to_playlist(
        self,
        db: Session,
        user: User,
        playlist_id: str,
        track_id: str,
    ) -> bool:
        return tidal_service.add_track_to_playlist(db, user, playlist_id, track_id)

    def add_tracks_to_playlist(
        self,
        db: Session,
        user: User,
        playlist_id: str,
        track_ids: list[str],
    ) -> bool:
        """Batch add using Tidal's native batch API (skips duplicates)."""
        return tidal_service.add_tracks_to_playlist(db, user, playlist_id, track_ids)

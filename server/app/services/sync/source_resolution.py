"""Source URL and ISRC resolution stages for request enrichment."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.request import Request
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.schemas.tidal import TidalSearchResult
from app.services.request import normalize_key


@dataclass(frozen=True)
class FieldResolution:
    """A provider value and its provenance for one track field."""

    value: object
    source: str


@dataclass(frozen=True)
class SourceResolutionResult:
    """Resolved ISRC and metadata updates, without mutating the request."""

    isrc: str | None
    fields: Mapping[str, FieldResolution] = field(default_factory=dict)


def track_field_resolutions(
    request: Request,
    track: BeatportSearchResult | TidalSearchResult,
    *,
    source: str,
    with_genre: bool = False,
) -> dict[str, FieldResolution]:
    """Return only provider fields that can fill currently missing request data."""
    updates: dict[str, FieldResolution] = {}
    if with_genre and not request.genre and getattr(track, "genre", None):
        updates["genre"] = FieldResolution(track.genre, source)
    if not request.bpm and getattr(track, "bpm", None):
        updates["bpm"] = FieldResolution(float(track.bpm), source)
    if not request.musical_key and getattr(track, "key", None):
        updates["musical_key"] = FieldResolution(normalize_key(track.key), source)
    return updates


def resolve_direct_source_track(
    db: Session,
    request: Request,
    *,
    user: User | None,
    source_svc: str | None,
    source_track_id: str | None,
    resolved_isrc: str | None,
    logger: logging.Logger,
) -> SourceResolutionResult:
    """Resolve a linked Beatport/Tidal track before provider search."""
    request_id = request.id
    fields: dict[str, FieldResolution] = {}
    if source_svc == "beatport" and source_track_id:
        if user and user.beatport_access_token and (not request.bpm or not request.musical_key):
            try:
                from app.services.providers.beatport_catalog import get_beatport_track

                direct = get_beatport_track(db, user, source_track_id)
                if direct:
                    logger.info(
                        "Beatport direct fetch for %d: '%s' bpm=%s key=%s",
                        request_id,
                        direct.title,
                        direct.bpm,
                        direct.key,
                    )
                    fields.update(
                        track_field_resolutions(request, direct, source="beatport", with_genre=True)
                    )
                    if getattr(direct, "isrc", None):
                        resolved_isrc = direct.isrc
            except Exception as exc:
                logger.warning(
                    "Beatport direct fetch failed for request %d (%s)",
                    request_id,
                    type(exc).__name__,
                )

    if source_svc == "tidal" and source_track_id:
        if user and user.tidal_access_token and (not request.bpm or not request.musical_key):
            try:
                from app.services.providers.tidal_search import get_tidal_track_by_id

                direct = get_tidal_track_by_id(db, user, source_track_id)
                if direct:
                    logger.info(
                        "Tidal direct fetch for %d: '%s' bpm=%s key=%s",
                        request_id,
                        direct.title,
                        direct.bpm,
                        direct.key,
                    )
                    fields.update(track_field_resolutions(request, direct, source="tidal"))
                    if getattr(direct, "isrc", None):
                        resolved_isrc = direct.isrc
            except Exception as exc:
                logger.warning(
                    "Tidal direct fetch failed for request %d (%s)",
                    request_id,
                    type(exc).__name__,
                )

    return SourceResolutionResult(isrc=resolved_isrc, fields=fields)


def resolve_spotify_isrc_and_tidal_match(
    db: Session,
    request: Request,
    *,
    user: User | None,
    source_svc: str | None,
    resolved_isrc: str | None,
    settings_provider: Callable[[], Settings],
    isrc_resolver: Callable[..., str | None],
    logger: logging.Logger,
) -> SourceResolutionResult:
    """Fetch a Spotify ISRC only when useful, then resolve a Tidal exact match."""
    request_id = request.id
    fields: dict[str, FieldResolution] = {}
    needs_isrc_for_tidal = bool(
        (not request.bpm or not request.musical_key) and user and user.tidal_access_token
    )
    needs_isrc_for_soundcharts = settings_provider().soundcharts_audio_features_enabled
    if (
        source_svc == "spotify"
        and not resolved_isrc
        and (needs_isrc_for_tidal or needs_isrc_for_soundcharts)
    ):
        resolved_isrc = isrc_resolver(request.source_url, request_id=request_id)

    if (
        source_svc == "spotify"
        and resolved_isrc
        and (not request.bpm or not request.musical_key)
        and user
        and user.tidal_access_token
    ):
        try:
            from app.services.providers.tidal_search import search_tidal_by_isrc

            isrc_match = search_tidal_by_isrc(db, user, resolved_isrc)
            if isrc_match:
                logger.info(
                    "ISRC match for %d: '%s' by '%s' bpm=%s key=%s (ISRC=%s)",
                    request_id,
                    isrc_match.title,
                    isrc_match.artist,
                    isrc_match.bpm,
                    isrc_match.key,
                    resolved_isrc,
                )
                fields.update(track_field_resolutions(request, isrc_match, source="tidal"))
        except Exception as exc:
            logger.warning(
                "ISRC enrichment failed for request %d (%s)", request_id, type(exc).__name__
            )

    return SourceResolutionResult(isrc=resolved_isrc, fields=fields)

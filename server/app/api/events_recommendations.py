"""Recommendation and playlist routes for event owners."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_owned_event
from app.core.rate_limit import limiter
from app.models.event import Event
from app.schemas.recommendation import (
    EventMusicProfile,
    LLMPromptRequest,
    LLMQueryInfo,
    LLMRecommendationResponse,
    PlaylistInfo,
    PlaylistListResponse,
    RecommendationResponse,
    RecommendedTrack,
    TemplatePlaylistRequest,
)
from app.services.music_matching import parse_key

router = APIRouter()
_llm_rate_limit_cache: dict[str, int] = {"value": 3}


def _build_recommendation_response(result, db, actor=None) -> RecommendationResponse:
    """Build a RecommendationResponse from a recommendation engine result."""
    from app.services.recommendation.llm_hooks import is_llm_available

    profile = EventMusicProfile(
        avg_bpm=result.event_profile.avg_bpm,
        bpm_range_low=result.event_profile.bpm_range[0] if result.event_profile.bpm_range else None,
        bpm_range_high=result.event_profile.bpm_range[1]
        if result.event_profile.bpm_range
        else None,
        dominant_keys=[str(p) for k in result.event_profile.dominant_keys if (p := parse_key(k))],
        dominant_genres=list(result.event_profile.dominant_genres),
        track_count=result.event_profile.track_count,
        enriched_count=result.enriched_count,
    )

    suggestions = [
        RecommendedTrack(
            title=s.profile.title,
            artist=s.profile.artist,
            bpm=s.profile.bpm,
            key=str(p) if (p := parse_key(s.profile.key)) else s.profile.key,
            genre=s.profile.genre,
            score=s.score,
            bpm_score=s.bpm_score,
            key_score=s.key_score,
            genre_score=s.genre_score,
            source=s.profile.source,
            track_id=s.profile.track_id,
            url=s.profile.url,
            cover_url=s.profile.cover_url,
            duration_seconds=s.profile.duration_seconds,
            mb_verified=result.mb_verified.get(s.profile.artist, False),
        )
        for s in result.suggestions
    ]

    return RecommendationResponse(
        suggestions=suggestions,
        profile=profile,
        services_used=result.services_used,
        total_candidates_searched=result.total_candidates_searched,
        llm_available=is_llm_available(db, actor=actor),
    )


@router.post("/{code}/recommendations", response_model=RecommendationResponse)
@limiter.limit("5/minute")
def get_recommendations(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Generate song recommendations based on the event's musical profile."""
    from app.services.recommendation.service import (
        generate_recommendations,
        soundcharts_related_available,
    )

    user = event.created_by

    # A candidate source must be available: a connected Tidal/Beatport account,
    # or the provider-agnostic Soundcharts related-tracks source (#556), which
    # needs no connected service (dark by default — only when explicitly enabled).
    has_services = bool(user.tidal_access_token) or bool(user.beatport_access_token)
    if not has_services and not soundcharts_related_available():
        raise HTTPException(
            status_code=503,
            detail="No music services connected. Link Tidal or Beatport to get recommendations.",
        )

    result = generate_recommendations(db, user, event)
    return _build_recommendation_response(result, db, actor=user)


@router.get("/{code}/playlists")
@limiter.limit("10/minute")
def get_playlists(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> PlaylistListResponse:
    """List the DJ's playlists from connected music services."""
    user = event.created_by
    playlists: list[PlaylistInfo] = []

    if user.tidal_access_token:
        from app.services.providers.tidal import list_user_playlists as tidal_list

        for p in tidal_list(db, user):
            playlists.append(
                PlaylistInfo(
                    id=p.id,
                    name=p.name,
                    num_tracks=p.num_tracks,
                    description=p.description,
                    cover_url=p.cover_url,
                    source=p.source,
                )
            )

    if user.beatport_access_token:
        from app.services.providers.beatport import list_user_playlists as bp_list

        for p in bp_list(db, user):
            playlists.append(
                PlaylistInfo(
                    id=p.id,
                    name=p.name,
                    num_tracks=p.num_tracks,
                    description=p.description,
                    cover_url=p.cover_url,
                    source=p.source,
                )
            )

    return PlaylistListResponse(playlists=playlists)


@router.post("/{code}/recommendations/from-template", response_model=RecommendationResponse)
@limiter.limit("5/minute")
def get_recommendations_from_template(
    request: Request,
    template_request: TemplatePlaylistRequest,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Generate recommendations using a template playlist."""
    from app.services.recommendation.service import generate_recommendations_from_template

    user = event.created_by

    # Check if any music services are connected
    has_services = bool(user.tidal_access_token) or bool(user.beatport_access_token)
    if not has_services:
        raise HTTPException(
            status_code=503,
            detail="No music services connected. Link Tidal or Beatport to get recommendations.",
        )

    result = generate_recommendations_from_template(
        db,
        user,
        event,
        template_source=template_request.source,
        template_id=template_request.playlist_id,
    )
    return _build_recommendation_response(result, db, actor=user)


@router.post("/{code}/recommendations/llm")
@limiter.limit(lambda: f"{_llm_rate_limit_cache['value']}/minute")
async def get_llm_recommendations(
    request: Request,
    prompt_request: LLMPromptRequest,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> LLMRecommendationResponse:
    """Generate song recommendations from an LLM-interpreted DJ prompt."""
    from app.services.recommendation.llm_hooks import is_llm_available
    from app.services.recommendation.service import generate_recommendations_from_llm
    from app.services.system_settings import get_system_settings

    # Refresh LLM rate limit cache from DB
    sys_settings = get_system_settings(db)
    _llm_rate_limit_cache["value"] = sys_settings.llm_rate_limit_per_minute

    user = event.created_by

    if not is_llm_available(db, actor=user):
        raise HTTPException(
            status_code=503,
            detail="LLM recommendations not configured. Add a DJ/admin AI connector to enable.",
        )

    has_services = bool(user.tidal_access_token) or bool(user.beatport_access_token)
    if not has_services:
        raise HTTPException(
            status_code=503,
            detail="No music services connected. Link Tidal or Beatport to get recommendations.",
        )

    from app.services.llm.exceptions import QuotaCapReached

    try:
        result = await generate_recommendations_from_llm(db, user, event, prompt_request.prompt)
    except QuotaCapReached as exc:
        # DJ-facing message only — no internal usage/cap details leaked (issue #339).
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception:
        import logging

        logging.getLogger(__name__).exception("LLM recommendation failed")
        raise HTTPException(
            status_code=502,
            detail="LLM service error. Try again or use algorithmic recommendations.",
        )

    base = _build_recommendation_response(result, db, actor=user)

    llm_queries = [
        LLMQueryInfo(
            search_query=q.search_query,
            target_bpm=q.target_bpm,
            target_key=q.target_key,
            target_genre=q.target_genre,
            reasoning=q.reasoning,
        )
        for q in result.llm_queries
    ]

    return LLMRecommendationResponse(
        suggestions=base.suggestions,
        profile=base.profile,
        services_used=base.services_used,
        total_candidates_searched=base.total_candidates_searched,
        llm_queries=llm_queries,
        llm_model=result.llm_model or "",
    )

"""Pool collection and vibe routes for WrzDJSet."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.models.track_vibe import (
    TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
    TRACK_VIBE_SOURCE_UPVOTE,
    TrackVibeOverride,
)
from app.models.user import User
from app.schemas.recommendation import PlaylistInfo
from app.schemas.setbuilder import (
    BuilderPlaylistsOut,
    CommunityVibeOut,
    LlmVibeOut,
    OwnVibeOut,
    PoolEnrichmentSummary,
    PoolImportEventIn,
    PoolImportManualIn,
    PoolImportPlaylistIn,
    PoolImportResult,
    PoolImportUrlIn,
    PoolMutationResult,
    PoolRemoveTracksIn,
    PoolSourceOut,
    PoolState,
    PoolTrackOut,
    PoolUrlPreview,
    PoolVibeOverrideIn,
    PoolVibesState,
    ResolvedVibeOut,
    TrackVibeStateOut,
    VibeEnrichmentResult,
)
from app.services.llm.exceptions import NoLlmConfigured
from app.services.setbuilder import (
    pool,
    vibe_enrichment,
    vibe_resolver,
)
from app.services.setbuilder.playlist_url import InvalidPlaylistUrl, parse_public_playlist_url
from app.services.setbuilder.public_playlist_import import (
    UnsupportedPublicPlaylist,
    persist_public_playlist_source,
    prepare_public_playlist_import,
)

router = APIRouter()


def _pool_state(db: Session, set_id: int) -> PoolState:
    sources, tracks = pool.get_pool(db, set_id)
    return PoolState(
        sources=[PoolSourceOut.model_validate(s) for s in sources],
        tracks=[PoolTrackOut.model_validate(t) for t in tracks],
        runtime_sec=pool.pool_runtime_sec(db, set_id),
        enrichment=_pool_enrichment_summary(tracks),
    )


def _pool_enrichment_summary(tracks: list[SetPoolTrack]) -> PoolEnrichmentSummary:
    enriched = sum(1 for track in tracks if track.enrichment_status == pool.POOL_ENRICHED)
    failed = sum(1 for track in tracks if track.enrichment_status == pool.POOL_ENRICH_FAILED)
    pending = sum(1 for track in tracks if track.enrichment_status == pool.POOL_ENRICH_PENDING)
    return PoolEnrichmentSummary(
        total=len(tracks),
        enriched=enriched,
        failed=failed,
        pending=pending,
        in_progress=pending > 0,
    )


def _import_result(db: Session, set_id: int, source, added: int, deduped: int) -> PoolImportResult:
    return PoolImportResult(
        added=added,
        deduped=deduped,
        source=PoolSourceOut.model_validate(source),
        pool=_pool_state(db, set_id),
    )


def _queue_pool_enrichment(
    db: Session, background_tasks: BackgroundTasks, set_id: int, source_id: int
) -> None:
    pending_ids = pool.pending_enrichment_track_ids(db, set_id, source_id=source_id)
    if pending_ids:
        background_tasks.add_task(pool.enrich_pool_tracks, set_id, pending_ids)


@router.get("/sets/{set_id}/pool", response_model=PoolState)
@limiter.limit("60/minute")
def get_pool_state(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolState:
    """Full pool snapshot (sources + tracks) for one of the DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _pool_state(db, set_obj.id)


@router.get("/playlists", response_model=BuilderPlaylistsOut)
@limiter.limit("20/minute")
def list_builder_playlists(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BuilderPlaylistsOut:
    """Connected-service playlists for the import modal pickers."""
    tidal_connected = bool(current_user.tidal_access_token)
    beatport_connected = bool(current_user.beatport_access_token)
    tidal_playlists: list[PlaylistInfo] = []
    beatport_playlists: list[PlaylistInfo] = []

    if tidal_connected:
        from app.services.providers.tidal import list_user_playlists as tidal_list

        tidal_playlists = [PlaylistInfo(**vars(p)) for p in tidal_list(db, current_user)]
    if beatport_connected:
        from app.services.providers.beatport import list_user_playlists as bp_list

        beatport_playlists = [PlaylistInfo(**vars(p)) for p in bp_list(db, current_user)]

    return BuilderPlaylistsOut(
        tidal_connected=tidal_connected,
        beatport_connected=beatport_connected,
        tidal=tidal_playlists,
        beatport=beatport_playlists,
    )


@router.post("/sets/{set_id}/pool/import/event", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_event(
    set_id: int,
    payload: PoolImportEventIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a DJ-owned event's non-rejected requests into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    result = pool.candidates_from_event(db, current_user, payload.event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event, candidates = result
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="event",
        external_ref=str(event.id),
        label=event.name,
        meta="WrzDJ event requests",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/tidal", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_tidal(
    set_id: int,
    payload: PoolImportPlaylistIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a connected-account Tidal playlist into the pool."""
    from app.services.providers.tidal import TidalFetchError

    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        candidates = pool.candidates_from_tidal(db, current_user, payload.playlist_id)
    except TidalFetchError:
        raise HTTPException(status_code=502, detail="Couldn't fetch that Tidal playlist") from None
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="tidal",
        external_ref=payload.playlist_id,
        label=payload.label or "Tidal playlist",
        meta="Tidal playlist",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/beatport", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_beatport(
    set_id: int,
    payload: PoolImportPlaylistIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a connected-account Beatport playlist into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    # beatport.get_playlist_tracks returns [] on fetch failure (existing semantics)
    candidates = pool.candidates_from_beatport(db, current_user, payload.playlist_id)
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="beatport",
        external_ref=payload.playlist_id,
        label=payload.label or "Beatport playlist",
        meta="Beatport playlist",
    )
    candidates = pool.hydrate_candidates_from_store(
        db, candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/url-preview", response_model=PoolUrlPreview)
@limiter.limit("10/minute")
def preview_pool_url(
    set_id: int,
    payload: PoolImportUrlIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolUrlPreview:
    """Validate a public playlist URL and return the preview card payload."""
    _get_owned_or_404(db, set_id, current_user)
    try:
        parsed = parse_public_playlist_url(payload.url)
    except InvalidPlaylistUrl as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not parsed.supported:
        return PoolUrlPreview(provider=parsed.provider, supported=False, message=parsed.message)
    try:
        if parsed.provider == "apple_music":
            meta = pool.preview_public_playlist(
                db,
                current_user,
                parsed.provider,
                parsed.playlist_id,
                storefront=parsed.storefront,
            )
        else:
            meta = pool.preview_public_playlist(
                db, current_user, parsed.provider, parsed.playlist_id
            )
    except pool.PoolImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    return PoolUrlPreview(provider=parsed.provider, supported=True, **meta)


@router.post("/sets/{set_id}/pool/import/url", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_url(
    set_id: int,
    payload: PoolImportUrlIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a validated public playlist URL into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        prepared = prepare_public_playlist_import(db, current_user, payload.url)
    except (InvalidPlaylistUrl, UnsupportedPublicPlaylist) as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except pool.PoolImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    source = persist_public_playlist_source(db, set_obj, prepared)
    candidates = pool.hydrate_candidates_from_store(
        db, prepared.candidates, user=current_user, enrich_missing=False
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    _queue_pool_enrichment(db, background_tasks, set_obj.id, source.id)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/manual", response_model=PoolImportResult)
@limiter.limit("30/minute")
def import_pool_manual(
    set_id: int,
    payload: PoolImportManualIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Add a single manually-searched track to the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    candidate = pool.candidate_from_manual(
        title=payload.title,
        artist=payload.artist,
        album=payload.album,
        genre=payload.genre,
        bpm=payload.bpm,
        key=payload.key,
        isrc=payload.isrc,
        duration_sec=payload.duration_sec,
        artwork_url=payload.artwork_url,
        source_service=payload.source_service,
        source_track_id=payload.source_track_id,
    )
    source = pool.get_or_create_source(
        db, set_obj, kind="manual", external_ref=None, label="Manual", meta="Single-track search"
    )
    candidates = pool.hydrate_candidates_from_store(db, [candidate], user=current_user)
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/tracks/remove", response_model=PoolMutationResult)
@limiter.limit("30/minute")
def remove_pool_tracks(
    set_id: int,
    payload: PoolRemoveTracksIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolMutationResult:
    """Remove pool tracks by id (per-track context menu + multi-select)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    removed = pool.remove_tracks(db, set_obj, payload.track_ids)
    return PoolMutationResult(removed=removed, pool=_pool_state(db, set_obj.id))


@router.delete("/sets/{set_id}/pool/sources/{source_id}", response_model=PoolMutationResult)
@limiter.limit("30/minute")
def remove_pool_source(
    set_id: int,
    source_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolMutationResult:
    """Remove an import source and exactly its tracks."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    source = pool.get_owned_source(db, set_obj, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    removed = pool.remove_source(db, set_obj, source)
    return PoolMutationResult(removed=removed, pool=_pool_state(db, set_obj.id))


# ---------------------------------------------------------------------------
# Track vibes (issue #391) — read-only three-tier state + LLM enrichment


def _pool_vibes_state(db: Session, actor: User, set_obj: Set) -> PoolVibesState:
    states = vibe_resolver.build_pool_vibe_states(db, actor, set_obj)
    out = []
    for s in states:
        llm_out = None
        if s.llm is not None:
            llm_out = LlmVibeOut(
                energy=s.llm.energy,
                mood=s.llm.mood,
                era=s.llm.era,
                sing_along=s.llm.sing_along,
                dance_floor=s.llm.dance_floor,
                transitional_role=s.llm.transitional_role,
                confidence=s.llm.confidence,
                low_confidence=vibe_resolver.is_low_confidence(s.llm),
                llm_provider=s.llm.llm_provider,
                llm_model=s.llm.llm_model,
            )
        out.append(
            TrackVibeStateOut(
                pool_track_id=s.pool_track_id,
                vibe_key=s.vibe_key,
                own=OwnVibeOut(energy=s.own.energy, mood=s.own.mood) if s.own else None,
                community=(
                    CommunityVibeOut(
                        energy=s.community.energy,
                        mood=s.community.mood,
                        sample_size=s.community.sample_size,
                    )
                    if s.community
                    else None
                ),
                llm=llm_out,
                resolved=ResolvedVibeOut(
                    energy=s.resolved.energy,
                    energy_source=s.resolved.energy_source,
                    mood=s.resolved.mood,
                    mood_source=s.resolved.mood_source,
                ),
            )
        )
    return PoolVibesState(tracks=out)


def _pool_vibe_state_for_track(
    db: Session,
    actor: User,
    set_obj: Set,
    pool_track_id: int,
) -> vibe_resolver.TrackVibeState:
    state = vibe_resolver.build_pool_vibe_state(db, actor, set_obj, pool_track_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Pool track not found")
    return state


def _agree_values(state: vibe_resolver.TrackVibeState) -> tuple[int | None, str | None]:
    energy = (
        state.community.energy
        if state.community and state.community.energy is not None
        else state.llm.energy
        if state.llm
        else None
    )
    mood = (
        state.community.mood
        if state.community and state.community.mood is not None
        else state.llm.mood
        if state.llm
        else None
    )
    if energy is None and mood is None:
        raise HTTPException(status_code=400, detail="No vibe available to agree with")
    return energy, mood


def _overridden_from_vibe_id(state: vibe_resolver.TrackVibeState) -> int | None:
    if state.llm is None:
        return None
    if "llm" in {state.resolved.energy_source, state.resolved.mood_source}:
        return state.llm.id
    return None


def _write_vibe_override(
    db: Session,
    actor: User,
    state: vibe_resolver.TrackVibeState,
    *,
    energy: int | None,
    mood: str | None,
    source: str,
    energy_was: int | None = None,
    mood_was: str | None = None,
    overridden_from_vibe_id: int | None = None,
) -> TrackVibeOverride:
    row = TrackVibeOverride(
        track_id=state.vibe_key,
        user_id=actor.id,
        energy_override=energy,
        mood_override=mood,
        overridden_from_vibe_id=overridden_from_vibe_id,
        energy_was=energy_was,
        mood_was=mood_was,
        source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/sets/{set_id}/pool/vibes", response_model=PoolVibesState)
@limiter.limit("60/minute")
def get_pool_vibes(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolVibesState:
    """Three-tier vibe state (own / community / LLM) for the set's pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return _pool_vibes_state(db, current_user, set_obj)


@router.post(
    "/sets/{set_id}/pool/vibes/{pool_track_id}/agree",
    response_model=PoolVibesState,
    responses={400: {"description": "No non-own vibe signal available for this pool track."}},
)
@limiter.limit("30/minute")
def agree_pool_vibe(
    set_id: int,
    pool_track_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolVibesState:
    """Upvote the best non-own vibe signal for one pool track without creating an own tier."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    state = _pool_vibe_state_for_track(db, current_user, set_obj, pool_track_id)
    energy, mood = _agree_values(state)
    _write_vibe_override(
        db,
        current_user,
        state,
        energy=energy,
        mood=mood,
        source=TRACK_VIBE_SOURCE_UPVOTE,
    )
    return _pool_vibes_state(db, current_user, set_obj)


@router.patch("/sets/{set_id}/pool/vibes/{pool_track_id}/override", response_model=PoolVibesState)
@limiter.limit("30/minute")
def override_pool_vibe(
    set_id: int,
    pool_track_id: int,
    payload: PoolVibeOverrideIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolVibesState:
    """Write an explicit DJ vibe edit, preserving omitted fields from their latest vote."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    state = _pool_vibe_state_for_track(db, current_user, set_obj, pool_track_id)
    latest = vibe_resolver.latest_override_row(db, current_user.id, state.vibe_key)
    energy = (
        payload.energy
        if "energy" in payload.model_fields_set
        else latest.energy_override
        if latest
        else None
    )
    mood = (
        payload.mood
        if "mood" in payload.model_fields_set
        else latest.mood_override
        if latest
        else None
    )
    _write_vibe_override(
        db,
        current_user,
        state,
        energy=energy,
        mood=mood,
        source=TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
        energy_was=state.resolved.energy,
        mood_was=state.resolved.mood,
        overridden_from_vibe_id=_overridden_from_vibe_id(state),
    )
    return _pool_vibes_state(db, current_user, set_obj)


@router.post(
    "/sets/{set_id}/pool/vibes/enrich",
    response_model=VibeEnrichmentResult,
    responses={
        400: {"description": "No LLM connector configured for this DJ or the org."},
    },
)
@limiter.limit("5/minute")
async def enrich_pool_vibes(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> VibeEnrichmentResult:
    """Batch-enrich uncached pool tracks via the LLM gateway (20 tracks/call)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        stats = await vibe_enrichment.enrich_pool_vibes(db, current_user, set_obj)
    except NoLlmConfigured:
        raise HTTPException(
            status_code=400,
            detail="No AI connector configured — connect one in Settings → AI.",
        ) from None
    return VibeEnrichmentResult(
        enriched=stats.enriched,
        cached=stats.cached,
        failed=stats.failed,
        llm_calls=stats.llm_calls,
        vibes=_pool_vibes_state(db, current_user, set_obj),
    )


# ---------------------------------------------------------------------------
# Export (issue #396) — preflight resolution check + Tidal / file exports.
# The unresolved-track interrupt is enforced server-side: exports return 409
# unless the DJ explicitly opted to skip (never silently dropped).

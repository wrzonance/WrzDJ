"""WrzDJSet set-CRUD router (Phase 0).

Mounted at /api/setbuilder. Every endpoint requires an active DJ
(get_current_active_user rejects pending users). Sets are owner-private;
missing-or-unowned sets return 404 to avoid leaking existence.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.user import User
from app.schemas.setbuilder import (
    ApplyTemplateRequest,
    ApplyTemplateResponse,
    BuilderPlaylistsOut,
    BuiltinTemplateOut,
    CommunityVibeOut,
    CurvePointModel,
    CurveTemplateCreate,
    CurveTemplateOut,
    CurveTemplatesResponse,
    ExportFileIn,
    ExportPreflightIn,
    ExportPreflightOut,
    ExportTidalIn,
    ExportTidalOut,
    LlmVibeOut,
    OwnVibeOut,
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
    PoolVibesState,
    ResolvedVibeOut,
    SetCreate,
    SetDetail,
    SetRename,
    SetSummary,
    SlotOut,
    SlotTargetOut,
    SlotTargetUpdate,
    TemplateWindowOut,
    TrackVibeStateOut,
    UnresolvedTrackOut,
    VibeEnrichmentResult,
    VibeWindowModel,
    VibeWindowsPut,
    VibeWindowsResponse,
)
from app.services.llm.exceptions import NoLlmConfigured
from app.services.setbuilder import (
    curve,
    export_common,
    export_files,
    export_tidal,
    pool,
    set_service,
    vibe_enrichment,
    vibe_resolver,
)
from app.services.setbuilder.playlist_url import InvalidPlaylistUrl, parse_public_playlist_url

router = APIRouter()


def _get_owned_or_404(db: Session, set_id: int, user: User) -> Set:
    set_obj = set_service.get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


@router.post("/sets", response_model=SetDetail, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_set(
    payload: SetCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Create a new empty set owned by the current DJ."""
    set_obj = set_service.create_set(
        db, owner_id=current_user.id, name=payload.name, event_id=payload.event_id
    )
    return SetDetail.model_validate(set_obj)


@router.get("/sets", response_model=list[SetSummary])
@limiter.limit("60/minute")
def list_sets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[SetSummary]:
    """List the current DJ's sets, newest first."""
    return [SetSummary.model_validate(s) for s in set_service.list_sets(db, current_user.id)]


@router.get("/sets/{set_id}", response_model=SetDetail)
@limiter.limit("60/minute")
def get_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Get one of the current DJ's sets, or 404."""
    return SetDetail.model_validate(_get_owned_or_404(db, set_id, current_user))


@router.patch("/sets/{set_id}", response_model=SetDetail)
@limiter.limit("30/minute")
def rename_set(
    set_id: int,
    payload: SetRename,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Rename one of the current DJ's sets, or 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return SetDetail.model_validate(set_service.rename_set(db, set_obj, payload.name))


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete one of the current DJ's sets, or 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    set_service.delete_set(db, set_obj)


# ---------------------------------------------------------------------------
# Energy curve editor (#389) — templates, slot targets, vibe windows
# ---------------------------------------------------------------------------


def _builtin_templates_out() -> list[BuiltinTemplateOut]:
    return [
        BuiltinTemplateOut(name=name, points=[CurvePointModel(**p) for p in points])
        for name, points in curve.BUILTIN_TEMPLATES.items()
    ]


def _template_out(tpl) -> CurveTemplateOut:
    return CurveTemplateOut(
        id=tpl.id,
        name=tpl.name,
        points=[CurvePointModel(**p) for p in curve.template_points(tpl)],
        updated_at=tpl.updated_at,
    )


def _get_owned_template_or_404(db: Session, template_id: int, user: User):
    tpl = curve.get_owned_template(db, template_id, user.id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.get("/curve-templates", response_model=CurveTemplatesResponse)
@limiter.limit("60/minute")
def list_curve_templates(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CurveTemplatesResponse:
    """Built-in templates plus the current DJ's saved templates."""
    return CurveTemplatesResponse(
        builtin=_builtin_templates_out(),
        user=[_template_out(t) for t in curve.list_templates(db, current_user.id)],
    )


@router.post(
    "/curve-templates", response_model=CurveTemplateOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit("30/minute")
def create_curve_template(
    payload: CurveTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CurveTemplateOut:
    """Save a new per-DJ curve template."""
    points = [p.model_dump(exclude_none=True) for p in payload.points]
    return _template_out(curve.create_template(db, current_user.id, payload.name, points))


@router.put("/curve-templates/{template_id}", response_model=CurveTemplateOut)
@limiter.limit("30/minute")
def update_curve_template(
    template_id: int,
    payload: CurveTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CurveTemplateOut:
    """Overwrite one of the current DJ's templates, or 404."""
    tpl = _get_owned_template_or_404(db, template_id, current_user)
    points = [p.model_dump(exclude_none=True) for p in payload.points]
    return _template_out(curve.update_template(db, tpl, payload.name, points))


@router.delete("/curve-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_curve_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete one of the current DJ's templates, or 404."""
    tpl = _get_owned_template_or_404(db, template_id, current_user)
    curve.delete_template(db, tpl)


@router.get("/sets/{set_id}/slots", response_model=list[SlotOut])
@limiter.limit("60/minute")
def list_set_slots(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[SlotOut]:
    """Ordered timeline slots for one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    return [SlotOut.model_validate(s) for s in slots]


@router.patch("/sets/{set_id}/slots/{slot_id}/target", response_model=SlotTargetOut)
@limiter.limit("60/minute")
def update_slot_target(
    set_id: int,
    slot_id: int,
    payload: SlotTargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SlotTargetOut:
    """Set (or clear with null) a slot's energy target."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    slot = next((s for s in set_obj.slots if s.id == slot_id), None)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    slot = curve.set_slot_target(db, slot, payload.target_energy)
    return SlotTargetOut(slot_id=slot.id, target_energy=slot.target_energy)


@router.post("/sets/{set_id}/curve/apply-template", response_model=ApplyTemplateResponse)
@limiter.limit("30/minute")
def apply_curve_template(
    set_id: int,
    payload: ApplyTemplateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ApplyTemplateResponse:
    """Re-target every slot from a built-in or saved template shape."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if payload.builtin is not None:
        points = curve.BUILTIN_TEMPLATES.get(payload.builtin)
        if points is None:
            raise HTTPException(status_code=404, detail="Template not found")
    else:
        tpl = _get_owned_template_or_404(db, payload.template_id, current_user)
        points = curve.template_points(tpl)
    try:
        applied = curve.apply_points_to_slots(db, set_obj, points, payload.slot_midpoints)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApplyTemplateResponse(
        targets=[SlotTargetOut(slot_id=sid, target_energy=t) for sid, t in applied],
        windows=[TemplateWindowOut(**w) for w in curve.windows_from_points(points)],
    )


@router.get("/sets/{set_id}/vibe-windows", response_model=VibeWindowsResponse)
@limiter.limit("60/minute")
def get_vibe_windows(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> VibeWindowsResponse:
    """The set's stored vibe windows."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    windows = curve.get_vibe_windows(db, set_obj.id)
    return VibeWindowsResponse(windows=[VibeWindowModel(**w) for w in windows])


@router.put("/sets/{set_id}/vibe-windows", response_model=VibeWindowsResponse)
@limiter.limit("30/minute")
def put_vibe_windows(
    set_id: int,
    payload: VibeWindowsPut,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> VibeWindowsResponse:
    """Replace-all update of the set's vibe windows."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    stored = curve.replace_vibe_windows(db, set_obj, [w.model_dump() for w in payload.windows])
    return VibeWindowsResponse(windows=[VibeWindowModel(**w) for w in stored])


# ---------------------------------------------------------------------------
# Pool (issue #388) — candidate-track surface with per-source import/removal.
# All endpoints are owner-scoped via _get_owned_or_404.


def _pool_state(db: Session, set_id: int) -> PoolState:
    sources, tracks = pool.get_pool(db, set_id)
    return PoolState(
        sources=[PoolSourceOut.model_validate(s) for s in sources],
        tracks=[PoolTrackOut.model_validate(t) for t in tracks],
    )


def _import_result(db: Session, set_id: int, source, added: int, deduped: int) -> PoolImportResult:
    return PoolImportResult(
        added=added,
        deduped=deduped,
        source=PoolSourceOut.model_validate(source),
        pool=_pool_state(db, set_id),
    )


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
    from app.schemas.recommendation import PlaylistInfo

    tidal_connected = bool(current_user.tidal_access_token)
    beatport_connected = bool(current_user.beatport_access_token)
    tidal_playlists: list[PlaylistInfo] = []
    beatport_playlists: list[PlaylistInfo] = []

    if tidal_connected:
        from app.services.tidal import list_user_playlists as tidal_list

        tidal_playlists = [PlaylistInfo(**vars(p)) for p in tidal_list(db, current_user)]
    if beatport_connected:
        from app.services.beatport import list_user_playlists as bp_list

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
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/tidal", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_tidal(
    set_id: int,
    payload: PoolImportPlaylistIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a connected-account Tidal playlist into the pool."""
    from app.services.tidal import TidalFetchError

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
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
    return _import_result(db, set_obj.id, source, added, deduped)


@router.post("/sets/{set_id}/pool/import/beatport", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_beatport(
    set_id: int,
    payload: PoolImportPlaylistIn,
    request: Request,
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
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
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
        meta = pool.preview_public_playlist(db, current_user, parsed.provider, parsed.playlist_id)
    except pool.PoolImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    return PoolUrlPreview(provider=parsed.provider, supported=True, **meta)


@router.post("/sets/{set_id}/pool/import/url", response_model=PoolImportResult)
@limiter.limit("10/minute")
def import_pool_url(
    set_id: int,
    payload: PoolImportUrlIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PoolImportResult:
    """Import a validated public playlist URL into the pool."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        parsed = parse_public_playlist_url(payload.url)
    except InvalidPlaylistUrl as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not parsed.supported:
        raise HTTPException(status_code=422, detail=parsed.message)
    try:
        name, candidates = pool.candidates_from_public_url(
            db, current_user, parsed.provider, parsed.playlist_id
        )
    except pool.PoolImportError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    source = pool.get_or_create_source(
        db,
        set_obj,
        kind="public_url",
        external_ref=f"{parsed.provider}:{parsed.playlist_id}",
        label=name,
        meta=f"Public {parsed.provider} playlist",
    )
    added, deduped = pool.import_candidates(db, set_obj, source, candidates)
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
    added, deduped = pool.import_candidates(db, set_obj, source, [candidate])
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
<<<<<<< HEAD
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


def _unresolved_out(
    tracks: list[export_common.ExportTrack],
    reason: Literal["no_tidal_match", "missing_metadata"],
) -> list[UnresolvedTrackOut]:
    return [
        UnresolvedTrackOut(
            position=t.position,
            title=t.title,
            artist=t.artist,
            track_id=t.track_id,
            reason=reason,
        )
        for t in tracks
    ]


def _unresolved_409(unresolved: list[UnresolvedTrackOut]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "unresolved_tracks",
            "unresolved": [u.model_dump() for u in unresolved],
        },
    )


@router.post("/sets/{set_id}/export/preflight", response_model=ExportPreflightOut)
@limiter.limit("5/minute")
def export_preflight(
    set_id: int,
    payload: ExportPreflightIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportPreflightOut:
    """Pre-export resolution check (tidal targets do live Tidal matching)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    source, tracks = export_common.collect_export_tracks(set_obj)

    if payload.target == "tidal":
        if not current_user.tidal_access_token:
            return ExportPreflightOut(
                target=payload.target,
                source=source,
                total=len(tracks),
                resolved_count=0,
                unresolved=[],
                tidal_connected=False,
            )
        resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
        return ExportPreflightOut(
            target=payload.target,
            source=source,
            total=len(tracks),
            resolved_count=len(resolved),
            unresolved=_unresolved_out(unresolved, "no_tidal_match"),
            tidal_connected=True,
        )

    unresolved = export_files.file_unresolved(tracks)
    return ExportPreflightOut(
        target=payload.target,
        source=source,
        total=len(tracks),
        resolved_count=len(tracks) - len(unresolved),
        unresolved=_unresolved_out(unresolved, "missing_metadata"),
    )


@router.post("/sets/{set_id}/export/tidal", response_model=ExportTidalOut)
@limiter.limit("5/minute")
def export_set_tidal(
    set_id: int,
    payload: ExportTidalIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportTidalOut:
    """Export the setlist to a fresh Tidal playlist (DJ's existing OAuth)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not current_user.tidal_access_token:
        raise HTTPException(status_code=400, detail="Tidal account not connected")
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "no_tidal_match"))
    if not resolved:
        raise HTTPException(status_code=400, detail="No resolvable tracks to export")

    try:
        outcome = export_tidal.export_to_tidal(db, current_user, set_obj, resolved)
    except export_tidal.TidalNotConnected:
        raise HTTPException(status_code=400, detail="Tidal account not connected") from None
    except export_tidal.TidalExportError:
        raise HTTPException(status_code=502, detail="Tidal export failed") from None

    return ExportTidalOut(
        playlist_id=outcome.playlist_id,
        playlist_url=outcome.playlist_url,
        added=outcome.added,
        skipped=len(unresolved),
        exported_at=set_obj.exported_at,
        status=set_obj.status,
    )


_FILE_RENDERERS = {
    "rekordbox": (export_files.render_rekordbox_xml, "application/xml", "xml"),
    "m3u": (export_files.render_m3u, "audio/x-mpegurl", "m3u8"),
    "txt": (export_files.render_txt, "text/plain", "txt"),
}


@router.post("/sets/{set_id}/export/file")
@limiter.limit("10/minute")
def export_set_file(
    set_id: int,
    payload: ExportFileIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download the setlist as Rekordbox XML, M3U8, or plaintext."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    unresolved = export_files.file_unresolved(tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "missing_metadata"))
    exportable = [t for t in tracks if t.has_metadata]

    render, media_type, ext = _FILE_RENDERERS[payload.format]
    content = render(set_obj.name, exportable)
    filename = export_files.safe_filename(set_obj.name, ext)
    return Response(
        content=content,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

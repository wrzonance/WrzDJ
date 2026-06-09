"""WrzDJSet set-CRUD router (Phase 0).

Mounted at /api/setbuilder. Every endpoint requires an active DJ
(get_current_active_user rejects pending users). Sets are owner-private;
missing-or-unowned sets return 404 to avoid leaking existence.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.user import User
from app.schemas.setbuilder import (
    BuilderPlaylistsOut,
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
    SetCreate,
    SetDetail,
    SetRename,
    SetSummary,
)
from app.services.setbuilder import pool, set_service
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

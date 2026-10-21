"""Curve template, slot and pairing routes for WrzDJSet."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.models.user import User
from app.schemas.setbuilder import (
    BuiltinTemplateOut,
    CurvePointModel,
    CurveTemplateCreate,
    CurveTemplateOut,
    CurveTemplatesResponse,
    PairingCreate,
    PairingOut,
    PairingsState,
    PairingUpdate,
    PoolTrackOut,
    SlotOut,
)
from app.services.setbuilder import (
    curve,
    pairings,
)

router = APIRouter()


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


def get_owned_template_or_404(db: Session, template_id: int, user: User):
    tpl = curve.get_owned_template(db, template_id, user.id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


def _pairing_out(view: pairings.PairingView) -> PairingOut:
    p = view.pairing
    return PairingOut(
        id=p.id,
        set_id=p.set_id,
        from_track_id=p.from_track_id,
        into_track_id=p.into_track_id,
        cue_in_sec=p.cue_in_sec,
        note=p.note,
        tags=pairings.tags_for_pairing(p),
        use_count=p.use_count,
        from_track=PoolTrackOut.model_validate(view.from_track) if view.from_track else None,
        into_track=PoolTrackOut.model_validate(view.into_track) if view.into_track else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def pairings_state(db: Session, set_obj: Set, query: str | None = None) -> PairingsState:
    views = pairings.list_pairings(db, set_obj, query)
    return PairingsState(count=len(views), pairings=[_pairing_out(v) for v in views])


def slots_out(db: Session, set_obj: Set) -> list[SlotOut]:
    """Ordered slots with pool metadata and saved-pairing seam markers."""
    ordered = sorted(set_obj.slots, key=lambda s: s.position)
    track_ids = [s.track_id for s in ordered if s.track_id]
    pool_track_ids = [
        int(s.track_id.removeprefix("pool:"))
        for s in ordered
        if s.track_id
        and s.track_id.startswith("pool:")
        and s.track_id.removeprefix("pool:").isdigit()
    ]
    tracks_by_id: dict[str, SetPoolTrack] = {}
    if track_ids or pool_track_ids:
        query = db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id)
        filters = []
        if track_ids:
            filters.append(SetPoolTrack.track_id.in_(track_ids))
        if pool_track_ids:
            filters.append(SetPoolTrack.id.in_(pool_track_ids))
        tracks = query.filter(or_(*filters)).all()
        for track in tracks:
            if track.track_id:
                tracks_by_id[track.track_id] = track
            tracks_by_id[f"pool:{track.id}"] = track
    by_transition = {(p.from_track_id, p.into_track_id): p.id for p in set_obj.pairings}
    out: list[SlotOut] = []
    for idx, slot in enumerate(ordered):
        track = tracks_by_id.get(slot.track_id or "")
        next_slot = ordered[idx + 1] if idx + 1 < len(ordered) else None
        pairing_id = None
        if slot.track_id and next_slot and next_slot.track_id:
            pairing_id = by_transition.get((slot.track_id, next_slot.track_id))
        out.append(
            SlotOut(
                id=slot.id,
                position=slot.position,
                track_id=slot.track_id,
                locked=slot.locked,
                target_energy=slot.target_energy,
                notes=slot.notes,
                transition_score=slot.transition_score,
                transition_warnings=slot.transition_warnings,
                pool_track_id=track.id if track else None,
                title=track.title if track else None,
                artist=track.artist if track else None,
                bpm=track.bpm if track else None,
                key=track.key if track else None,
                camelot=track.camelot if track else None,
                energy=track.energy if track else None,
                duration_sec=track.duration_sec if track else None,
                next_pairing_id=pairing_id,
                next_is_dj_pairing=pairing_id is not None,
            )
        )
    return out


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
    tpl = get_owned_template_or_404(db, template_id, current_user)
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
    tpl = get_owned_template_or_404(db, template_id, current_user)
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
    return slots_out(db, set_obj)


@router.get("/sets/{set_id}/pairings", response_model=PairingsState)
@limiter.limit("60/minute")
def list_set_pairings(
    set_id: int,
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PairingsState:
    """Searchable pairings overlay state for one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return pairings_state(db, set_obj, query)


@router.post(
    "/sets/{set_id}/pairings",
    response_model=PairingOut,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": PairingOut}},
)
@limiter.limit("30/minute")
def create_set_pairing(
    set_id: int,
    payload: PairingCreate,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PairingOut:
    """Create or update a DJ-curated transition pairing."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        pairing, created = pairings.upsert_pairing(
            db,
            set_obj,
            from_track_id=payload.from_track_id,
            into_track_id=payload.into_track_id,
            cue_in_sec=payload.cue_in_sec,
            note=payload.note,
            tags=payload.tags,
            increment_use_count=payload.increment_use_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return _pairing_out(pairings.pairing_view(db, set_obj, pairing))


@router.patch("/sets/{set_id}/pairings/{pairing_id}", response_model=PairingOut)
@limiter.limit("30/minute")
def update_set_pairing(
    set_id: int,
    pairing_id: int,
    payload: PairingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PairingOut:
    """Inline-edit note, tags, and cue-in for a pairing."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    pairing = pairings.get_pairing(db, set_obj, pairing_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found")
    fields = payload.model_fields_set
    tags = (
        payload.tags
        if "tags" in fields and payload.tags is not None
        else pairings.tags_for_pairing(pairing)
    )
    updated = pairings.update_pairing(
        db,
        pairing,
        cue_in_sec=payload.cue_in_sec if "cue_in_sec" in fields else pairing.cue_in_sec,
        note=payload.note if "note" in fields else pairing.note,
        tags=tags,
    )
    return _pairing_out(pairings.pairing_view(db, set_obj, updated))


@router.delete("/sets/{set_id}/pairings/{pairing_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_set_pairing(
    set_id: int,
    pairing_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete a pairing from one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    pairing = pairings.get_pairing(db, set_obj, pairing_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found")
    pairings.delete_pairing(db, pairing)


# ---------------------------------------------------------------------------
# Play-history feedback loop (issue #403) — derive-on-read planned-vs-actual.
# Read-only on play_history AND requests; the only write is SetPairing.use_count
# via the explicit apply-pairings action.

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
    ApplyTemplateRequest,
    ApplyTemplateResponse,
    BuiltinTemplateOut,
    CurvePointModel,
    CurveTemplateCreate,
    CurveTemplateOut,
    CurveTemplatesResponse,
    SetCreate,
    SetDetail,
    SetRename,
    SetSummary,
    SlotOut,
    SlotTargetOut,
    SlotTargetUpdate,
    TemplateWindowOut,
    VibeWindowModel,
    VibeWindowsPut,
    VibeWindowsResponse,
)
from app.services.setbuilder import curve, set_service

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

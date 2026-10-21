"""Curve, slot editing, and document snapshot routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.api.setbuilder_common import transition_scores_out
from app.api.setbuilder_pairings import get_owned_template_or_404
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.setbuilder import (
    ApplyTemplateRequest,
    ApplyTemplateResponse,
    SetDocumentSnapshot,
    SlotOrderRequest,
    SlotTargetOut,
    SlotTargetUpdate,
    TemplateWindowOut,
    TransitionScoreOut,
    VibeWindowModel,
    VibeWindowsPut,
    VibeWindowsResponse,
)
from app.services.setbuilder import curve, document_snapshot, reorder

router = APIRouter()


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


@router.put(
    "/sets/{set_id}/slots/order",
    response_model=list[TransitionScoreOut],
    responses={
        400: {"description": "Invalid reorder (not a permutation, or would move a locked slot)"}
    },
)
@limiter.limit("30/minute")
def reorder_slots(
    set_id: int,
    payload: SlotOrderRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[TransitionScoreOut]:
    """Reassign the set's slot order by hand and recompute transition scores (#437)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        scores = reorder.apply_slot_order(db, set_obj, payload.slot_ids)
    except reorder.ReorderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return transition_scores_out(scores)


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
        tpl = get_owned_template_or_404(db, payload.template_id, current_user)
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


@router.get(
    "/sets/{set_id}/document",
    response_model=SetDocumentSnapshot,
    responses={404: {"description": "Set not found or not accessible"}},
)
@limiter.limit("60/minute")
def get_document_snapshot(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDocumentSnapshot:
    """Full restorable builder document snapshot for one of the current DJ's sets."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return document_snapshot.build_snapshot(set_obj)


@router.put(
    "/sets/{set_id}/document",
    response_model=SetDocumentSnapshot,
    responses={404: {"description": "Set not found or not accessible"}},
)
@limiter.limit("30/minute")
def put_document_snapshot(
    set_id: int,
    payload: SetDocumentSnapshot,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDocumentSnapshot:
    """Replace the restorable builder document with a prior snapshot."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return document_snapshot.restore_snapshot(db, set_obj, payload)

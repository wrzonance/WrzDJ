"""Per-DJ SetBuilder template routes: save-as-template, gallery, instantiate,
delete (issue #407).

Mirrors ``setbuilder_share.py``'s router pattern: owner-scoped routes mounted
under /api/setbuilder, rate-limited via the shared limiter. Templates are
private to their owner — no route or helper here touches ``SetCollaborator``
or sharing/role logic.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.set import Set
from app.models.set_template import SetTemplate
from app.models.user import User
from app.schemas.setbuilder import SetDetail
from app.schemas.setbuilder_templates import (
    InstantiateTemplateRequest,
    SaveAsTemplateRequest,
    SetTemplateCurvePointModel,
    SetTemplateGalleryResponse,
    SetTemplateOut,
)
from app.services.setbuilder import set_service, set_templates

router = APIRouter()


def _get_owned_set_or_404(db: Session, set_id: int, user: User) -> Set:
    set_obj = set_service.get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


def _require_owned_event(db: Session, event_id: int | None, user: User) -> None:
    """Reject an ``event_id`` the caller does not own.

    A set's ``event_id`` is a capability: downstream setbuilder routes read
    event-scoped data through it. Binding a set to an event the caller does
    not own is therefore never valid, and this route validates it up front
    rather than trusting the client-supplied id.
    """
    if event_id is None:
        return
    owned = (
        db.query(Event.id).filter(Event.id == event_id, Event.created_by_user_id == user.id).first()
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Event not found")


def _get_owned_template_or_404(db: Session, template_id: int, user: User) -> SetTemplate:
    tpl = set_templates.get_owned_template(db, template_id, user.id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


def _template_out(tpl: SetTemplate) -> SetTemplateOut:
    """Build the response schema explicitly from decoded JSON (no from_attributes)."""
    slots = set_templates.decode_slots(tpl.slots_json)
    curve_points = set_templates.decode_curve_points(tpl.curve_points_json)
    return SetTemplateOut(
        id=tpl.id,
        name=tpl.name,
        vibe_theme=tpl.vibe_theme,
        target_duration_sec=tpl.target_duration_sec,
        avg_transition_overlap_sec=tpl.avg_transition_overlap_sec,
        bpm_floor=tpl.bpm_floor,
        bpm_ceiling=tpl.bpm_ceiling,
        key_strictness=tpl.key_strictness,
        slot_count=len(slots),
        curve_points=[SetTemplateCurvePointModel(**p) for p in curve_points],
        created_at=tpl.created_at,
        updated_at=tpl.updated_at,
    )


@router.post(
    "/sets/{set_id}/save-as-template",
    response_model=SetTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def save_as_template(
    set_id: int,
    body: SaveAsTemplateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetTemplateOut:
    """Extract a reusable template from an owned set."""
    set_obj = _get_owned_set_or_404(db, set_id, current_user)
    tpl = set_templates.extract_template(db, set_obj, current_user.id, body.name)
    return _template_out(tpl)


@router.get("/set-templates", response_model=SetTemplateGalleryResponse)
@limiter.limit("30/minute")
def list_set_templates(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetTemplateGalleryResponse:
    """The DJ's saved templates, newest first. Always 200, even when empty."""
    templates = set_templates.list_templates(db, current_user.id)
    return SetTemplateGalleryResponse(templates=[_template_out(t) for t in templates])


@router.post(
    "/set-templates/{template_id}/instantiate",
    response_model=SetDetail,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def instantiate_set_template(
    template_id: int,
    body: InstantiateTemplateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Create a new draft set from an owned template."""
    tpl = _get_owned_template_or_404(db, template_id, current_user)
    _require_owned_event(db, body.event_id, current_user)
    new_set = set_templates.instantiate_template(db, tpl, current_user.id, body.name, body.event_id)
    return SetDetail.model_validate(new_set)


@router.delete("/set-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def delete_set_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete an owned template; repeat delete or unowned id 404s."""
    tpl = _get_owned_template_or_404(db, template_id, current_user)
    set_templates.delete_template(db, tpl)

"""Share-link + duplicate routes for WrzDJSet (issue #398).

``router`` mounts under /api/setbuilder (owner-scoped, active DJ only).
``public_router`` mounts under /api/public/setbuilder (no auth). The
share token is the sole capability for the single public GET and grants
read access only — every mutating route lives on the authenticated
router, so a leaked link can never modify anything.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.user import User
from app.schemas.setbuilder import (
    SetDetail,
    SharedCurvePointView,
    SharedSetView,
    SharedSlotView,
    ShareTokenOut,
)
from app.services.setbuilder import set_service, share_service

router = APIRouter()
public_router = APIRouter()


def _get_owned_or_404(db: Session, set_id: int, user: User) -> Set:
    set_obj = set_service.get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


@router.post("/sets/{set_id}/share", response_model=ShareTokenOut)
@limiter.limit("10/minute")
def create_or_rotate_share_token(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ShareTokenOut:
    """Create (or rotate) the read-only share token for an owned set."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    set_obj = share_service.regenerate_share_token(db, set_obj)
    return ShareTokenOut(share_token=set_obj.share_token)


@router.delete("/sets/{set_id}/share", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def revoke_share_token(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Revoke the share token for an owned set; existing links 404."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    share_service.revoke_share_token(db, set_obj)


@router.post(
    "/sets/{set_id}/duplicate",
    response_model=SetDetail,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def duplicate_set(
    set_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Duplicate an owned set (slots, curve, targets); copy is a private draft."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return SetDetail.model_validate(share_service.duplicate_set(db, set_obj))


@public_router.get("/shared/{token}", response_model=SharedSetView)
@limiter.limit("30/minute")
def view_shared_set(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> SharedSetView:
    """Public read-only projection of a shared set (no auth required).

    Unknown, revoked, and malformed tokens all return the same 404.
    """
    set_obj = share_service.get_set_by_share_token(db, token)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Not found")
    return SharedSetView(
        name=set_obj.name,
        status=set_obj.status,
        vibe_theme=set_obj.vibe_theme,
        target_duration_sec=set_obj.target_duration_sec,
        bpm_floor=set_obj.bpm_floor,
        bpm_ceiling=set_obj.bpm_ceiling,
        key_strictness=set_obj.key_strictness,
        slots=[
            SharedSlotView.model_validate(s)
            for s in sorted(set_obj.slots, key=lambda s: s.position)
        ],
        curve_points=[
            SharedCurvePointView.model_validate(c)
            for c in sorted(set_obj.curve_points, key=lambda c: c.position_sec)
        ],
    )

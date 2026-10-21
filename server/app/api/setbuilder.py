"""Core WrzDJSet routes and router assembly.

Mounted at /api/setbuilder. Every endpoint requires an active DJ
(get_current_active_user rejects pending users). Sets are owner-private;
missing-or-unowned sets return 404 to avoid leaking existence.

Pool, pairing, collaboration, and export route groups live in focused routers
included here under the same ``/api/setbuilder`` prefix.
"""

from fastapi import (
    APIRouter,
    Depends,
    Request,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db, require_owned_event_id
from app.api.setbuilder_agent import router as agent_router
from app.api.setbuilder_collaboration import router as collaboration_router
from app.api.setbuilder_common import get_owned_set_or_404 as _get_owned_or_404
from app.api.setbuilder_document import router as document_router
from app.api.setbuilder_exports import router as exports_router
from app.api.setbuilder_pairings import (
    router as pairings_router,
)
from app.api.setbuilder_playback import router as playback_router
from app.api.setbuilder_pool import router as pool_router
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.setbuilder import (
    SetCreate,
    SetDetail,
    SetRename,
    SetSummary,
    SetTargetUpdate,
    TasteProfileMoodOut,
    TasteProfileOut,
)
from app.services.setbuilder import set_service, taste_profile

router = APIRouter()
router.include_router(pool_router)
router.include_router(exports_router)
router.include_router(pairings_router)
router.include_router(collaboration_router)
router.include_router(agent_router)
router.include_router(playback_router)
router.include_router(document_router)


def _taste_profile_out(profile: taste_profile.TasteProfile) -> TasteProfileOut:
    return TasteProfileOut(
        sample_count=profile.sample_count,
        min_samples=profile.min_samples,
        active=profile.active,
        average_energy_delta=profile.average_energy_delta,
        energy_adjustment=profile.energy_adjustment,
        top_moods=[
            TasteProfileMoodOut(mood=mood.mood, count=mood.count) for mood in profile.top_moods
        ],
        summary=profile.summary,
        reset_at=profile.reset_at,
    )


@router.get("/taste-profile", response_model=TasteProfileOut)
@limiter.limit("30/minute")
def get_taste_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TasteProfileOut:
    """Return the current DJ's learned SetBuilder taste profile."""
    return _taste_profile_out(taste_profile.build_taste_profile(db, current_user.id))


@router.post("/taste-profile/reset", response_model=TasteProfileOut)
@limiter.limit("10/minute")
def reset_taste_profile(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TasteProfileOut:
    """Reset learned profile training history without deleting override rows."""
    return _taste_profile_out(taste_profile.reset_taste_profile(db, current_user.id))


@router.post("/sets", response_model=SetDetail, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_set(
    payload: SetCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Create a new empty set owned by the current DJ."""
    require_owned_event_id(db, payload.event_id, current_user)
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


@router.put("/sets/{set_id}/target", response_model=SetDetail)
@limiter.limit("30/minute")
def update_set_target(
    set_id: int,
    payload: SetTargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SetDetail:
    """Update set-length target + average transition overlap."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    return SetDetail.model_validate(
        set_service.update_target_settings(
            db,
            set_obj,
            target_duration_sec=payload.target_duration_sec,
            avg_transition_overlap_sec=payload.avg_transition_overlap_sec,
        )
    )


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
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Transport (issue #393) — queue playback commands for the attached event's Bridge.


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pool (issue #388) — candidate-track surface with per-source import/removal.
# All endpoints are owner-scoped via _get_owned_or_404.

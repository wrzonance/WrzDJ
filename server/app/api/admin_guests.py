"""Admin API endpoints for guest identity management (#862).

Mounted under `/api/admin` next to `app/api/admin.py`, which is at its file budget.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Request as FastAPIRequest
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.rate_limit import limiter
from app.models.guest import Guest
from app.models.user import User
from app.schemas.admin_guest import (
    GUEST_FILTERS,
    AdminGuestOut,
    AdminGuestProfileUpdate,
    AdminGuestUpdate,
)
from app.schemas.user import PaginatedResponse
from app.services.admin_guests import (
    NicknameTaken,
    ProfileNotFound,
    delete_guest_admin,
    get_guest_by_id,
    list_guests,
    revoke_guest_email,
    serialize_guest,
    update_guest_profile_nickname,
)

router = APIRouter()


def _load_guest(db: Session, guest_id: int) -> Guest:
    guest = get_guest_by_id(db, guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest


@router.get("/guests", response_model=PaginatedResponse)
@limiter.limit("120/minute")
def admin_list_guests(
    request: FastAPIRequest,
    page: int = Query(default=1, ge=1, le=1000),
    limit: int = Query(default=20, ge=1, le=100),
    filter: str = Query(default="all"),
    q: str | None = Query(default=None, max_length=30),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> PaginatedResponse:
    if filter not in GUEST_FILTERS:
        raise HTTPException(status_code=400, detail="Invalid guest filter")
    items, total = list_guests(db, page=page, limit=limit, filter=filter, q=q)
    return PaginatedResponse(
        items=[AdminGuestOut.model_validate(item) for item in items],
        total=total,
        page=page,
        limit=limit,
    )


@router.patch("/guests/{guest_id}", response_model=AdminGuestOut)
@limiter.limit("30/minute")
def admin_update_guest(
    guest_id: int,
    payload: AdminGuestUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AdminGuestOut:
    guest = _load_guest(db, guest_id)
    if payload.revoke_email:
        guest = revoke_guest_email(db, guest)
    return AdminGuestOut.model_validate(serialize_guest(db, guest))


@router.patch("/guests/{guest_id}/events/{event_id}", response_model=AdminGuestOut)
@limiter.limit("30/minute")
def admin_update_guest_profile(
    guest_id: int,
    event_id: int,
    payload: AdminGuestProfileUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AdminGuestOut:
    guest = _load_guest(db, guest_id)
    try:
        update_guest_profile_nickname(db, guest, event_id, payload.nickname)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail="Guest is not a member of that event")
    except NicknameTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Nickname already taken in this event"
        )
    return AdminGuestOut.model_validate(serialize_guest(db, guest))


@router.delete("/guests/{guest_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def admin_delete_guest(
    guest_id: int,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> None:
    delete_guest_admin(db, _load_guest(db, guest_id))

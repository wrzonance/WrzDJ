"""Admin API endpoints for guest identity management (#862).

Mounted under `/api/admin` next to `app/api/admin.py`, which is at its file budget.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Request as FastAPIRequest
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.admin_guest import GUEST_FILTERS, AdminGuestOut
from app.schemas.user import PaginatedResponse
from app.services.admin_guests import list_guests

router = APIRouter()


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

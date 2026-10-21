"""Apple Music DJ account-link lifecycle endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.common import StatusMessageResponse
from app.services.apple_music import accounts as apple_music_accounts
from app.services.apple_music import tokens as apple_music_tokens

router = APIRouter()

MusicUserToken = Annotated[
    str, StringConstraints(min_length=20, max_length=8192, strip_whitespace=True)
]


class AppleMusicLinkIn(BaseModel):
    music_user_token: MusicUserToken

    @field_validator("music_user_token")
    @classmethod
    def reject_invalid_header_characters(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 or ord(char) > 255 for char in value):
            raise ValueError("Invalid Music User Token")
        return value


class AppleMusicStatusOut(BaseModel):
    configured: bool
    linked: bool
    requires_reauthorization: bool
    storefront: str | None = None


@router.get("/status", response_model=AppleMusicStatusOut)
@limiter.limit("10/minute")
def status_for_user(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> AppleMusicStatusOut:
    try:
        return AppleMusicStatusOut(**apple_music_accounts.account_status(db, current_user))
    except apple_music_tokens.AppleMusicError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not check Apple Music account status",
        ) from exc


@router.post("/link", response_model=AppleMusicStatusOut)
@limiter.limit("5/minute")
def link_account(
    request: Request,
    payload: AppleMusicLinkIn,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> AppleMusicStatusOut:
    try:
        connection = apple_music_accounts.link_account(db, current_user, payload.music_user_token)
    except apple_music_tokens.AppleMusicNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Apple Music is not configured",
        ) from exc
    except apple_music_tokens.AppleMusicUserAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apple Music authorization failed. Please reconnect your account.",
        ) from exc
    except apple_music_tokens.AppleMusicLinkSuperseded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Apple Music connect was canceled. Try connecting again.",
        ) from exc
    except apple_music_tokens.AppleMusicError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify Apple Music authorization",
        ) from exc
    return AppleMusicStatusOut(**apple_music_accounts.linked_account_status(connection))


@router.post("/disconnect", response_model=StatusMessageResponse)
@limiter.limit("10/minute")
def disconnect_account(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    apple_music_accounts.disconnect_account(db, current_user)
    return StatusMessageResponse(status="ok", message="Apple Music account disconnected")

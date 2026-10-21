"""Apple Music deployment-token endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.api.deps import get_current_active_user
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.apple_music import tokens as apple_music_tokens

router = APIRouter()


class AppleMusicDeveloperTokenOut(BaseModel):
    developer_token: str
    expires_at: int


@router.get("/developer-token", response_model=AppleMusicDeveloperTokenOut)
@limiter.limit("10/minute")
def developer_token(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_active_user),
) -> AppleMusicDeveloperTokenOut:
    del current_user
    response.headers["Cache-Control"] = "no-store"
    try:
        token, expires_at = apple_music_tokens.create_developer_token()
    except apple_music_tokens.AppleMusicNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Apple Music is not configured",
        ) from exc
    return AppleMusicDeveloperTokenOut(developer_token=token, expires_at=expires_at)

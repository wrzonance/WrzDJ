"""Spotify account authorization and playlist-export status."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.spotify_oauth import (
    SpotifyOAuthError,
    authorization_url,
    cancel_authorization,
    disconnect,
    finish_authorization,
)

router = APIRouter()


class SpotifyAuthorizationOut(BaseModel):
    authorization_url: str


class SpotifyStatusOut(BaseModel):
    configured: bool
    linked: bool
    expires_at: str | None = None


def _spotify_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.spotify_client_id
        and settings.spotify_client_secret
        and settings.spotify_redirect_uri
        and settings.public_url
    )


@router.get("/status", response_model=SpotifyStatusOut)
def status_for_user(
    current_user: User = Depends(get_current_active_user),
) -> SpotifyStatusOut:
    expires_at = current_user.spotify_token_expires_at
    return SpotifyStatusOut(
        configured=_spotify_configured(),
        linked=bool(current_user.spotify_access_token),
        expires_at=expires_at.isoformat() + ("Z" if expires_at.tzinfo is None else ""),
    )


@router.post("/auth/start", response_model=SpotifyAuthorizationOut)
@limiter.limit("10/minute")
def start_authorization(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> SpotifyAuthorizationOut:
    try:
        return SpotifyAuthorizationOut(authorization_url=authorization_url(db, current_user))
    except SpotifyOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Spotify account linking is not configured",
        ) from exc


@router.get("/auth/callback")
@limiter.limit("20/minute")
def authorization_callback(
    request: Request,
    state: str = Query(..., min_length=5, max_length=200),
    code: str | None = Query(None, min_length=1, max_length=2048),
    error: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()
    if not error and code:
        try:
            finish_authorization(db, state, code)
            result = "connected"
        except SpotifyOAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif error:
        try:
            cancel_authorization(db, state)
            result = "cancelled" if error == "access_denied" else "error"
        except SpotifyOAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail="Missing Spotify authorization code")
    return RedirectResponse(
        f"{settings.public_url.rstrip('/')}/setbuilder?{urlencode({'spotify': result})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/disconnect")
@limiter.limit("10/minute")
def disconnect_account(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    disconnect(db, current_user)
    return {"status": "ok"}

"""Spotify account authorization and playlist-export status."""

import hashlib
import hmac
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
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
    refresh_access_token,
)

router = APIRouter()


class SpotifyAuthorizationOut(BaseModel):
    authorization_url: str


class SpotifyStatusOut(BaseModel):
    configured: bool
    linked: bool
    expires_at: str | None = None


OAUTH_STATE_COOKIE = "wrzdj_spotify_oauth_state"
OAUTH_STATE_COOKIE_PATH = "/api/spotify/auth/callback"


def _oauth_state_cookie_value(state: str, signing_key: str) -> str:
    """Return a browser-binding digest without storing raw OAuth state in the cookie."""
    message = f"wrzdj-spotify-oauth-state:{state}".encode()
    return hmac.new(signing_key.encode(), message, hashlib.sha256).hexdigest()


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
    db: Session = Depends(get_db),
) -> SpotifyStatusOut:
    linked = refresh_access_token(db, current_user)
    expires_at = current_user.spotify_token_expires_at
    return SpotifyStatusOut(
        configured=_spotify_configured(),
        linked=linked,
        expires_at=(
            expires_at.isoformat() + ("Z" if expires_at.tzinfo is None else "")
            if linked and expires_at
            else None
        ),
    )


@router.post("/auth/start", response_model=SpotifyAuthorizationOut)
@limiter.limit("10/minute")
def start_authorization(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> SpotifyAuthorizationOut:
    try:
        url = authorization_url(db, current_user)
        settings = get_settings()
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            _oauth_state_cookie_value(current_user.spotify_oauth_state, settings.jwt_secret),
            max_age=600,
            httponly=True,
            secure=settings.spotify_redirect_uri.startswith("https://"),
            samesite="lax",
            path=OAUTH_STATE_COOKIE_PATH,
        )
        return SpotifyAuthorizationOut(authorization_url=url)
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
    oauth_state_cookie: str | None = Cookie(None, alias=OAUTH_STATE_COOKIE),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()
    expected_cookie = _oauth_state_cookie_value(state, settings.jwt_secret)
    if (
        not oauth_state_cookie
        or not oauth_state_cookie.isascii()
        or not hmac.compare_digest(expected_cookie, oauth_state_cookie)
    ):
        raise HTTPException(status_code=400, detail="Invalid Spotify authorization state")
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
    response = RedirectResponse(
        f"{settings.public_url.rstrip('/')}/setbuilder?{urlencode({'spotify': result})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_STATE_COOKIE_PATH)
    return response


@router.post("/disconnect")
@limiter.limit("10/minute")
def disconnect_account(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    disconnect(db, current_user)
    return {"status": "ok"}

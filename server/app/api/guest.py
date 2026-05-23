"""Public API endpoint for guest identity resolution."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.rate_limit import get_client_ip, get_guest_id, limiter
from app.schemas.guest import IdentifyRequest, IdentifyResponse
from app.schemas.human_verification import (
    VerifyHumanRequest,
    VerifyHumanResponse,
    VerifyStatusResponse,
)
from app.services.guest_identity import identify_guest
from app.services.human_verification import (
    COOKIE_NAME,
    _b64decode,
    issue_human_cookie,
    verify_human_cookie,
)
from app.services.turnstile import verify_turnstile_token

router = APIRouter()
settings = get_settings()


@router.post("/guest/identify", response_model=IdentifyResponse)
@limiter.limit("120/minute")
def identify(
    payload: IdentifyRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Resolve guest identity via cookie token and/or browser fingerprint."""
    token_from_cookie = request.cookies.get("wrzdj_guest")
    user_agent = (request.headers.get("user-agent") or "")[:512]

    result = identify_guest(
        db,
        token_from_cookie=token_from_cookie,
        fingerprint_hash=payload.fingerprint_hash,
        fingerprint_components=payload.fingerprint_components,
        user_agent=user_agent,
    )

    response = JSONResponse(
        content={
            "guest_id": result.guest_id,
            "action": result.action,
            "reconcile_hint": result.reconcile_hint,
        }
    )

    if result.token:
        is_prod = settings.env == "production"
        response.set_cookie(
            key="wrzdj_guest",
            value=result.token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=31536000,
            path="/api/",
        )

    return response


@router.post("/guest/verify-human", response_model=VerifyHumanResponse)
@limiter.limit("10/minute")
async def verify_human(
    payload: VerifyHumanRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> VerifyHumanResponse:
    """Validate a Turnstile token and issue a wrzdj_human session cookie."""
    guest_id = get_guest_id(request, db)
    if guest_id is None:
        raise HTTPException(status_code=400, detail="Guest identity required")

    client_ip = get_client_ip(request)
    is_valid = await verify_turnstile_token(payload.turnstile_token, client_ip)
    if not is_valid:
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed")

    issue_human_cookie(response, guest_id)

    return VerifyHumanResponse(verified=True, expires_in=settings.human_cookie_ttl_seconds)


@router.get("/guest/verify-status", response_model=VerifyStatusResponse)
@limiter.limit("60/minute")
def verify_status(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> VerifyStatusResponse:
    """Report whether the caller already has a valid wrzdj_human cookie.

    Returns verified=false on missing, expired, version-mismatched, or
    tampered cookies. No side effects (no cookie refresh, no DB writes).
    Safe to call on every page mount.
    """
    response.headers["Cache-Control"] = "no-store, private"

    guest_id = verify_human_cookie(request)
    if guest_id is None:
        return VerifyStatusResponse(verified=False, expires_in=0)

    import json as _json

    raw = request.cookies.get(COOKIE_NAME)
    payload_part, _sig = raw.rsplit(".", 1)
    payload = _json.loads(_b64decode(payload_part))
    from app.core.time import utcnow

    remaining = max(0, int(payload["exp"]) - int(utcnow().timestamp()))
    return VerifyStatusResponse(verified=True, expires_in=remaining)

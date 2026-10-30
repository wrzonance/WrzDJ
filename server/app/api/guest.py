"""Public API endpoint for guest identity resolution."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core import config as core_config
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
    record_human_verification,
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
    from app.core.rate_limit import is_inert_dev_token

    token_from_cookie = request.cookies.get("wrzdj_guest")
    # A leaked dev-bypass guest row must not be claimable or re-tokenizable here when
    # the bypass is off — drop the reserved token so identity resolves as cookieless.
    if is_inert_dev_token(token_from_cookie):
        token_from_cookie = None
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

    # A cookie hit re-sets the same token, so the lifetime counts from the last visit
    # (and cookies issued with an older, longer Max-Age pick up the current one).
    token = result.token or (token_from_cookie if result.action == "cookie_hit" else None)
    if token:
        is_prod = settings.env == "production"
        response.set_cookie(
            key="wrzdj_guest",
            value=token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=settings.guest_cookie_max_age_seconds,
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

    record_human_verification(db, guest_id)
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
    tampered cookies, and on a cookie bound to a guest other than the
    caller's current wrzdj_guest (after a merge, delete, or re-identify),
    because require_verified_human would reject that cookie (#874). No side
    effects (no cookie refresh, no DB writes). Safe to call on every page mount.
    """
    response.headers["Cache-Control"] = "no-store, private"

    guest_id = verify_human_cookie(request)
    if guest_id is None:
        return VerifyStatusResponse(verified=False, expires_in=0)

    # DEV-ONLY: the gates accept any caller under the bypass, and resolving the
    # guest here would create the dev guest row — a write this probe must not make.
    bypass = core_config.get_settings().auth_bypass_enabled
    if not bypass and get_guest_id(request, db) != guest_id:
        return VerifyStatusResponse(verified=False, expires_in=0)

    import json as _json

    raw = request.cookies.get(COOKIE_NAME)
    payload_part, _sig = raw.rsplit(".", 1)
    payload = _json.loads(_b64decode(payload_part))
    from app.core.time import utcnow

    remaining = max(0, int(payload["exp"]) - int(utcnow().timestamp()))
    return VerifyStatusResponse(verified=True, expires_in=remaining)

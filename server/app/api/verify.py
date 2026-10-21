"""Public API endpoints for guest email verification."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.rate_limit import get_client_ip, get_guest_id, limiter
from app.schemas.verify import (
    VerifyConfirmResponse,
    VerifyConfirmSchema,
    VerifyRequestResponse,
    VerifyRequestSchema,
)
from app.services.email_sender import EmailNotConfiguredError, EmailSendError
from app.services.email_verification import (
    CodeExpiredError,
    CodeInvalidError,
    RateLimitExceededError,
    confirm_verification_code,
    create_verification_code,
)
from app.services.human_verification import issue_human_cookie, verify_human_cookie
from app.services.turnstile import verify_turnstile_token

router = APIRouter()


@router.post("/verify/request", response_model=VerifyRequestResponse)
@limiter.limit("10/minute")
async def request_verification_code(
    payload: VerifyRequestSchema,
    request: Request,
    db: Session = Depends(get_db),
) -> VerifyRequestResponse:
    """Send a verification code to the provided email.

    Requires a fresh Turnstile token (separate from the session cookie) to
    protect against email-cost / sender-reputation abuse.
    """
    is_valid = await verify_turnstile_token(payload.turnstile_token, get_client_ip(request))
    if not is_valid:
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed")

    guest_id = get_guest_id(request, db)
    if guest_id is None:
        raise HTTPException(status_code=400, detail="Guest identity required")

    try:
        create_verification_code(db, guest_id=guest_id, email=payload.email)
    except RateLimitExceededError:
        raise HTTPException(status_code=429, detail="Too many codes requested")
    except (EmailNotConfiguredError, EmailSendError):
        raise HTTPException(status_code=422, detail="Email verification is temporarily unavailable")

    return VerifyRequestResponse(sent=True)


@router.post("/verify/confirm", response_model=VerifyConfirmResponse)
@limiter.limit("10/minute")
def confirm_code(
    payload: VerifyConfirmSchema,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Confirm a verification code. May trigger guest merge."""
    guest_id = get_guest_id(request, db)
    if guest_id is None:
        raise HTTPException(status_code=400, detail="Guest identity required")

    try:
        result = confirm_verification_code(
            db,
            guest_id=guest_id,
            email=payload.email,
            code=payload.code,
        )
    except CodeInvalidError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except CodeExpiredError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = JSONResponse(
        content={
            "verified": result.verified,
            "guest_id": result.guest_id,
            "merged": result.merged,
        }
    )

    if result.new_token:
        is_prod = get_settings().env == "production"
        response.set_cookie(
            key="wrzdj_guest",
            value=result.new_token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=31536000,
            path="/api/",
        )
        # A merge rotated this browser's identity to the surviving guest. Its
        # wrzdj_human cookie is HMAC-bound to the source guest, which no longer
        # exists, so every gated call would 403 until it expired (#874). The
        # browser already proved it is human for this session: carry that proof
        # over. Never mint one the browser did not earn.
        if verify_human_cookie(request) == guest_id:
            issue_human_cookie(response, result.guest_id)

    return response

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_current_user, get_db
from app.core.config import get_settings
from app.core.lockout import lockout_manager
from app.core.rate_limit import get_client_ip, limiter
from app.models.user import User, UserRole
from app.schemas.auth import Token
from app.schemas.common import StatusMessageResponse
from app.schemas.user import (
    ChangePasswordRequest,
    HelpPageSeenRequest,
    PublicSettings,
    RegisterRequest,
    RequestEmailChangeRequest,
    UserOut,
)
from app.services import account as account_service
from app.services.account import (
    EmailTakenError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenUsedError,
)
from app.services.auth import (
    authenticate_user,
    create_access_token,
    create_user,
    get_user_by_username,
)
from app.services.email_sender import EmailNotConfiguredError, EmailSendError
from app.services.system_settings import get_system_settings
from app.services.turnstile import verify_turnstile_token

router = APIRouter()
settings = get_settings()


class MePreferencesUpdate(BaseModel):
    frictionless_join_default: bool


@router.post("/login", response_model=Token)
@limiter.limit(lambda: f"{settings.login_rate_limit_per_minute}/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    client_ip = get_client_ip(request)
    username = form_data.username

    # Check lockout status
    if settings.is_lockout_enabled:
        is_locked, seconds_remaining = lockout_manager.is_locked_out(client_ip, username)
        if is_locked:
            mins = seconds_remaining // 60 + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Try again in {mins} minutes.",
                headers={"Retry-After": str(seconds_remaining)},
            )

    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        # Record failed attempt
        if settings.is_lockout_enabled:
            is_locked, lockout_seconds = lockout_manager.record_failure(client_ip, username)
            if is_locked:
                mins = lockout_seconds // 60
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many failed attempts. Try again in {mins} minutes.",
                    headers={"Retry-After": str(lockout_seconds)},
                )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Clear lockout on success
    if settings.is_lockout_enabled:
        lockout_manager.record_success(client_ip, username)

    access_token = create_access_token(data={"sub": user.username, "tv": user.token_version})
    return Token(access_token=access_token)


@router.post("/logout", response_model=StatusMessageResponse)
@limiter.limit("30/minute")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    """Invalidate all outstanding JWTs for the current user.

    SECURITY (CRIT-2): bumps token_version so every previously-issued JWT
    for this user fails the version check in get_current_user.
    """
    current_user.token_version += 1
    db.commit()
    return StatusMessageResponse(status="ok", message="Logged out")


@router.get("/me", response_model=UserOut)
@limiter.limit("60/minute")
def get_me(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    pending = account_service.get_active_pending_email_change(db, current_user.id)
    data = UserOut.model_validate(current_user).model_dump()
    data["pending_email"] = pending.new_email if pending else None
    return data


@router.patch("/me/password", response_model=StatusMessageResponse)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    try:
        account_service.change_password(db, current_user, body.current_password, body.new_password)
    except ValueError:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return StatusMessageResponse(status="ok", message="Password updated. Please log in again.")


@router.patch("/me/preferences", response_model=UserOut)
@limiter.limit("20/minute")
def update_me_preferences(
    body: MePreferencesUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    updated = account_service.update_preferences(
        db, current_user, frictionless_join_default=body.frictionless_join_default
    )
    return UserOut.model_validate(updated)


@router.post("/me/email/request", response_model=StatusMessageResponse)
@limiter.limit("3/minute")
def request_email_change(
    request: Request,
    body: RequestEmailChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    try:
        account_service.request_email_change(
            db, current_user, body.current_password, body.new_email
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Incorrect password or email already in use",
        )
    except (EmailNotConfiguredError, EmailSendError):
        raise HTTPException(status_code=422, detail="Email service temporarily unavailable")
    return StatusMessageResponse(status="ok", message="Confirmation email sent")


@router.get("/email/confirm", response_model=StatusMessageResponse)
@limiter.limit("10/minute")
def confirm_email_change(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    try:
        account_service.confirm_email_change(db, token)
    except TokenNotFoundError:
        raise HTTPException(status_code=400, detail="Invalid confirmation link")
    except TokenExpiredError:
        raise HTTPException(status_code=400, detail="Confirmation link has expired")
    except TokenUsedError:
        raise HTTPException(status_code=400, detail="Confirmation link has already been used")
    except EmailTakenError:
        raise HTTPException(status_code=409, detail="Email address is already in use")
    return StatusMessageResponse(status="ok", message="Email updated")


@router.post("/help-seen", response_model=StatusMessageResponse)
@limiter.limit("30/minute")
def mark_help_page_seen(
    request: Request,
    body: HelpPageSeenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    """Mark a help page as seen for the current user."""
    current_user.mark_help_page_seen(body.page)
    db.commit()
    return StatusMessageResponse(status="ok", message="OK")


@router.get("/settings", response_model=PublicSettings)
@limiter.limit("30/minute")
def get_public_settings(request: Request, db: Session = Depends(get_db)) -> PublicSettings:
    """Public endpoint returning registration status and Turnstile site key."""
    sys_settings = get_system_settings(db)
    return PublicSettings(
        registration_enabled=sys_settings.registration_enabled,
        turnstile_site_key=settings.turnstile_site_key,
    )


@router.post("/register", response_model=StatusMessageResponse)
@limiter.limit(lambda: f"{settings.registration_rate_limit_per_minute}/minute")
async def register(
    request: Request,
    reg_data: RegisterRequest,
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    """Register a new user (pending approval)."""
    # Check if registration is enabled
    sys_settings = get_system_settings(db)
    if not sys_settings.registration_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently disabled",
        )

    # Verify Turnstile token
    client_ip = get_client_ip(request)
    is_valid = await verify_turnstile_token(reg_data.turnstile_token, client_ip)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CAPTCHA verification failed",
        )

    # Check username and email uniqueness (generic message to prevent enumeration)
    if get_user_by_username(db, reg_data.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration failed. Username or email already in use.",
        )

    existing_email = db.query(User).filter(User.email == reg_data.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration failed. Username or email already in use.",
        )

    # Create pending user
    user = create_user(db, reg_data.username, reg_data.password, role=UserRole.PENDING.value)
    user.email = reg_data.email
    db.commit()

    return StatusMessageResponse(
        status="ok",
        message="Registration submitted. An admin will review your account.",
    )

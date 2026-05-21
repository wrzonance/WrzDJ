from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.event import Event
from app.models.request import Request as SongRequest
from app.models.user import User, UserRole
from app.services.auth import decode_token, get_user_by_username
from app.services.event import get_event_by_code_for_owner

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = decode_token(token)
    if token_data is None or token_data.username is None:
        raise credentials_exception
    user = get_user_by_username(db, token_data.username)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # CRIT-2: reject tokens whose version doesn't match the user's current version
    if token_data.token_version != user.token_version:
        raise credentials_exception
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Reject pending users from accessing DJ features."""
    if current_user.role == UserRole.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending approval",
        )
    return current_user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Only allow admin users."""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_owned_event(
    code: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Event:
    """Get an event owned by the current user, or raise 404."""
    event = get_event_by_code_for_owner(db, code, current_user)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def get_event_for_dj_or_admin(
    code: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Event:
    """Get an event accessible to the current user (owner or admin).

    Returns 404 if the event doesn't exist, 403 if the user neither owns it
    nor has admin role. Used by pre-event-collection endpoints where admins
    need to inspect/mutate events they don't own.
    """
    event = db.query(Event).filter(Event.code == code).one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.created_by_user_id != current_user.id and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Forbidden")
    return event


def get_owned_event_by_id(
    event_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Event:
    """Get an event by ID owned by the current user, or raise 404.

    Returns 404 (not 403) to avoid leaking event existence.
    """
    event = (
        db.query(Event)
        .filter(Event.id == event_id, Event.created_by_user_id == current_user.id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def get_owned_request(
    request_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> SongRequest:
    """Get a song request whose event is owned by the current user, or raise 404.

    Returns 404 (not 403) to avoid leaking request/event existence.
    """
    song_request = db.query(SongRequest).filter(SongRequest.id == request_id).first()
    if not song_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if song_request.event.created_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Request not found")
    return song_request


def require_verified_human(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> int:
    """Require a valid wrzdj_human cookie tied to the current wrzdj_guest.

    Refreshes (slides) the cookie on every successful call. Raises 403 with
    structured detail {"code": "human_verification_required"} so the frontend
    can distinguish this from generic forbidden errors and trigger a re-bootstrap.
    """
    from app.core.rate_limit import get_guest_id
    from app.services.human_verification import issue_human_cookie, verify_human_cookie

    guest_id_cookie = verify_human_cookie(request)
    guest_id_db = get_guest_id(request, db)

    if guest_id_cookie is None or guest_id_db is None or guest_id_cookie != guest_id_db:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "human_verification_required"},
        )

    issue_human_cookie(response, guest_id_db)
    return guest_id_db


def require_verified_human_soft(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> int | None:
    """Soft-mode wrapper around require_verified_human.

    Reads SystemSettings.human_verification_enforced. When False (rollout
    Phase 1), a missing/invalid cookie logs a warning and returns the guest_id
    (or None) without raising. When True (Phase 2+), behaves identically to
    require_verified_human and raises 403.

    Apply this dependency to all gated public endpoints during rollout. After
    Phase 3 cleanup, swap to require_verified_human directly and remove this.
    """
    import logging

    from app.core.rate_limit import get_guest_id
    from app.services.human_verification import issue_human_cookie, verify_human_cookie
    from app.services.system_settings import get_system_settings

    sys_settings = get_system_settings(db)
    guest_id_cookie = verify_human_cookie(request)
    guest_id_db = get_guest_id(request, db)

    if guest_id_cookie is not None and guest_id_db is not None and guest_id_db == guest_id_cookie:
        issue_human_cookie(response, guest_id_db)
        return guest_id_db

    if sys_settings.human_verification_enforced:
        raise HTTPException(
            status_code=403,
            detail={"code": "human_verification_required"},
        )

    # Soft-mode: log structured warning, pass through
    logging.getLogger(__name__).warning(
        "guest.human_verify action=missing guest_id=%s reason=soft_mode_pass",
        guest_id_db,
    )
    return guest_id_db


def require_email_verified(
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_verified_human),
) -> int:
    """Require an email-verified guest. Chains require_verified_human (hard mode).

    Apply to every mutating collection-phase endpoint AND personal-data GETs.
    Returns 403 with structured detail {"code": "email_verification_required"}
    so the frontend can render the EmailGate component.
    """
    from app.models.guest import Guest

    guest = db.get(Guest, guest_id)
    if guest is None or guest.verified_email is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "email_verification_required"},
        )
    return guest_id

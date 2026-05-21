"""Kiosk pairing and management API endpoints."""

import hmac
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import get_client_ip, limiter
from app.models.event import Event
from app.models.user import User
from app.schemas.kiosk import (
    KioskAssignRequest,
    KioskCompletePairingRequest,
    KioskOut,
    KioskPairResponse,
    KioskPairStatusResponse,
    KioskRenameRequest,
    KioskSessionResponse,
)
from app.services.kiosk import (
    assign_kiosk_event,
    complete_pairing,
    create_kiosk,
    delete_kiosk,
    get_kiosk_by_id,
    get_kiosk_by_pair_code,
    get_kiosk_by_session_token,
    get_kiosks_for_user,
    is_pair_code_expired,
    rename_kiosk,
    update_kiosk_last_seen,
)

# In-memory nonce cache for kiosk pairing. Safe under single-worker uvicorn.
# {client_ip: (nonce_str, expires_at_unix_timestamp)}
# If deploy ever moves to multi-worker, replace with KioskPairChallenge DB model.
_pair_nonces: dict[str, tuple[str, float]] = {}
_NONCE_TTL_SECONDS = 10


class KioskPairChallengeResponse(BaseModel):
    nonce: str
    expires_in: int


# Public endpoints (no auth) — for kiosk devices
public_router = APIRouter()

# Authenticated endpoints — for DJs managing kiosks
auth_router = APIRouter()


def _resolve_event_name(db: Session, event_code: str | None) -> str | None:
    """Look up the event name for a given collection code, or return None."""
    if not event_code:
        return None
    event = db.query(Event).filter(Event.code == event_code).first()
    return event.name if event else None


def _resolve_event_join_code(db: Session, event_code: str | None) -> str | None:
    """Look up the join_code for an event identified by its collection code."""
    if not event_code:
        return None
    event = db.query(Event).filter(Event.code == event_code).first()
    return event.join_code if event else None


def _assert_caller_owns_event(event: Event, user: User) -> None:
    """Enforce that the caller owns the target event (or is an admin).

    SECURITY (CRIT-3, CRIT-4): before this check, any DJ could pair or
    reassign a kiosk to an event owned by another DJ by supplying the
    victim's event code. See docs/security/audit-2026-04-08.md.
    """
    if user.role == "admin":
        return
    if event.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this event")


# ── Public endpoints ───────────────────────────────────────────────────


@public_router.get("/pair-challenge", response_model=KioskPairChallengeResponse)
@limiter.limit("10/minute")
def get_pair_challenge(request: Request) -> KioskPairChallengeResponse:
    """Issue a one-time IP-bound nonce required for kiosk pairing."""
    client_ip = get_client_ip(request)
    now = time.time()
    # Opportunistic prune of expired entries
    expired = [ip for ip, (_, exp) in _pair_nonces.items() if exp < now]
    for ip in expired:
        _pair_nonces.pop(ip, None)

    nonce = secrets.token_urlsafe(16)
    _pair_nonces[client_ip] = (nonce, now + _NONCE_TTL_SECONDS)
    return KioskPairChallengeResponse(nonce=nonce, expires_in=_NONCE_TTL_SECONDS)


@public_router.post("/pair", response_model=KioskPairResponse)
@limiter.limit("3/minute")
def create_pairing(request: Request, db: Session = Depends(get_db)):
    """Create a new kiosk pairing session.

    Requires a valid X-Pair-Nonce header obtained from /pair-challenge,
    bound to the same client IP. Nonce is consumed on use.
    """
    client_ip = get_client_ip(request)
    nonce_header = request.headers.get("X-Pair-Nonce")
    entry = _pair_nonces.pop(client_ip, None)

    if not nonce_header or entry is None:
        raise HTTPException(400, "Missing or unknown pairing nonce")

    nonce, expires_at = entry
    if not hmac.compare_digest(nonce_header, nonce):
        raise HTTPException(400, "Invalid pairing nonce")
    if time.time() > expires_at:
        raise HTTPException(400, "Pairing nonce expired")

    kiosk = create_kiosk(db)
    return KioskPairResponse(
        pair_code=kiosk.pair_code,
        session_token=kiosk.session_token,
        expires_at=kiosk.pair_expires_at,
    )


@public_router.get("/pair/{pair_code}/status", response_model=KioskPairStatusResponse)
@limiter.limit("180/minute")
def get_pair_status(pair_code: str, request: Request, db: Session = Depends(get_db)):
    """Poll the status of a pairing code."""
    kiosk = get_kiosk_by_pair_code(db, pair_code)
    if not kiosk:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    # Check if expired and still in pairing state
    if kiosk.status == "pairing" and is_pair_code_expired(kiosk):
        return KioskPairStatusResponse(status="expired")

    event_name = _resolve_event_name(db, kiosk.event_code)
    event_join_code = _resolve_event_join_code(db, kiosk.event_code)
    return KioskPairStatusResponse(
        status=kiosk.status,
        event_code=kiosk.event_code,
        event_join_code=event_join_code,
        event_name=event_name,
    )


@public_router.get("/session/assignment", response_model=KioskSessionResponse)
@limiter.limit("60/minute")
def get_session_assignment(request: Request, db: Session = Depends(get_db)):
    """Poll the kiosk's current event assignment. Updates last_seen_at.

    Session token must be sent in the X-Kiosk-Session header (not in the URL path)
    to prevent token leakage in access logs.
    """
    session_token = request.headers.get("X-Kiosk-Session")
    if not session_token:
        raise HTTPException(status_code=401, detail="Missing X-Kiosk-Session header")

    kiosk = get_kiosk_by_session_token(db, session_token)
    if not kiosk:
        raise HTTPException(status_code=404, detail="Kiosk session not found")

    # Check if expired and still in pairing state
    if kiosk.status == "pairing" and is_pair_code_expired(kiosk):
        return KioskSessionResponse(status="expired")

    # Update last_seen for active kiosks
    if kiosk.status == "active":
        update_kiosk_last_seen(db, kiosk)

    event_name = _resolve_event_name(db, kiosk.event_code)
    event_join_code = _resolve_event_join_code(db, kiosk.event_code)
    return KioskSessionResponse(
        status=kiosk.status,
        event_code=kiosk.event_code,
        event_join_code=event_join_code,
        event_name=event_name,
    )


# ── Authenticated endpoints ────────────────────────────────────────────


@auth_router.post("/pair/{pair_code}/complete", response_model=KioskOut)
@limiter.limit("30/minute")
def complete_kiosk_pairing(
    pair_code: str,
    body: KioskCompletePairingRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Complete a kiosk pairing by assigning an event."""
    kiosk = get_kiosk_by_pair_code(db, pair_code)
    if not kiosk:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    # Validate event exists
    event = db.query(Event).filter(Event.code == body.event_code.upper()).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # CRIT-3: caller must own the target event (or be admin)
    _assert_caller_owns_event(event, current_user)

    try:
        complete_pairing(db, kiosk, event.code, current_user.id)
    except ValueError as e:
        msg = str(e)
        if "expired" in msg:
            raise HTTPException(status_code=410, detail="Pairing code has expired")
        if "already paired" in msg:
            raise HTTPException(status_code=409, detail="Kiosk is already paired")
        raise HTTPException(status_code=400, detail=msg)

    return KioskOut(
        id=kiosk.id,
        name=kiosk.name,
        event_code=kiosk.event_code,
        event_join_code=event.join_code,
        event_name=event.name,
        status=kiosk.status,
        paired_at=kiosk.paired_at,
        last_seen_at=kiosk.last_seen_at,
    )


@auth_router.get("/mine", response_model=list[KioskOut])
@limiter.limit("60/minute")
def list_my_kiosks(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List all kiosks paired by the current user."""
    kiosks = get_kiosks_for_user(db, current_user.id)
    return [
        KioskOut(
            id=k.id,
            name=k.name,
            event_code=k.event_code,
            event_join_code=_resolve_event_join_code(db, k.event_code),
            event_name=_resolve_event_name(db, k.event_code),
            status=k.status,
            paired_at=k.paired_at,
            last_seen_at=k.last_seen_at,
        )
        for k in kiosks
    ]


def _get_owned_kiosk(db: Session, kiosk_id: int, user: User):
    """Get a kiosk owned by the user, or raise 403/404."""
    kiosk = get_kiosk_by_id(db, kiosk_id)
    if not kiosk:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    if kiosk.paired_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your kiosk")
    return kiosk


@auth_router.patch("/{kiosk_id}/assign", response_model=KioskOut)
@limiter.limit("30/minute")
def assign_kiosk(
    kiosk_id: int,
    body: KioskAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Change which event a kiosk displays."""
    kiosk = _get_owned_kiosk(db, kiosk_id, current_user)

    event = db.query(Event).filter(Event.code == body.event_code.upper()).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # CRIT-4: caller must own the target event (or be admin)
    _assert_caller_owns_event(event, current_user)

    assign_kiosk_event(db, kiosk, event.code)
    return KioskOut(
        id=kiosk.id,
        name=kiosk.name,
        event_code=kiosk.event_code,
        event_join_code=event.join_code,
        event_name=event.name,
        status=kiosk.status,
        paired_at=kiosk.paired_at,
        last_seen_at=kiosk.last_seen_at,
    )


@auth_router.patch("/{kiosk_id}", response_model=KioskOut)
@limiter.limit("30/minute")
def rename_kiosk_endpoint(
    kiosk_id: int,
    body: KioskRenameRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Rename a kiosk."""
    kiosk = _get_owned_kiosk(db, kiosk_id, current_user)
    rename_kiosk(db, kiosk, body.name)
    return KioskOut(
        id=kiosk.id,
        name=kiosk.name,
        event_code=kiosk.event_code,
        event_join_code=_resolve_event_join_code(db, kiosk.event_code),
        event_name=_resolve_event_name(db, kiosk.event_code),
        status=kiosk.status,
        paired_at=kiosk.paired_at,
        last_seen_at=kiosk.last_seen_at,
    )


@auth_router.delete("/{kiosk_id}", status_code=204)
@limiter.limit("30/minute")
def delete_kiosk_endpoint(
    kiosk_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Unpair and delete a kiosk."""
    kiosk = _get_owned_kiosk(db, kiosk_id, current_user)
    delete_kiosk(db, kiosk)

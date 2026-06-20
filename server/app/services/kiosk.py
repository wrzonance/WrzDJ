"""Kiosk pairing and management service."""

import secrets
import string
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.kiosk import Kiosk

# Same safe alphabet as event codes — no O/0/I/1
_ALPHABET = string.ascii_uppercase + string.digits
_ALPHABET = _ALPHABET.replace("0", "").replace("O", "").replace("I", "").replace("1", "")

PAIR_CODE_LENGTH = 6
PAIR_EXPIRY_MINUTES = 5


def generate_pair_code(length: int = PAIR_CODE_LENGTH) -> str:
    """Generate a random alphanumeric pair code using safe characters."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def create_kiosk(db: Session) -> Kiosk:
    """Create a new kiosk pairing session.

    Lazily cleans up expired pairing records before creating a new one.
    """
    cleanup_expired_pairing_kiosks(db)

    # Generate unique pair code
    while True:
        pair_code = generate_pair_code()
        existing = db.query(Kiosk).filter(Kiosk.pair_code == pair_code).first()
        if not existing:
            break

    session_token = secrets.token_hex(32)
    kiosk = Kiosk(
        pair_code=pair_code,
        session_token=session_token,
        status="pairing",
        pair_expires_at=utcnow() + timedelta(minutes=PAIR_EXPIRY_MINUTES),
    )
    db.add(kiosk)
    db.commit()
    db.refresh(kiosk)
    return kiosk


def get_kiosk_by_pair_code(db: Session, code: str) -> Kiosk | None:
    """Find a kiosk by its pair code (case-insensitive)."""
    return db.query(Kiosk).filter(Kiosk.pair_code == code.upper()).first()


def get_kiosk_by_session_token(db: Session, token: str) -> Kiosk | None:
    """Find a kiosk by its session token."""
    return db.query(Kiosk).filter(Kiosk.session_token == token).first()


def is_trusted_kiosk_for_event(db: Session, session_token: str | None, event: Event) -> bool:
    """True when `session_token` identifies an active kiosk paired to `event`.

    A DJ-paired kiosk is a trusted physical device controlled by the event
    owner, so — like the authenticated owner — it bypasses the guest
    human-verification gate on public event endpoints. Scoped to the kiosk's
    assigned event (its stored collection `code`) so one kiosk's token cannot
    vouch for a different event, and only `active` kiosks qualify.
    """
    if not session_token:
        return False
    kiosk = get_kiosk_by_session_token(db, session_token)
    return kiosk is not None and kiosk.status == "active" and kiosk.event_code == event.code


def get_kiosk_by_id(db: Session, kiosk_id: int) -> Kiosk | None:
    """Find a kiosk by its ID."""
    return db.query(Kiosk).filter(Kiosk.id == kiosk_id).first()


def is_pair_code_expired(kiosk: Kiosk) -> bool:
    """Check whether a kiosk's pairing code has expired."""
    return kiosk.pair_expires_at <= utcnow()


def complete_pairing(db: Session, kiosk: Kiosk, event_code: str, user_id: int) -> Kiosk:
    """Complete the pairing process for a kiosk.

    Raises:
        ValueError: If kiosk is already paired or pair code has expired.
    """
    if kiosk.status != "pairing":
        raise ValueError("Kiosk is already paired")
    if is_pair_code_expired(kiosk):
        raise ValueError("Pair code has expired")

    kiosk.status = "active"
    kiosk.event_code = event_code
    kiosk.paired_by_user_id = user_id
    kiosk.paired_at = utcnow()
    db.commit()
    db.refresh(kiosk)
    return kiosk


def update_kiosk_last_seen(db: Session, kiosk: Kiosk) -> None:
    """Update the kiosk's last seen timestamp."""
    kiosk.last_seen_at = utcnow()
    db.commit()


def assign_kiosk_event(db: Session, kiosk: Kiosk, event_code: str) -> Kiosk:
    """Change which event a kiosk displays."""
    kiosk.event_code = event_code
    db.commit()
    db.refresh(kiosk)
    return kiosk


def rename_kiosk(db: Session, kiosk: Kiosk, name: str | None) -> Kiosk:
    """Rename a kiosk (or clear the name with None)."""
    kiosk.name = name
    db.commit()
    db.refresh(kiosk)
    return kiosk


def delete_kiosk(db: Session, kiosk: Kiosk) -> None:
    """Delete a kiosk record."""
    db.delete(kiosk)
    db.commit()


def delete_kiosks_for_event(db: Session, event_code: str) -> int:
    """Delete all kiosks bound to a given event code (does not commit).

    Called when an event is deleted so kiosks don't dangle pointing at a
    non-existent event — which previously bricked the device on the pairing
    screen (issue #474). Returns the number of kiosks removed; the caller is
    responsible for committing.
    """
    return db.query(Kiosk).filter(Kiosk.event_code == event_code).delete(synchronize_session=False)


def get_kiosks_for_user(db: Session, user_id: int) -> list[Kiosk]:
    """Get all kiosks paired by a specific user."""
    return (
        db.query(Kiosk)
        .filter(Kiosk.paired_by_user_id == user_id)
        .order_by(Kiosk.created_at.desc())
        .all()
    )


def cleanup_expired_pairing_kiosks(db: Session) -> int:
    """Delete kiosks that are still in 'pairing' status past their expiry.

    Returns the number of deleted records.
    """
    now = utcnow()
    count = (
        db.query(Kiosk)
        .filter(
            Kiosk.status == "pairing",
            Kiosk.pair_expires_at <= now,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return count

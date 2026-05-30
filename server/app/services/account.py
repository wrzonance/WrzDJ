"""Self-service credential management: password change, email change."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models.pending_email_change import PendingEmailChange
from app.models.user import User
from app.services.auth import get_password_hash, verify_password
from app.services.email_sender import send_email_confirmation


class AccountError(Exception):
    """Base exception for account service errors."""

    pass


class TokenNotFoundError(AccountError):
    """Raised when email change confirmation token not found."""

    pass


class TokenExpiredError(AccountError):
    """Raised when email change confirmation token has expired."""

    pass


class TokenUsedError(AccountError):
    """Raised when email change confirmation token has already been used."""

    pass


class EmailTakenError(AccountError):
    """Raised when target email is already in use by another user."""

    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invalidate_pending_email_changes(db: Session, user_id: int) -> None:
    """Mark all pending, unused email changes for a user as used (invalidated).

    Called on password change to revoke any in-flight email change confirmations.
    """
    db.query(PendingEmailChange).filter(
        PendingEmailChange.user_id == user_id,
        PendingEmailChange.used.is_(False),
    ).update({"used": True})


def update_preferences(db: Session, user: User, *, frictionless_join_default: bool) -> User:
    """Update self-service DJ preferences."""
    user.frictionless_join_default = frictionless_join_default
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    """Change a user's password after verifying the current password.

    - Verifies current password is correct
    - Updates password hash
    - Bumps token_version to invalidate all existing JWT tokens
    - Invalidates any pending email change confirmations

    Args:
        db: Database session
        user: User model instance
        current_password: User's current password (plaintext)
        new_password: New password (plaintext)

    Raises:
        ValueError: If current password is incorrect
    """
    if not verify_password(current_password, user.password_hash):
        raise ValueError("incorrect_password")

    user.password_hash = get_password_hash(new_password)
    invalidate_pending_email_changes(db, user.id)
    user.token_version += 1
    db.commit()


def request_email_change(db: Session, user: User, current_password: str, new_email: str) -> None:
    """Request to change the user's email address.

    Verifies password, validates email is not taken, generates confirmation token,
    sends confirmation email with link to `confirm_email_change`.

    Args:
        db: Database session
        user: User model instance
        current_password: User's current password (plaintext)
        new_email: Desired new email address

    Raises:
        ValueError: If current password is incorrect or email is already taken
    """
    if not verify_password(current_password, user.password_hash):
        raise ValueError("incorrect_or_taken")
    existing = db.query(User).filter(User.email == new_email, User.id != user.id).first()
    if existing:
        raise ValueError("incorrect_or_taken")
    invalidate_pending_email_changes(db, user.id)
    token = secrets.token_hex(32)
    record = PendingEmailChange(
        user_id=user.id,
        new_email=new_email,
        token=_hash_token(token),
        expires_at=utcnow() + timedelta(hours=24),
    )
    db.add(record)
    db.commit()
    settings = get_settings()
    confirmation_url = f"{settings.public_url}/account/confirm-email?token={token}"
    send_email_confirmation(new_email, confirmation_url)


def get_active_pending_email_change(db: Session, user_id: int) -> PendingEmailChange | None:
    """Get the active (unused, not expired) pending email change for a user.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        PendingEmailChange if one exists and is valid, None otherwise
    """
    return (
        db.query(PendingEmailChange)
        .filter(
            PendingEmailChange.user_id == user_id,
            PendingEmailChange.used.is_(False),
            PendingEmailChange.expires_at > utcnow(),
        )
        .first()
    )


def confirm_email_change(db: Session, token: str) -> User:
    """Confirm an email change using a confirmation token.

    Validates token exists, is not expired, not already used, then updates the
    user's email and marks the token as used.

    Args:
        db: Database session
        token: Email change confirmation token

    Returns:
        Updated User model

    Raises:
        TokenNotFoundError: If token does not exist
        TokenExpiredError: If token has expired
        TokenUsedError: If token has already been used
        EmailTakenError: If target email is already in use
    """
    token_hash = _hash_token(token)
    record = db.query(PendingEmailChange).filter(PendingEmailChange.token == token_hash).first()
    if record is None:
        raise TokenNotFoundError("Token not found")
    if record.used:
        raise TokenUsedError("Token already used")
    if record.expires_at <= utcnow():
        raise TokenExpiredError("Token expired")
    existing = (
        db.query(User).filter(User.email == record.new_email, User.id != record.user_id).first()
    )
    if existing:
        raise EmailTakenError("Email already in use")
    user = db.query(User).filter(User.id == record.user_id).first()
    if user is None:
        raise TokenNotFoundError("Associated user no longer exists")
    user.email = record.new_email
    record.used = True
    db.commit()
    return user

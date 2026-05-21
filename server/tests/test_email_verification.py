"""Unit tests for email verification service."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest
from app.services.email_verification import (
    CodeExpiredError,
    CodeInvalidError,
    RateLimitExceededError,
    confirm_verification_code,
    create_verification_code,
)


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()


def test_create_verification_code(db: Session, test_guest: Guest):
    """6-digit code generated, stored with correct expiry."""
    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")

    assert len(code_row.code) == 6
    assert code_row.code.isdigit()
    assert int(code_row.code) >= 100000
    assert code_row.email_hash == _email_hash("fan@test.com")
    assert code_row.expires_at > utcnow()
    assert code_row.used is False
    assert code_row.attempts == 0


def test_verify_correct_code(db: Session, test_guest: Guest):
    """Accepted, marked used, email set on Guest."""
    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")

    result = confirm_verification_code(
        db, guest_id=test_guest.id, email="fan@test.com", code=code_row.code
    )
    assert result.verified is True
    assert result.merged is False

    db.refresh(test_guest)
    assert test_guest.email_hash == _email_hash("fan@test.com")
    assert test_guest.email_verified_at is not None


def test_verify_wrong_code_increments_attempts(db: Session, test_guest: Guest):
    """Wrong code -> attempts +1."""
    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")

    with pytest.raises(CodeInvalidError):
        confirm_verification_code(db, guest_id=test_guest.id, email="fan@test.com", code="000000")

    db.refresh(code_row)
    assert code_row.attempts == 1


def test_verify_three_strikes_invalidates(db: Session, test_guest: Guest):
    """MAX_ATTEMPTS wrong attempts -> code no longer accepted (now 5 per OTP best practice)."""
    from app.services.email_verification import MAX_ATTEMPTS

    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")
    real_code = code_row.code

    for _ in range(MAX_ATTEMPTS):
        with pytest.raises(CodeInvalidError):
            confirm_verification_code(
                db, guest_id=test_guest.id, email="fan@test.com", code="000000"
            )

    with pytest.raises(CodeInvalidError):
        confirm_verification_code(db, guest_id=test_guest.id, email="fan@test.com", code=real_code)


def test_verify_expired_code_rejected(db: Session, test_guest: Guest):
    """Code past 15 min -> rejected."""
    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")

    code_row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()

    with pytest.raises(CodeExpiredError):
        confirm_verification_code(
            db, guest_id=test_guest.id, email="fan@test.com", code=code_row.code
        )


def test_rate_limit_five_codes_per_hour(db: Session, test_guest: Guest):
    """6th code request for same email -> RateLimitExceededError."""
    with patch("app.services.email_verification.send_verification_email"):
        for _ in range(5):
            create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")

        with pytest.raises(RateLimitExceededError):
            create_verification_code(db, guest_id=test_guest.id, email="fan@test.com")


def test_verify_sets_email_on_guest(db: Session, test_guest: Guest):
    """Guest.verified_email and email_verified_at populated."""
    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="test@example.com")

    confirm_verification_code(
        db, guest_id=test_guest.id, email="test@example.com", code=code_row.code
    )

    db.refresh(test_guest)
    assert test_guest.verified_email == "test@example.com"
    assert test_guest.email_hash == _email_hash("test@example.com")


def test_already_verified_same_email(db: Session, test_guest: Guest):
    """Re-verifying same email on same device -> no-op success."""
    test_guest.verified_email = "already@test.com"
    test_guest.email_hash = _email_hash("already@test.com")
    test_guest.email_verified_at = utcnow()
    db.commit()

    with patch("app.services.email_verification.send_verification_email"):
        code_row = create_verification_code(db, guest_id=test_guest.id, email="already@test.com")

    result = confirm_verification_code(
        db, guest_id=test_guest.id, email="already@test.com", code=code_row.code
    )
    assert result.verified is True
    assert result.merged is False

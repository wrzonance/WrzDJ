"""Tests for self-service credential management (password + email change)."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.pending_email_change import PendingEmailChange
from app.models.user import User
from app.services.account import (  # noqa: F401
    EmailTakenError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenUsedError,
    change_password,
    confirm_email_change,
    get_active_pending_email_change,
    invalidate_pending_email_changes,
    request_email_change,
)
from app.services.auth import verify_password

# ── change_password ────────────────────────────────────────────────────────────


def test_change_password_success(db: Session, test_user: User) -> None:
    change_password(db, test_user, "testpassword123", "newpassword456")
    db.refresh(test_user)
    assert verify_password("newpassword456", test_user.password_hash)


def test_change_password_wrong_current(db: Session, test_user: User) -> None:
    original_hash = test_user.password_hash
    with pytest.raises(ValueError, match="incorrect_password"):
        change_password(db, test_user, "wrongpassword", "newpassword456")
    db.refresh(test_user)
    assert test_user.password_hash == original_hash


def test_change_password_bumps_token_version(db: Session, test_user: User) -> None:
    original_tv = test_user.token_version
    change_password(db, test_user, "testpassword123", "newpassword456")
    db.refresh(test_user)
    assert test_user.token_version == original_tv + 1


def test_change_password_invalidates_pending_email(db: Session, test_user: User) -> None:
    pending = PendingEmailChange(
        user_id=test_user.id,
        new_email="new@example.com",
        token="a" * 64,
        expires_at=utcnow() + timedelta(hours=24),
        used=False,
    )
    db.add(pending)
    db.commit()

    change_password(db, test_user, "testpassword123", "newpassword456")

    db.refresh(pending)
    assert pending.used is True


# ── request_email_change ───────────────────────────────────────────────────────


def test_request_email_change_success(db: Session, test_user: User) -> None:
    from unittest.mock import patch

    with patch("app.services.account.send_email_confirmation"):
        request_email_change(db, test_user, "testpassword123", "newemail@example.com")

    record = (
        db.query(PendingEmailChange)
        .filter(
            PendingEmailChange.user_id == test_user.id,
            PendingEmailChange.used.is_(False),
        )
        .first()
    )
    assert record is not None
    assert record.new_email == "newemail@example.com"
    assert len(record.token) == 64


def test_request_email_change_wrong_password(db: Session, test_user: User) -> None:
    from unittest.mock import patch

    with pytest.raises(ValueError, match="incorrect_or_taken"):
        with patch("app.services.account.send_email_confirmation"):
            request_email_change(db, test_user, "wrongpassword", "newemail@example.com")
    assert db.query(PendingEmailChange).count() == 0


def test_request_email_change_email_taken(db: Session, test_user: User, admin_user: User) -> None:
    from unittest.mock import patch

    with pytest.raises(ValueError, match="incorrect_or_taken"):
        with patch("app.services.account.send_email_confirmation"):
            request_email_change(db, test_user, "testpassword123", admin_user.email)


def test_request_email_change_supersedes_previous(db: Session, test_user: User) -> None:
    from unittest.mock import patch

    first_record = PendingEmailChange(
        user_id=test_user.id,
        new_email="first@example.com",
        token="b" * 64,
        expires_at=utcnow() + timedelta(hours=24),
        used=False,
    )
    db.add(first_record)
    db.commit()

    with patch("app.services.account.send_email_confirmation"):
        request_email_change(db, test_user, "testpassword123", "second@example.com")

    db.refresh(first_record)
    assert first_record.used is True
    active = (
        db.query(PendingEmailChange)
        .filter(
            PendingEmailChange.user_id == test_user.id,
            PendingEmailChange.used.is_(False),
        )
        .all()
    )
    assert len(active) == 1
    assert active[0].new_email == "second@example.com"


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_pending(
    db: Session,
    user: User,
    email: str,
    token: str,
    *,
    hours: int = 24,
    used: bool = False,
) -> PendingEmailChange:
    record = PendingEmailChange(
        user_id=user.id,
        new_email=email,
        token=token,
        expires_at=utcnow() + timedelta(hours=hours),
        used=used,
    )
    db.add(record)
    db.commit()
    return record


# ── confirm_email_change ───────────────────────────────────────────────────────


def test_confirm_email_change_success(db: Session, test_user: User) -> None:
    _make_pending(db, test_user, "confirmed@example.com", "c" * 64)
    returned_user = confirm_email_change(db, "c" * 64)
    db.refresh(test_user)
    assert test_user.email == "confirmed@example.com"
    assert returned_user.id == test_user.id


def test_confirm_marks_record_used(db: Session, test_user: User) -> None:
    record = _make_pending(db, test_user, "confirmed@example.com", "d" * 64)
    confirm_email_change(db, "d" * 64)
    db.refresh(record)
    assert record.used is True


def test_confirm_email_change_expired(db: Session, test_user: User) -> None:
    _make_pending(db, test_user, "expired@example.com", "e" * 64, hours=-1)
    with pytest.raises(TokenExpiredError):
        confirm_email_change(db, "e" * 64)


def test_confirm_email_change_used(db: Session, test_user: User) -> None:
    _make_pending(db, test_user, "used@example.com", "f" * 64, used=True)
    with pytest.raises(TokenUsedError):
        confirm_email_change(db, "f" * 64)


def test_confirm_email_change_not_found(db: Session) -> None:
    with pytest.raises(TokenNotFoundError):
        confirm_email_change(db, "0" * 64)


def test_confirm_email_change_email_race(db: Session, test_user: User) -> None:
    from app.services.auth import get_password_hash

    other_user = User(
        username="otheruser",
        email="other@example.com",
        password_hash=get_password_hash("otherpassword123"),
        role="dj",
    )
    db.add(other_user)
    db.commit()

    _make_pending(db, test_user, other_user.email, "g" * 64)
    with pytest.raises(EmailTakenError):
        confirm_email_change(db, "g" * 64)


# ── get_active_pending_email_change ────────────────────────────────────────────


def test_get_active_pending_returns_active(db: Session, test_user: User) -> None:
    _make_pending(db, test_user, "active@example.com", "h" * 64)
    result = get_active_pending_email_change(db, test_user.id)
    assert result is not None
    assert result.new_email == "active@example.com"


def test_get_active_pending_ignores_expired(db: Session, test_user: User) -> None:
    _make_pending(db, test_user, "expired@example.com", "i" * 64, hours=-1)
    result = get_active_pending_email_change(db, test_user.id)
    assert result is None


def test_get_active_pending_ignores_used(db: Session, test_user: User) -> None:
    _make_pending(db, test_user, "used@example.com", "j" * 64, used=True)
    result = get_active_pending_email_change(db, test_user.id)
    assert result is None


# ── send_email_confirmation ────────────────────────────────────────────────────


def test_send_email_confirmation_raises_when_not_configured() -> None:
    from unittest.mock import patch

    from app.services.email_sender import EmailNotConfiguredError, send_email_confirmation

    with patch("app.services.email_sender.get_settings") as mock_settings:
        mock_settings.return_value.resend_api_key = ""
        mock_settings.return_value.email_from_address = "noreply@wrzdj.com"
        with pytest.raises(EmailNotConfiguredError):
            send_email_confirmation(
                "test@example.com",
                "https://example.com/account/confirm-email?token=abc",
            )


def test_send_email_confirmation_calls_resend() -> None:
    from unittest.mock import patch

    from app.services.email_sender import send_email_confirmation

    with (
        patch("app.services.email_sender.get_settings") as mock_settings,
        patch("app.services.email_sender.resend.Emails.send") as mock_send,
    ):
        mock_settings.return_value.resend_api_key = "re_test_key"
        mock_settings.return_value.email_from_address = "noreply@wrzdj.com"
        send_email_confirmation(
            "user@example.com",
            "https://app.wrzdj.com/account/confirm-email?token=abc123",
        )
        mock_send.assert_called_once()
        payload = mock_send.call_args[0][0]
        assert payload["to"] == ["user@example.com"]
        assert "confirm-email" in payload["text"]

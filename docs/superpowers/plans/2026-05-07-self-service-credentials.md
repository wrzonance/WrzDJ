# Self-Service Credential Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow authenticated DJs and admins to change their password and email address from a new `/account` page, with full session invalidation on password change and email ownership verification via a 24h confirmation link.

**Architecture:** New `pending_email_changes` DB table stores email confirmation tokens; `services/account.py` encapsulates all credential-change logic; three new endpoints in `api/auth.py`; `/account` Next.js page with two independent forms; `/account/confirm-email` landing page verifies the token from the confirmation link. Pending users are blocked from all credential-change endpoints via `get_current_active_user`.

**Tech Stack:** Python/FastAPI/SQLAlchemy 2.0 (backend), bcrypt (password hashing), Resend API (email delivery), Next.js 16/React 19/TypeScript (frontend), vitest + @testing-library/react (frontend tests), pytest (backend tests).

---

## File Map

### New Files
| File | Purpose |
|---|---|
| `server/app/models/pending_email_change.py` | SQLAlchemy model for `pending_email_changes` table |
| `server/alembic/versions/042_add_pending_email_changes.py` | DB migration |
| `server/app/services/account.py` | `change_password`, `request_email_change`, `confirm_email_change`, helpers |
| `server/tests/test_account.py` | All backend tests for credential changes |
| `dashboard/app/account/page.tsx` | `/account` page — Change Password + Change Email cards |
| `dashboard/app/account/confirm-email/page.tsx` | Email confirmation landing |
| `dashboard/app/account/__tests__/page.test.tsx` | Frontend tests for /account |
| `dashboard/app/account/confirm-email/__tests__/page.test.tsx` | Frontend tests for confirm-email |

### Modified Files
| File | Change |
|---|---|
| `server/app/models/__init__.py` | Register `PendingEmailChange` |
| `server/app/schemas/user.py` | Add `ChangePasswordRequest`, `RequestEmailChangeRequest`; add `pending_email` field to `UserOut` |
| `server/app/services/email_sender.py` | Add `send_email_confirmation()` |
| `server/app/api/auth.py` | Add 3 endpoints; update `/me` to include `pending_email` |
| `dashboard/lib/api.ts` | Update `getMe` return type; add `changePassword`, `requestEmailChange`, `confirmEmailChange` |
| `dashboard/app/events/page.tsx` | Add "Account" nav link in header button row |

---

## Task 1: Data Model + Migration

**Files:**
- Create: `server/app/models/pending_email_change.py`
- Modify: `server/app/models/__init__.py`
- Create: `server/alembic/versions/042_add_pending_email_changes.py`

- [ ] **Step 1: Create the model**

Create `server/app/models/pending_email_change.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class PendingEmailChange(Base):
    __tablename__ = "pending_email_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
```

- [ ] **Step 2: Register in `__init__.py`**

In `server/app/models/__init__.py`, add the import after the existing imports:

```python
from app.models.pending_email_change import PendingEmailChange
```

And add `"PendingEmailChange"` to the `__all__` list.

- [ ] **Step 3: Create migration**

Create `server/alembic/versions/042_add_pending_email_changes.py`:

```python
"""Add pending_email_changes table for self-service email verification.

Revision ID: 042
Revises: 8addb2680814
Create Date: 2026-05-07
"""

import sqlalchemy as sa

from alembic import op

revision: str = "042"
down_revision: str | None = "8addb2680814"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "pending_email_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("new_email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "used", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(
        "ix_pending_email_changes_user_id", "pending_email_changes", ["user_id"]
    )
    op.create_index(
        "ix_pending_email_changes_token", "pending_email_changes", ["token"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_email_changes_token", table_name="pending_email_changes")
    op.drop_index("ix_pending_email_changes_user_id", table_name="pending_email_changes")
    op.drop_table("pending_email_changes")
```

- [ ] **Step 4: Run migration and check for drift**

```bash
cd server && source .venv/bin/activate && alembic upgrade head && alembic check
```

Expected: clean exit, no output from `alembic check`.

- [ ] **Step 5: Commit**

```bash
git add server/app/models/pending_email_change.py \
        server/app/models/__init__.py \
        server/alembic/versions/042_add_pending_email_changes.py
git commit -m "feat(account): add pending_email_changes model and migration"
```

---

## Task 2: Service — change_password (TDD)

**Files:**
- Create: `server/app/services/account.py` (partial — only `change_password` + `invalidate_pending_email_changes`)
- Create: `server/tests/test_account.py` (partial)

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_account.py`:

```python
"""Tests for self-service credential management (password + email change)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.pending_email_change import PendingEmailChange
from app.models.user import User
from app.services.account import (
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
from app.services.auth import get_password_hash, verify_password


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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "change_password" -v 2>&1 | head -30
```

Expected: `ImportError` — `app.services.account` does not exist yet.

- [ ] **Step 3: Create `server/app/services/account.py`**

Create the full module with implementations for Task 2 functions and **stubs** for Task 3/4 functions. The test file imports all names upfront — the stubs prevent `ImportError` while Tasks 3-4 add real implementations.

```python
"""Self-service credential management: password change, email change."""

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
    pass


class TokenNotFoundError(AccountError):
    pass


class TokenExpiredError(AccountError):
    pass


class TokenUsedError(AccountError):
    pass


class EmailTakenError(AccountError):
    pass


def invalidate_pending_email_changes(db: Session, user_id: int) -> None:
    db.query(PendingEmailChange).filter(
        PendingEmailChange.user_id == user_id,
        PendingEmailChange.used.is_(False),
    ).update({"used": True})


def change_password(
    db: Session, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValueError("incorrect_password")
    user.password_hash = get_password_hash(new_password)
    invalidate_pending_email_changes(db, user.id)
    user.token_version += 1
    db.commit()


# Stubs — implemented in Tasks 3 and 4
def request_email_change(
    db: Session, user: User, current_password: str, new_email: str
) -> None:
    raise NotImplementedError


def get_active_pending_email_change(
    db: Session, user_id: int
) -> "PendingEmailChange | None":
    raise NotImplementedError


def confirm_email_change(db: Session, token: str) -> User:
    raise NotImplementedError
```

- [ ] **Step 4: Run change_password tests**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "change_password" -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/account.py server/tests/test_account.py
git commit -m "feat(account): change_password service with token_version bump and pending invalidation"
```

---

## Task 3: Service — request_email_change (TDD)

**Files:**
- Modify: `server/app/services/account.py`
- Modify: `server/tests/test_account.py`

- [ ] **Step 1: Add failing tests**

Append to `server/tests/test_account.py`:

```python
# ── request_email_change ───────────────────────────────────────────────────────


def test_request_email_change_success(db: Session, test_user: User) -> None:
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
    with pytest.raises(ValueError, match="incorrect_or_taken"):
        with patch("app.services.account.send_email_confirmation"):
            request_email_change(db, test_user, "wrongpassword", "newemail@example.com")
    assert db.query(PendingEmailChange).count() == 0


def test_request_email_change_email_taken(
    db: Session, test_user: User, admin_user: User
) -> None:
    with pytest.raises(ValueError, match="incorrect_or_taken"):
        with patch("app.services.account.send_email_confirmation"):
            request_email_change(db, test_user, "testpassword123", admin_user.email)


def test_request_email_change_supersedes_previous(db: Session, test_user: User) -> None:
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "request_email_change" -v 2>&1 | head -20
```

Expected: `ImportError` — `request_email_change` not yet defined.

- [ ] **Step 3: Replace `request_email_change` stub in `account.py`**

Replace the `request_email_change` stub in `server/app/services/account.py` with the real implementation:

```python
def request_email_change(
    db: Session, user: User, current_password: str, new_email: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise ValueError("incorrect_or_taken")
    existing = (
        db.query(User)
        .filter(User.email == new_email, User.id != user.id)
        .first()
    )
    if existing:
        raise ValueError("incorrect_or_taken")
    invalidate_pending_email_changes(db, user.id)
    token = secrets.token_hex(32)
    record = PendingEmailChange(
        user_id=user.id,
        new_email=new_email,
        token=token,
        expires_at=utcnow() + timedelta(hours=24),
    )
    db.add(record)
    db.commit()
    settings = get_settings()
    confirmation_url = (
        f"{settings.public_url}/account/confirm-email?token={token}"
    )
    send_email_confirmation(new_email, confirmation_url)
```

- [ ] **Step 4: Run request_email_change tests**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "request_email_change" -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/account.py server/tests/test_account.py
git commit -m "feat(account): request_email_change service with pending token and email dispatch"
```

---

## Task 4: Service — confirm_email_change + get_active_pending (TDD)

**Files:**
- Modify: `server/app/services/account.py`
- Modify: `server/tests/test_account.py`

- [ ] **Step 1: Add failing tests**

Append to `server/tests/test_account.py`:

```python
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


def test_confirm_email_change_email_race(
    db: Session, test_user: User, admin_user: User
) -> None:
    _make_pending(db, test_user, admin_user.email, "g" * 64)
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "confirm_email_change or get_active_pending" -v 2>&1 | head -20
```

Expected: `ImportError` — functions not yet defined.

- [ ] **Step 3: Replace stubs in `account.py`**

Replace the `get_active_pending_email_change` and `confirm_email_change` stubs in `server/app/services/account.py` with real implementations:

```python
def get_active_pending_email_change(
    db: Session, user_id: int
) -> PendingEmailChange | None:
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
    record = (
        db.query(PendingEmailChange)
        .filter(PendingEmailChange.token == token)
        .first()
    )
    if record is None:
        raise TokenNotFoundError("Token not found")
    if record.used:
        raise TokenUsedError("Token already used")
    if record.expires_at <= utcnow():
        raise TokenExpiredError("Token expired")
    existing = (
        db.query(User)
        .filter(User.email == record.new_email, User.id != record.user_id)
        .first()
    )
    if existing:
        raise EmailTakenError("Email already in use")
    user = db.query(User).filter(User.id == record.user_id).first()
    user.email = record.new_email
    record.used = True
    db.commit()
    return user
```

- [ ] **Step 4: Run all confirm + pending tests**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "confirm_email_change or get_active_pending" -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/account.py server/tests/test_account.py
git commit -m "feat(account): confirm_email_change and get_active_pending_email_change"
```

---

## Task 5: Email Sender Extension (TDD)

**Files:**
- Modify: `server/app/services/email_sender.py`
- Modify: `server/tests/test_account.py`

- [ ] **Step 1: Add failing tests**

Append to `server/tests/test_account.py`:

```python
# ── send_email_confirmation ────────────────────────────────────────────────────


def test_send_email_confirmation_raises_when_not_configured() -> None:
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "send_email_confirmation" -v 2>&1 | head -20
```

Expected: `ImportError` — `send_email_confirmation` not in `email_sender.py`.

- [ ] **Step 3: Add `send_email_confirmation` to `email_sender.py`**

Append to `server/app/services/email_sender.py`:

```python
def send_email_confirmation(to_address: str, confirmation_url: str) -> None:
    """Send an email address confirmation link via Resend."""
    settings = get_settings()

    if not settings.resend_api_key or not settings.email_from_address:
        raise EmailNotConfiguredError("Resend API key or from address is not configured")

    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send(
            {
                "from": settings.email_from_address,
                "to": [to_address],
                "subject": "Confirm your new WrzDJ email address",
                "text": (
                    "Click the link below to confirm your new email address:\n\n"
                    f"{confirmation_url}\n\n"
                    "This link expires in 24 hours.\n\n"
                    "If you didn't request this change, you can safely ignore this email.\n"
                ),
            }
        )
    except Exception as exc:
        _logger.error(
            "email.confirmation_send_failed to_hash=%s error=%s",
            to_address[:3] + "***",
            exc,
        )
        raise EmailSendError(str(exc)) from exc

    _logger.info("email.confirmation_sent to_hash=%s", to_address[:3] + "***")
```

- [ ] **Step 4: Run email sender tests**

```bash
cd server && .venv/bin/pytest tests/test_account.py -k "send_email_confirmation" -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/services/email_sender.py server/tests/test_account.py
git commit -m "feat(account): add send_email_confirmation to email_sender"
```

---

## Task 6: Backend Schemas + API Endpoints

**Files:**
- Modify: `server/app/schemas/user.py`
- Modify: `server/app/api/auth.py`
- Modify: `server/tests/test_account.py`

- [ ] **Step 1: Update `UserOut` in `user.py`**

In `server/app/schemas/user.py`, add `pending_email: str | None = None` to `UserOut`, immediately after `help_pages_seen`:

```python
class UserOut(BaseSchema):
    id: int
    username: str
    is_active: bool
    role: str
    created_at: datetime
    help_pages_seen: list[str] = []
    pending_email: str | None = None

    @field_validator("help_pages_seen", mode="before")
    @classmethod
    def parse_help_pages(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return json.loads(v)
        return v
```

- [ ] **Step 2: Add new request schemas to `user.py`**

Append to `server/app/schemas/user.py` (after the `RegisterRequest` class):

```python
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_new_password: str

    @field_validator("confirm_new_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class RequestEmailChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_email: EmailStr
```

- [ ] **Step 3: Update imports in `auth.py`**

In `server/app/api/auth.py`, make these changes to the import block:

Replace:
```python
from app.api.deps import get_current_user, get_db
```
With:
```python
from app.api.deps import get_current_active_user, get_current_user, get_db
```

Replace:
```python
from app.schemas.user import HelpPageSeenRequest, PublicSettings, RegisterRequest, UserOut
```
With:
```python
from app.schemas.user import (
    ChangePasswordRequest,
    HelpPageSeenRequest,
    PublicSettings,
    RegisterRequest,
    RequestEmailChangeRequest,
    UserOut,
)
```

Add these new imports after the existing service imports:
```python
from app.services import account as account_service
from app.services.account import (
    EmailTakenError,
    TokenExpiredError,
    TokenNotFoundError,
    TokenUsedError,
)
from app.services.email_sender import EmailNotConfiguredError, EmailSendError
```

- [ ] **Step 4: Update the `/me` endpoint**

In `server/app/api/auth.py`, replace the existing `/me` endpoint:

```python
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
```

- [ ] **Step 5: Add three new endpoints**

Add after the updated `/me` endpoint in `server/app/api/auth.py`:

```python
@router.patch("/me/password", response_model=StatusMessageResponse)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    try:
        account_service.change_password(
            db, current_user, body.current_password, body.new_password
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return StatusMessageResponse(status="ok", message="Password updated. Please log in again.")


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
        raise HTTPException(
            status_code=422, detail="Email service temporarily unavailable"
        )
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
        raise HTTPException(
            status_code=400, detail="Confirmation link has already been used"
        )
    except EmailTakenError:
        raise HTTPException(status_code=409, detail="Email address is already in use")
    return StatusMessageResponse(status="ok", message="Email updated")
```

- [ ] **Step 6: Add API-level tests**

Append to `server/tests/test_account.py`:

```python
# ── API endpoints ──────────────────────────────────────────────────────────────


def test_api_change_password_success(
    client, auth_headers: dict, db: Session, test_user: User
) -> None:
    resp = client.patch(
        "/api/auth/me/password",
        json={
            "current_password": "testpassword123",
            "new_password": "newpassword456",
            "confirm_new_password": "newpassword456",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    db.refresh(test_user)
    assert verify_password("newpassword456", test_user.password_hash)


def test_api_change_password_wrong_current(client, auth_headers: dict) -> None:
    resp = client.patch(
        "/api/auth/me/password",
        json={
            "current_password": "wrongpassword",
            "new_password": "newpassword456",
            "confirm_new_password": "newpassword456",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_api_pending_role_blocked_password(client, pending_headers: dict) -> None:
    resp = client.patch(
        "/api/auth/me/password",
        json={
            "current_password": "pendingpassword123",
            "new_password": "newpassword456",
            "confirm_new_password": "newpassword456",
        },
        headers=pending_headers,
    )
    assert resp.status_code == 403


def test_api_request_email_change_success(
    client, auth_headers: dict, db: Session, test_user: User
) -> None:
    with patch("app.services.account.send_email_confirmation"):
        resp = client.post(
            "/api/auth/me/email/request",
            json={
                "current_password": "testpassword123",
                "new_email": "newemail@example.com",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert (
        db.query(PendingEmailChange)
        .filter(PendingEmailChange.user_id == test_user.id)
        .count()
        == 1
    )


def test_api_confirm_email_change_success(
    client, db: Session, test_user: User
) -> None:
    token = "k" * 64
    db.add(
        PendingEmailChange(
            user_id=test_user.id,
            new_email="confirmed@example.com",
            token=token,
            expires_at=utcnow() + timedelta(hours=24),
        )
    )
    db.commit()
    resp = client.get(f"/api/auth/email/confirm?token={token}")
    assert resp.status_code == 200
    db.refresh(test_user)
    assert test_user.email == "confirmed@example.com"


def test_api_me_includes_pending_email(
    client, auth_headers: dict, db: Session, test_user: User
) -> None:
    db.add(
        PendingEmailChange(
            user_id=test_user.id,
            new_email="pending@example.com",
            token="l" * 64,
            expires_at=utcnow() + timedelta(hours=24),
        )
    )
    db.commit()
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["pending_email"] == "pending@example.com"
```

- [ ] **Step 7: Run all account tests**

```bash
cd server && .venv/bin/pytest tests/test_account.py -v
```

Expected: all tests PASS.

- [ ] **Step 8: Run full backend CI**

```bash
cd server && \
  .venv/bin/ruff check . && \
  .venv/bin/ruff format --check . && \
  .venv/bin/bandit -r app -c pyproject.toml -q && \
  .venv/bin/pytest --tb=short -q
```

Expected: all pass, coverage ≥ 85%.

- [ ] **Step 9: Commit**

```bash
git add server/app/schemas/user.py server/app/api/auth.py server/tests/test_account.py
git commit -m "feat(account): add password and email change API endpoints"
```

---

## Task 7: Frontend API Client

**Files:**
- Modify: `dashboard/lib/api.ts`

- [ ] **Step 1: Update `getMe` return type**

In `dashboard/lib/api.ts`, replace:

```typescript
async getMe(): Promise<{ id: number; username: string; role: string; help_pages_seen: string[] }> {
  return this.fetch('/api/auth/me');
}
```

With:

```typescript
async getMe(): Promise<{
  id: number;
  username: string;
  role: string;
  help_pages_seen: string[];
  pending_email: string | null;
}> {
  return this.fetch('/api/auth/me');
}
```

- [ ] **Step 2: Add three new methods**

Add immediately after `markHelpPageSeen`:

```typescript
async changePassword(data: {
  current_password: string;
  new_password: string;
  confirm_new_password: string;
}): Promise<{ status: string; message: string }> {
  return this.fetch('/api/auth/me/password', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

async requestEmailChange(data: {
  current_password: string;
  new_email: string;
}): Promise<{ status: string; message: string }> {
  return this.fetch('/api/auth/me/email/request', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

async confirmEmailChange(token: string): Promise<{ status: string; message: string }> {
  return this.publicFetch(
    `${getApiUrl()}/api/auth/email/confirm?token=${encodeURIComponent(token)}`
  );
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat(account): add changePassword, requestEmailChange, confirmEmailChange to API client"
```

---

## Task 8: /account Page + Nav Link + Tests

**Files:**
- Create: `dashboard/app/account/page.tsx`
- Modify: `dashboard/app/events/page.tsx`
- Create: `dashboard/app/account/__tests__/page.test.tsx`

- [ ] **Step 1: Create `dashboard/app/account/page.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';

export default function AccountPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);

  const [emailCurrentPassword, setEmailCurrentPassword] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [emailPending, setEmailPending] = useState<string | null>(null);
  const [emailLoading, setEmailLoading] = useState(false);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      api.getMe().then(user => setEmailPending(user.pending_email));
    }
  }, [isAuthenticated]);

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError('');
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }
    setPasswordLoading(true);
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      });
      setPasswordSuccess(true);
      setTimeout(() => router.push('/login'), 1500);
    } catch (err: unknown) {
      setPasswordError(err instanceof Error ? err.message : 'Password change failed');
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleEmailRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    setEmailError('');
    setEmailLoading(true);
    try {
      await api.requestEmailChange({
        current_password: emailCurrentPassword,
        new_email: newEmail,
      });
      setEmailPending(newEmail);
      setEmailCurrentPassword('');
      setNewEmail('');
    } catch (err: unknown) {
      setEmailError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setEmailLoading(false);
    }
  };

  if (isLoading) return null;

  return (
    <main style={{ maxWidth: '480px', margin: '0 auto', padding: '2rem 1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <Link href="/events" style={{ color: '#888', textDecoration: 'none', fontSize: '0.875rem' }}>
          ← Events
        </Link>
        <h1 style={{ margin: 0, fontSize: '1.5rem' }}>Account Settings</h1>
      </div>

      <div style={{ background: '#1a1a1a', borderRadius: '0.75rem', padding: '1.5rem', marginBottom: '1.5rem' }}>
        <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Change Password</h2>
        {passwordSuccess ? (
          <p style={{ color: '#4ade80', margin: 0 }}>Password updated. Redirecting to login…</p>
        ) : (
          <form onSubmit={handlePasswordChange}>
            <label htmlFor="current-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: '#aaa' }}>
              Current Password
            </label>
            <input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
              required
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            <label htmlFor="new-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: '#aaa' }}>
              New Password
            </label>
            <input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              required
              minLength={8}
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            <label htmlFor="confirm-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: '#aaa' }}>
              Confirm New Password
            </label>
            <input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              required
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            {passwordError && (
              <p style={{ color: '#f87171', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                {passwordError}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={passwordLoading}>
              {passwordLoading ? 'Updating…' : 'Update Password'}
            </button>
          </form>
        )}
      </div>

      <div style={{ background: '#1a1a1a', borderRadius: '0.75rem', padding: '1.5rem' }}>
        <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Change Email</h2>
        {emailPending ? (
          <div>
            <p style={{ color: '#aaa', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Confirmation sent to:
            </p>
            <p style={{ color: '#ededed', fontWeight: 500, marginBottom: '1rem' }}>{emailPending}</p>
            <p style={{ color: '#888', fontSize: '0.8rem', margin: 0 }}>
              Check your inbox and click the confirmation link. The link expires in 24 hours.
            </p>
          </div>
        ) : (
          <form onSubmit={handleEmailRequest}>
            <label htmlFor="email-current-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: '#aaa' }}>
              Current Password
            </label>
            <input
              id="email-current-password"
              type="password"
              value={emailCurrentPassword}
              onChange={e => setEmailCurrentPassword(e.target.value)}
              required
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            <label htmlFor="new-email" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: '#aaa' }}>
              New Email Address
            </label>
            <input
              id="new-email"
              type="email"
              value={newEmail}
              onChange={e => setNewEmail(e.target.value)}
              required
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            {emailError && (
              <p style={{ color: '#f87171', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                {emailError}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={emailLoading}>
              {emailLoading ? 'Sending…' : 'Send Confirmation'}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Add Account link to events page header**

In `dashboard/app/events/page.tsx`, find the header button row. Locate the existing "Bridge App" `<a>` element and the Logout `<button>`. Add the Account link between them:

```tsx
<Link href="/account">
  <button className="btn" style={{ background: '#333' }}>Account</button>
</Link>
```

- [ ] **Step 3: Create `dashboard/app/account/__tests__/page.test.tsx`**

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AccountPage from '../page';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false }),
}));

const mockChangePassword = vi.fn();
const mockRequestEmailChange = vi.fn();
const mockGetMe = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    getMe: () => mockGetMe(),
    changePassword: (...args: unknown[]) => mockChangePassword(...args),
    requestEmailChange: (...args: unknown[]) => mockRequestEmailChange(...args),
  },
}));

describe('AccountPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMe.mockResolvedValue({
      id: 1,
      username: 'testuser',
      role: 'dj',
      help_pages_seen: [],
      pending_email: null,
    });
  });

  it('renders Change Password and Change Email headings', async () => {
    render(<AccountPage />);
    await waitFor(() => {
      expect(screen.getByText('Change Password')).toBeInTheDocument();
      expect(screen.getByText('Change Email')).toBeInTheDocument();
    });
  });

  it('submits password change with correct payload', async () => {
    mockChangePassword.mockResolvedValue({ status: 'ok', message: 'Updated' });
    render(<AccountPage />);

    await waitFor(() => screen.getByLabelText('Current Password'));

    fireEvent.change(screen.getByLabelText('Current Password'), {
      target: { value: 'oldpass' },
    });
    fireEvent.change(screen.getByLabelText('New Password'), {
      target: { value: 'newpass123' },
    });
    fireEvent.change(screen.getByLabelText('Confirm New Password'), {
      target: { value: 'newpass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith({
        current_password: 'oldpass',
        new_password: 'newpass123',
        confirm_new_password: 'newpass123',
      });
    });
  });

  it('redirects to /login after successful password change', async () => {
    mockChangePassword.mockResolvedValue({ status: 'ok', message: 'Updated' });
    vi.useFakeTimers();
    render(<AccountPage />);

    await waitFor(() => screen.getByLabelText('Current Password'));
    fireEvent.change(screen.getByLabelText('Current Password'), { target: { value: 'oldpass' } });
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpass123' } });
    fireEvent.change(screen.getByLabelText('Confirm New Password'), {
      target: { value: 'newpass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    await waitFor(() => screen.getByText(/Redirecting to login/));
    vi.advanceTimersByTime(1600);
    expect(mockPush).toHaveBeenCalledWith('/login');
    vi.useRealTimers();
  });

  it('shows error when passwords do not match', async () => {
    render(<AccountPage />);
    await waitFor(() => screen.getByLabelText('New Password'));

    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpass123' } });
    fireEvent.change(screen.getByLabelText('Confirm New Password'), {
      target: { value: 'different' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(screen.getByText('New passwords do not match')).toBeInTheDocument();
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it('shows check-inbox state after successful email request', async () => {
    mockRequestEmailChange.mockResolvedValue({ status: 'ok', message: 'Sent' });
    render(<AccountPage />);

    await waitFor(() => screen.getByLabelText('New Email Address'));
    fireEvent.change(screen.getByLabelText('New Email Address'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Confirmation' }));

    await waitFor(() => {
      expect(screen.getByText('new@example.com')).toBeInTheDocument();
      expect(screen.getByText(/Check your inbox/)).toBeInTheDocument();
    });
  });

  it('shows pending email from getMe on load', async () => {
    mockGetMe.mockResolvedValue({
      id: 1,
      username: 'testuser',
      role: 'dj',
      help_pages_seen: [],
      pending_email: 'pending@example.com',
    });
    render(<AccountPage />);
    await waitFor(() => {
      expect(screen.getByText('pending@example.com')).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 4: Run frontend tests**

```bash
cd dashboard && npm test -- --run app/account/__tests__/page.test.tsx 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 5: TypeScript check**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/account/page.tsx \
        dashboard/app/account/__tests__/page.test.tsx \
        dashboard/app/events/page.tsx
git commit -m "feat(account): add /account page with password and email change forms"
```

---

## Task 9: Email Confirmation Landing Page

**Files:**
- Create: `dashboard/app/account/confirm-email/page.tsx`
- Create: `dashboard/app/account/confirm-email/__tests__/page.test.tsx`

Note: `useSearchParams` requires a `<Suspense>` boundary in Next.js 14+. The component is split into `ConfirmEmailContent` (uses the hook) and a `ConfirmEmailPage` wrapper (provides the boundary).

- [ ] **Step 1: Create `dashboard/app/account/confirm-email/page.tsx`**

```tsx
'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { api } from '@/lib/api';

function ConfirmEmailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');
    if (!token) {
      setStatus('error');
      setErrorMessage('No confirmation token provided.');
      return;
    }
    api
      .confirmEmailChange(token)
      .then(() => {
        setStatus('success');
        setTimeout(() => router.push('/account'), 2000);
      })
      .catch((err: unknown) => {
        setStatus('error');
        setErrorMessage(err instanceof Error ? err.message : 'Confirmation failed.');
      });
  }, [searchParams, router]);

  return (
    <main style={{ maxWidth: '480px', margin: '4rem auto', padding: '2rem 1rem', textAlign: 'center' }}>
      {status === 'loading' && (
        <p style={{ color: '#aaa' }}>Verifying your email address…</p>
      )}
      {status === 'success' && (
        <>
          <p style={{ color: '#4ade80', fontSize: '1.1rem', marginBottom: '0.5rem' }}>
            Email address updated!
          </p>
          <p style={{ color: '#888', fontSize: '0.875rem' }}>
            Redirecting to account settings…
          </p>
        </>
      )}
      {status === 'error' && (
        <>
          <p style={{ color: '#f87171', fontSize: '1.1rem', marginBottom: '0.5rem' }}>
            Confirmation failed
          </p>
          <p style={{ color: '#888', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
            {errorMessage}
          </p>
          <Link href="/account" style={{ color: '#818cf8' }}>
            Return to account settings
          </Link>
        </>
      )}
    </main>
  );
}

export default function ConfirmEmailPage() {
  return (
    <Suspense
      fallback={
        <main style={{ padding: '4rem', textAlign: 'center' }}>
          <p style={{ color: '#aaa' }}>Loading…</p>
        </main>
      }
    >
      <ConfirmEmailContent />
    </Suspense>
  );
}
```

- [ ] **Step 2: Create `dashboard/app/account/confirm-email/__tests__/page.test.tsx`**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ConfirmEmailPage from '../page';

const mockPush = vi.fn();
let mockToken: string | null = 'validtoken123';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({ get: (key: string) => (key === 'token' ? mockToken : null) }),
}));

const mockConfirmEmailChange = vi.fn();
vi.mock('@/lib/api', () => ({
  api: { confirmEmailChange: (...args: unknown[]) => mockConfirmEmailChange(...args) },
}));

describe('ConfirmEmailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockToken = 'validtoken123';
  });

  it('shows success state on valid token', async () => {
    mockConfirmEmailChange.mockResolvedValue({ status: 'ok', message: 'Email updated' });
    vi.useFakeTimers();
    render(<ConfirmEmailPage />);

    await waitFor(() => {
      expect(screen.getByText('Email address updated!')).toBeInTheDocument();
    });
    vi.advanceTimersByTime(2100);
    expect(mockPush).toHaveBeenCalledWith('/account');
    vi.useRealTimers();
  });

  it('shows error state on expired token', async () => {
    mockConfirmEmailChange.mockRejectedValue(new Error('Confirmation link has expired'));
    render(<ConfirmEmailPage />);

    await waitFor(() => {
      expect(screen.getByText('Confirmation failed')).toBeInTheDocument();
      expect(screen.getByText('Confirmation link has expired')).toBeInTheDocument();
    });
  });

  it('shows error state when token missing from URL', async () => {
    mockToken = null;
    render(<ConfirmEmailPage />);

    await waitFor(() => {
      expect(screen.getByText('No confirmation token provided.')).toBeInTheDocument();
    });
  });

  it('shows link back to account settings on error', async () => {
    mockConfirmEmailChange.mockRejectedValue(new Error('Invalid confirmation link'));
    render(<ConfirmEmailPage />);

    await waitFor(() => {
      expect(screen.getByText('Return to account settings')).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd dashboard && npm test -- --run app/account/ 2>&1 | tail -20
```

Expected: all tests across both test files PASS.

- [ ] **Step 4: TypeScript check**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/account/confirm-email/page.tsx \
        dashboard/app/account/confirm-email/__tests__/page.test.tsx
git commit -m "feat(account): add email confirmation landing page"
```

---

## Task 10: Full CI Verification

- [ ] **Step 1: Backend CI**

```bash
cd server && \
  .venv/bin/ruff check . && \
  .venv/bin/ruff format --check . && \
  .venv/bin/bandit -r app -c pyproject.toml -q && \
  .venv/bin/pytest --tb=short -q
```

Expected: all pass, coverage ≥ 85%.

- [ ] **Step 2: Frontend CI**

```bash
cd dashboard && npm run lint && npx tsc --noEmit && npm test -- --run
```

Expected: no lint errors, no type errors, all tests pass.

- [ ] **Step 3: Bridge + Bridge App CI**

```bash
cd bridge && npx tsc --noEmit && npm test -- --run
cd bridge-app && npx tsc --noEmit && npm test -- --run
```

Expected: no errors (these components are unchanged).

- [ ] **Step 4: Alembic check**

```bash
cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check
```

Expected: clean exit.

- [ ] **Step 5: Fix any failures and commit**

Common issues to watch for:
- `ruff I001` (import sort): run `.venv/bin/ruff check --fix .`
- `ruff F401` (unused import): remove the import
- TypeScript error on `pending_email` access: verify `getMe()` return type was updated in Task 7
- Test failure on `getByLabelText`: confirm `htmlFor`/`id` pairs match exactly in the JSX

After fixing, run the affected CI step again before committing:
```bash
git add -p  # stage only the fix
git commit -m "fix(account): <describe the fix>"
```

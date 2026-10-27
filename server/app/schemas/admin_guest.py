"""Pydantic schemas for the admin Guests page (#862).

Spec: docs/superpowers/specs/2026-10-21-admin-guest-management-design.md
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import BaseSchema, IsoDatetime, OptionalIsoDatetime

GuestFilter = Literal["all", "verified", "unverified", "shared"]
GUEST_FILTERS: tuple[GuestFilter, ...] = ("all", "verified", "unverified", "shared")


class AdminGuestEventOut(BaseSchema):
    """One event membership (a guest_profiles row) as the admin sees it."""

    event_id: int
    code: str
    name: str
    nickname: str | None = None
    submission_count: int = 0
    joined_at: IsoDatetime


class AdminGuestOut(BaseSchema):
    id: int
    # Newest non-null per-event nickname; guests.nickname is never written (see spec).
    nickname: str | None = None
    browser: str | None = None
    email_verified: bool = False
    email_masked: str | None = None
    email_verified_at: OptionalIsoDatetime = None
    human_verified_at: OptionalIsoDatetime = None
    human_verify_count: int = 0
    fingerprint_short: str | None = None
    # Other guests sharing the same fingerprint hash; 0 means unique (or no hash).
    fingerprint_shared_with: int = 0
    created_at: IsoDatetime
    last_seen_at: IsoDatetime
    event_count: int = 0
    request_count: int = 0
    events: list[AdminGuestEventOut] = Field(default_factory=list)


class AdminGuestUpdate(BaseModel):
    revoke_email: bool = False


class AdminGuestProfileUpdate(BaseModel):
    nickname: str | None = Field(None, max_length=30)

    @field_validator("nickname", mode="before")
    @classmethod
    def _strip_nickname(cls, value: object) -> object:
        """Trim before the length check; blank means clear (None)."""
        if isinstance(value, str):
            return value.strip() or None
        return value

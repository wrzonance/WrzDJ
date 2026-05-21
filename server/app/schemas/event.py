from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import BaseSchema, IsoDatetime, OptionalIsoDatetime


class EventStatus(str, Enum):
    """Status of an event based on expiry and archive state."""

    ACTIVE = "active"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class BulkDeleteEventsRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("codes", mode="before")
    @classmethod
    def strip_and_uppercase(cls, v: list[str]) -> list[str]:
        return [c.strip().upper() for c in v]


class EventCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    expires_hours: int = Field(default=6, ge=1, le=48)


class EventUpdate(BaseModel):
    expires_at: datetime | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)


class DisplaySettingsUpdate(BaseModel):
    """Request body for updating display settings."""

    now_playing_hidden: bool | None = None
    now_playing_auto_hide_minutes: int | None = Field(default=None, ge=1, le=1440)
    requests_open: bool | None = None
    kiosk_display_only: bool | None = None


class DisplaySettingsResponse(BaseModel):
    """Response for display settings update."""

    status: str = "ok"
    now_playing_hidden: bool
    now_playing_auto_hide_minutes: int = 10
    requests_open: bool = True
    kiosk_display_only: bool = False


class EventOut(BaseSchema):
    id: int
    code: str
    join_code: str
    name: str
    created_at: IsoDatetime
    expires_at: IsoDatetime
    is_active: bool
    archived_at: OptionalIsoDatetime = None
    status: EventStatus | None = None
    join_url: str | None = None
    collect_url: str | None = None
    request_count: int | None = None
    # Tidal sync settings
    tidal_sync_enabled: bool = False
    tidal_playlist_id: str | None = None
    # Beatport sync settings
    beatport_sync_enabled: bool = False
    beatport_playlist_id: str | None = None
    # Banner
    banner_url: str | None = None
    banner_kiosk_url: str | None = None
    banner_colors: list[str] | None = None
    # Requests open/closed
    requests_open: bool = True
    # Pre-event collection
    collection_opens_at: OptionalIsoDatetime = None
    live_starts_at: OptionalIsoDatetime = None
    submission_cap_per_guest: int = 15
    collection_phase_override: str | None = None

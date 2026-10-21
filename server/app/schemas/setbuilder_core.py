from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SetCreate(BaseModel):
    """Body for creating a new (empty) set."""

    name: str = Field(..., min_length=1, max_length=120)
    event_id: int | None = None


class SetRename(BaseModel):
    """Body for renaming a set."""

    name: str = Field(..., min_length=1, max_length=120)


class SetTargetUpdate(BaseModel):
    """Body for updating set-length planning settings."""

    target_duration_sec: int | None = Field(None, ge=60, le=24 * 3600)
    avg_transition_overlap_sec: int = Field(..., ge=0, le=32)


class CollaboratorInviteCreate(BaseModel):
    role: Literal["editor", "viewer"]


class CollaboratorInviteCreated(BaseModel):
    token: str
    role: Literal["editor", "viewer"]
    expires_at: datetime


class CollaboratorInviteOut(BaseModel):
    id: int
    role: Literal["editor", "viewer"]
    created_at: datetime
    expires_at: datetime
    accepted: bool
    revoked: bool


class CollaboratorAccepted(BaseModel):
    set_id: int
    role: Literal["editor", "viewer"]


class SetSummary(BaseModel):
    """Set list item (no children)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    event_id: int | None
    status: Literal["draft", "locked", "exported"]
    sharing_mode: Literal["private", "invite_only"]
    # Owner-only surfaces; non-null means a public read-only link exists.
    share_token: str | None = None
    created_at: datetime
    updated_at: datetime


class SetDetail(SetSummary):
    """Full set record (Phase 0: no slot/curve expansion yet)."""

    vibe_theme: str | None
    target_duration_sec: int | None
    avg_transition_overlap_sec: int
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    tidal_playlist_id: str | None
    spotify_playlist_id: str | None = None
    apple_music_playlist_id: str | None = None
    apple_music_export_uncertain: bool = False
    apple_music_export_recovery_playlist_id: str | None = None
    exported_at: datetime | None


class TasteProfileMoodOut(BaseModel):
    """One mood preference learned from explicit vibe edits."""

    mood: str
    count: int


class TasteProfileOut(BaseModel):
    """Current DJ's read-time SetBuilder taste profile."""

    sample_count: int
    min_samples: int
    active: bool
    average_energy_delta: float | None
    energy_adjustment: float
    top_moods: list[TasteProfileMoodOut]
    summary: str
    reset_at: datetime | None


# ---------------------------------------------------------------------------
# Pool (issue #388)

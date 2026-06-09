"""Pydantic schemas for WrzDJSet set-CRUD endpoints (Phase 0)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.recommendation import PlaylistInfo


class SetCreate(BaseModel):
    """Body for creating a new (empty) set."""

    name: str = Field(..., min_length=1, max_length=120)
    event_id: int | None = None


class SetRename(BaseModel):
    """Body for renaming a set."""

    name: str = Field(..., min_length=1, max_length=120)


class SetSummary(BaseModel):
    """Set list item (no children)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    event_id: int | None
    status: Literal["draft", "locked", "exported"]
    sharing_mode: Literal["private", "invite_only"]
    created_at: datetime
    updated_at: datetime


class SetDetail(SetSummary):
    """Full set record (Phase 0: no slot/curve expansion yet)."""

    vibe_theme: str | None
    target_duration_sec: int | None
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    tidal_playlist_id: str | None
    exported_at: datetime | None


# ---------------------------------------------------------------------------
# Pool (issue #388)


class PoolSourceOut(BaseModel):
    """An import source row for the sources accordion."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: Literal["event", "tidal", "beatport", "public_url", "manual"]
    external_ref: str | None
    label: str
    meta: str | None
    created_at: datetime


class PoolTrackOut(BaseModel):
    """A pool track row (badges: camelot, bpm, energy; chip: source_id)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    track_id: str | None
    title: str
    artist: str
    album: str | None
    genre: str | None
    bpm: float | None
    key: str | None
    camelot: str | None
    energy: int | None
    isrc: str | None
    duration_sec: int | None
    artwork_url: str | None
    created_at: datetime


class PoolState(BaseModel):
    """Full pool snapshot: sources + tracks."""

    sources: list[PoolSourceOut]
    tracks: list[PoolTrackOut]


class PoolImportResult(BaseModel):
    """Result of any import flow — toast reads 'added new · deduped de-duped'."""

    added: int
    deduped: int
    source: PoolSourceOut
    pool: PoolState


class PoolMutationResult(BaseModel):
    """Result of a removal flow."""

    removed: int
    pool: PoolState


class PoolImportEventIn(BaseModel):
    """Body for importing a WrzDJ event's requests."""

    event_id: int = Field(..., ge=1)


class PoolImportPlaylistIn(BaseModel):
    """Body for importing a connected-account (Tidal/Beatport) playlist."""

    playlist_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    label: str | None = Field(None, max_length=200)


class PoolImportUrlIn(BaseModel):
    """Body for public playlist URL preview/import."""

    url: str = Field(..., min_length=12, max_length=500)


class PoolUrlPreview(BaseModel):
    """Validate → preview card payload for a public playlist URL."""

    provider: str
    supported: bool
    name: str | None = None
    owner: str | None = None
    track_count: int | None = None
    message: str | None = None


class PoolImportManualIn(BaseModel):
    """Body for adding a single track picked from manual search."""

    title: str = Field(..., min_length=1, max_length=255)
    artist: str = Field(..., min_length=1, max_length=255)
    album: str | None = Field(None, max_length=255)
    genre: str | None = Field(None, max_length=100)
    bpm: float | None = Field(None, ge=0, le=400)
    key: str | None = Field(None, max_length=20)
    isrc: str | None = Field(None, max_length=15)
    duration_sec: int | None = Field(None, ge=0, le=36000)
    artwork_url: str | None = Field(None, max_length=500, pattern=r"^https://")
    source_service: Literal["spotify", "beatport", "tidal", "manual"] = "manual"
    source_track_id: str | None = Field(None, max_length=100)


class PoolRemoveTracksIn(BaseModel):
    """Body for per-track / multi-select removal."""

    track_ids: list[int] = Field(..., min_length=1, max_length=500)


class BuilderPlaylistsOut(BaseModel):
    """Connected-service playlist pickers for the import modal."""

    tidal_connected: bool
    beatport_connected: bool
    tidal: list[PlaylistInfo]
    beatport: list[PlaylistInfo]

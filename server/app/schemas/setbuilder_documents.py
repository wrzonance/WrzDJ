from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.setbuilder_pool import PoolEnrichmentStatus


class SetDocumentSettings(BaseModel):
    """Mutable target-setting fields included in history/autosave snapshots."""

    vibe_theme: str | None = Field(None, max_length=50)
    target_duration_sec: int | None = Field(None, ge=0, le=36000)
    bpm_floor: int | None = Field(None, ge=0, le=400)
    bpm_ceiling: int | None = Field(None, ge=0, le=400)
    key_strictness: float = Field(0.2, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _bpm_ordered(self) -> "SetDocumentSettings":
        if (
            self.bpm_floor is not None
            and self.bpm_ceiling is not None
            and self.bpm_ceiling < self.bpm_floor
        ):
            raise ValueError("bpm_ceiling must be greater than or equal to bpm_floor")
        return self


class SetDocumentSlot(BaseModel):
    """Slot row as stored in a document snapshot."""

    id: int = Field(..., ge=1)
    position: int = Field(..., ge=0)
    track_id: str | None = Field(None, max_length=255)
    locked: bool = False
    notes: str | None = None
    transition_score: float | None = None
    transition_warnings: str | None = None
    target_energy: float | None = Field(None, ge=0.0, le=10.0)


class SetDocumentCurvePoint(BaseModel):
    """Curve/vibe-window row as stored in a document snapshot."""

    id: int = Field(..., ge=1)
    position_sec: int = Field(..., ge=0)
    energy: int = Field(..., ge=0, le=10)
    label: str | None = Field(None, max_length=50)
    is_slow_window_start: bool = False
    is_slow_window_end: bool = False


class SetDocumentPoolSource(BaseModel):
    """Pool source row as stored in a document snapshot."""

    id: int = Field(..., ge=1)
    kind: Literal["event", "tidal", "beatport", "public_url", "manual"]
    external_ref: str | None = Field(None, max_length=500)
    label: str = Field(..., min_length=1, max_length=200)
    meta: str | None = Field(None, max_length=200)
    created_at: datetime


class SetDocumentPoolTrack(BaseModel):
    """Pool track row as stored in a document snapshot."""

    id: int = Field(..., ge=1)
    source_id: int = Field(..., ge=1)
    track_id: str | None = Field(None, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    artist: str = Field(..., min_length=1, max_length=255)
    album: str | None = Field(None, max_length=255)
    genre: str | None = Field(None, max_length=100)
    bpm: float | None = Field(None, ge=0, le=400)
    key: str | None = Field(None, max_length=20)
    camelot: str | None = Field(None, max_length=3)
    energy: int | None = Field(None, ge=0, le=10)
    isrc: str | None = Field(None, max_length=15)
    duration_sec: int | None = Field(None, ge=0, le=36000)
    artwork_url: str | None = Field(None, max_length=500)
    dedupe_sig: str = Field(..., min_length=1, max_length=64)
    enrichment_status: PoolEnrichmentStatus = "pending"
    created_at: datetime


class SetDocumentPool(BaseModel):
    """Pool state in a restorable document snapshot."""

    sources: list[SetDocumentPoolSource] = Field(default_factory=list, max_length=500)
    tracks: list[SetDocumentPoolTrack] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _tracks_reference_sources(self) -> "SetDocumentPool":
        source_ids = {source.id for source in self.sources}
        missing = [track.source_id for track in self.tracks if track.source_id not in source_ids]
        if missing:
            raise ValueError("pool tracks must reference sources in this snapshot")
        return self


class SetDocumentSnapshot(BaseModel):
    """Full builder document snapshot for undo/redo and autosave."""

    settings: SetDocumentSettings
    slots: list[SetDocumentSlot] = Field(..., max_length=500)
    curve_points: list[SetDocumentCurvePoint] = Field(..., max_length=1000)
    pool: SetDocumentPool


# ---------------------------------------------------------------------------
# Share links (issue #398)


class ShareTokenOut(BaseModel):
    """Owner response after creating/rotating a share token (issue #398)."""

    share_token: str


class SharedSlotView(BaseModel):
    """View-only slot projection for public share links (no DB ids)."""

    model_config = ConfigDict(from_attributes=True)

    position: int
    track_id: str | None
    locked: bool
    notes: str | None
    transition_score: float | None


class SharedCurvePointView(BaseModel):
    """View-only curve-point projection for public share links."""

    model_config = ConfigDict(from_attributes=True)

    position_sec: int
    energy: int
    label: str | None
    is_slow_window_start: bool
    is_slow_window_end: bool


class SharedSetView(BaseModel):
    """Public read-only projection of a shared set (issue #398).

    Never include owner identity, internal ids, event linkage,
    collaborator info, or the token itself.
    """

    name: str
    status: Literal["draft", "locked", "exported"]
    vibe_theme: str | None
    target_duration_sec: int | None
    avg_transition_overlap_sec: int
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    slots: list[SharedSlotView]
    curve_points: list[SharedCurvePointView]


# ---------------------------------------------------------------------------
# Track vibes (issue #391) — read-only three-tier display + enrichment trigger

"""Pydantic schemas for WrzDJSet set-CRUD endpoints (Phase 0)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # Owner-only surfaces; non-null means a public read-only link exists.
    share_token: str | None = None
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


# ---------------------------------------------------------------------------
# Energy curve editor (#389)
# ---------------------------------------------------------------------------


class CurvePointModel(BaseModel):
    """One normalized template point: position t in [0,1], energy e in [0,10]."""

    t: float = Field(..., ge=0.0, le=1.0)
    e: float = Field(..., ge=0.0, le=10.0)
    label: str | None = Field(None, max_length=50)
    slow_start: bool = False
    slow_end: bool = False


def _validate_curve_points(points: list[CurvePointModel]) -> list[CurvePointModel]:
    """Shared shape rules: 2-32 points, endpoints at t=0/t=1, non-decreasing t."""
    if not (2 <= len(points) <= 32):
        raise ValueError("curve needs between 2 and 32 points")
    if points[0].t != 0.0:
        raise ValueError("first point must be at t=0")
    if points[-1].t != 1.0:
        raise ValueError("last point must be at t=1")
    ts = [p.t for p in points]
    if any(b < a for a, b in zip(ts, ts[1:])):
        raise ValueError("points must be ordered by non-decreasing t")
    return points


class CurveTemplateCreate(BaseModel):
    """Body for creating (or fully updating) a user curve template."""

    name: str = Field(..., min_length=1, max_length=80)
    points: list[CurvePointModel]

    _check_points = field_validator("points")(_validate_curve_points)


class BuiltinTemplateOut(BaseModel):
    """A built-in (code-defined) template."""

    name: str
    points: list[CurvePointModel]


class CurveTemplateOut(BaseModel):
    """A persisted per-DJ template."""

    id: int
    name: str
    points: list[CurvePointModel]
    updated_at: datetime


class CurveTemplatesResponse(BaseModel):
    """All templates available to the DJ."""

    builtin: list[BuiltinTemplateOut]
    user: list[CurveTemplateOut]


class SlotOut(BaseModel):
    """Timeline slot (curve-editor surface; track metadata joins with #388)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    track_id: str | None
    locked: bool
    target_energy: float | None
    notes: str | None


class SlotTargetUpdate(BaseModel):
    """Body for setting/clearing a slot's energy target. None = reset."""

    target_energy: float | None = Field(None, ge=0.0, le=10.0)


class SlotTargetOut(BaseModel):
    """One slot's persisted target after an update/apply."""

    slot_id: int
    target_energy: float | None


class ApplyTemplateRequest(BaseModel):
    """Apply a template's shape onto the set's slots.

    Exactly one of ``builtin`` / ``template_id``. ``slot_midpoints`` are the
    normalized slot midpoints (client knows track durations); omitted means
    uniform buckets.
    """

    builtin: str | None = Field(None, max_length=80)
    template_id: int | None = None
    slot_midpoints: list[float] | None = None

    @field_validator("slot_midpoints")
    @classmethod
    def _check_midpoints(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return v
        if len(v) > 500:
            raise ValueError("too many slot_midpoints")
        if any(not (0.0 <= m <= 1.0) for m in v):
            raise ValueError("slot_midpoints must be within [0, 1]")
        if any(b < a for a, b in zip(v, v[1:])):
            raise ValueError("slot_midpoints must be non-decreasing")
        return v

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "ApplyTemplateRequest":
        if (self.builtin is None) == (self.template_id is None):
            raise ValueError("provide exactly one of builtin or template_id")
        return self


class ApplyTemplateResponse(BaseModel):
    """Per-slot targets persisted by an apply, plus suggested vibe windows."""

    targets: list[SlotTargetOut]
    windows: list["TemplateWindowOut"]


class TemplateWindowOut(BaseModel):
    """Suggested vibe window from a template's slow_start/slow_end flags."""

    t0: float
    t1: float


class VibeWindowModel(BaseModel):
    """A named region of the set timeline, in seconds."""

    t0_sec: int = Field(..., ge=0)
    t1_sec: int = Field(..., ge=0)
    label: str = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def _ordered(self) -> "VibeWindowModel":
        if self.t1_sec <= self.t0_sec:
            raise ValueError("t1_sec must be greater than t0_sec")
        return self


class VibeWindowsPut(BaseModel):
    """Replace-all body for a set's vibe windows."""

    windows: list[VibeWindowModel] = Field(..., max_length=30)


class VibeWindowsResponse(BaseModel):
    """A set's stored vibe windows."""

    windows: list[VibeWindowModel]


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
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    slots: list[SharedSlotView]
    curve_points: list[SharedCurvePointView]

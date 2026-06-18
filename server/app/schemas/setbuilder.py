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


class SetTargetUpdate(BaseModel):
    """Body for updating set-length planning settings."""

    target_duration_sec: int | None = Field(None, ge=60, le=24 * 3600)
    avg_transition_overlap_sec: int = Field(..., ge=0, le=32)


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


def _validate_pairing_tags(tags: list[str]) -> list[str]:
    """Shape-only tag guard; service handles normalization/de-dupe."""
    if len(tags) > 12:
        raise ValueError("too many tags")
    for tag in tags:
        if len(tag) > 50:
            raise ValueError("tags must be 50 characters or fewer")
        if not tag.strip():
            raise ValueError("tags cannot be empty or whitespace-only")
        if len(tag.strip()) > 32:
            raise ValueError("tags must be 32 characters or fewer")
    return tags


class PairingCreate(BaseModel):
    """Create/update a DJ-curated from->into pairing."""

    from_track_id: str = Field(..., min_length=1, max_length=255)
    into_track_id: str = Field(..., min_length=1, max_length=255)
    cue_in_sec: int | None = Field(None, ge=0, le=36000)
    note: str | None = Field(None, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    increment_use_count: bool = False

    _check_tags = field_validator("tags")(_validate_pairing_tags)


class PairingUpdate(BaseModel):
    """Editable pairing details."""

    cue_in_sec: int | None = Field(None, ge=0, le=36000)
    note: str | None = Field(None, max_length=2000)
    tags: list[str] | None = None

    @field_validator("tags")
    @classmethod
    def _check_tags_optional(cls, tags: list[str] | None) -> list[str] | None:
        if tags is not None:
            return _validate_pairing_tags(tags)
        return tags


class PairingOut(BaseModel):
    """Pairing card/detail payload for the overlay."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    set_id: int
    from_track_id: str
    into_track_id: str
    cue_in_sec: int | None
    note: str | None
    tags: list[str]
    use_count: int
    from_track: PoolTrackOut | None = None
    into_track: PoolTrackOut | None = None
    created_at: datetime
    updated_at: datetime


class PairingsState(BaseModel):
    """Pairings list response."""

    count: int
    pairings: list[PairingOut]


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
    transition_score: float | None = None
    transition_warnings: str | None = None
    pool_track_id: int | None = None
    title: str | None = None
    artist: str | None = None
    bpm: float | None = None
    key: str | None = None
    camelot: str | None = None
    energy: int | None = None
    duration_sec: int | None = None
    next_pairing_id: int | None = None
    next_is_dj_pairing: bool = False


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
# Two-pass set builder (#390)
# ---------------------------------------------------------------------------


class BuildSetRequest(BaseModel):
    """Run deterministic set generation. confirmed=true is an explicit user gate."""

    confirmed: bool = Field(
        ...,
        json_schema_extra={"const": True},
        description="Must be true to confirm unlocked slots may be reordered.",
    )


class TransitionScoreOut(BaseModel):
    """One recomputed transition score."""

    slot_id: int
    position: int
    score: float
    warnings: list[str]


class BuildSetResponse(BaseModel):
    """Result of the deterministic pass."""

    slot_count: int
    iterations: int
    slots: list[SlotOut]
    transition_scores: list[TransitionScoreOut]


class SlotOrderRequest(BaseModel):
    """Full desired slot order for a set (hand-drag reorder, #437)."""

    slot_ids: list[int] = Field(..., min_length=1, max_length=500)


AgentCritiqueFlagType = Literal[
    "energy_dip",
    "vibe_clash",
    "era_jump",
    "sing_along_missing",
    "banger_buried",
    "transition_brilliant",
]


class CritiqueFlagOut(BaseModel):
    """A structured critique flag from the agent pass."""

    type: AgentCritiqueFlagType
    slot_position: int | None = None
    message: str | None = None


class SetCritiqueOut(BaseModel):
    """Structured auto-critique output."""

    overall_grade: str
    summary: str
    flags: list[CritiqueFlagOut]


class AgentChatHistoryItem(BaseModel):
    """Prior chat turn supplied by the client for context."""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class AgentChatIn(BaseModel):
    """One chat turn for the setbuilder agent."""

    message: str = Field(..., min_length=1, max_length=4000)
    history: list[AgentChatHistoryItem] = Field(default_factory=list, max_length=30)


class AppliedToolCallOut(BaseModel):
    """One agent tool call, including rationale for mutating tools."""

    id: str
    name: str
    args: dict
    rationale: str | None
    result: dict
    mutating: bool
    display_summary: str = ""


class AgentChatMessageOut(BaseModel):
    """One persisted agent sidebar message."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    display_summary: str | None = None
    tool_calls: list[AppliedToolCallOut] = Field(default_factory=list)
    affected_transition_scores: list[TransitionScoreOut] = Field(default_factory=list)
    created_at: datetime


class AgentChatHistoryOut(BaseModel):
    """Persisted agent sidebar transcript and compact context metadata."""

    messages: list[AgentChatMessageOut]
    context_summary: str | None = None
    compacted_through_message_id: int | None = None
    uses_compact_context: bool = True
    recent_turn_limit: int


class AgentChatOut(BaseModel):
    """Agent chat turn result after applying tool calls."""

    message: str
    tool_calls: list[AppliedToolCallOut]
    slots: list[SlotOut]
    affected_transition_scores: list[TransitionScoreOut]
    assistant_message: AgentChatMessageOut


# ---------------------------------------------------------------------------
# Transport (issue #393) — setbuilder playback commands via Bridge
# ---------------------------------------------------------------------------


class TransportCommandIn(BaseModel):
    """One setbuilder transport command queued to the Bridge client."""

    action: Literal["load", "play", "pause", "seek"] = Field(
        ..., description="Transport action for the Bridge playback client"
    )
    source: Literal["tidal"] = "tidal"
    slot_index: int = Field(..., ge=0)
    track_id: str | None = Field(None, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    artist: str = Field("", max_length=255)
    position_sec: float = Field(0, ge=0)
    duration_sec: float = Field(..., gt=0, le=36000)


class TransportCommandOut(BaseModel):
    """Bridge command queued for a setbuilder transport action."""

    command_id: str
    command_type: Literal["setbuilder_transport"]
    action: Literal["load", "play", "pause", "seek"]
    active_source: Literal["tidal"]


class TransportStatusOut(BaseModel):
    """Set-scoped Bridge playback status for the transport bar."""

    connected: bool
    active_source: str | None = None
    device_name: str | None = None
    last_seen: datetime | None = None


# ---------------------------------------------------------------------------
# Document snapshots (issue #395)


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


class OwnVibeOut(BaseModel):
    """The DJ's own override tier."""

    energy: int | None
    mood: str | None


class CommunityVibeOut(BaseModel):
    """Community consensus tier (gated by SystemSettings thresholds)."""

    energy: int | None
    mood: str | None
    sample_size: int


class LlmVibeOut(BaseModel):
    """Globally-cached LLM guess tier."""

    energy: int | None
    mood: str | None
    era: str | None
    sing_along: bool | None
    dance_floor: bool | None
    transitional_role: str | None
    confidence: float | None
    low_confidence: bool
    llm_provider: str
    llm_model: str


class ResolvedVibeOut(BaseModel):
    """Per-field precedence result: own -> community -> llm."""

    energy: int | None
    energy_source: Literal["own", "community", "llm"] | None
    mood: str | None
    mood_source: Literal["own", "community", "llm"] | None


class TrackVibeStateOut(BaseModel):
    """All three tiers + resolution for one pool track."""

    pool_track_id: int
    vibe_key: str
    own: OwnVibeOut | None
    community: CommunityVibeOut | None
    llm: LlmVibeOut | None
    resolved: ResolvedVibeOut


class PoolVibesState(BaseModel):
    """Vibe state for every track in a set's pool."""

    tracks: list[TrackVibeStateOut]


class PoolVibeOverrideIn(BaseModel):
    """Explicit DJ edit for one pool track's vibe fields."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "anyOf": [
                        {
                            "properties": {
                                "energy": {
                                    "anyOf": [
                                        {"maximum": 10.0, "minimum": 0.0, "type": "integer"},
                                        {"type": "null"},
                                    ],
                                    "title": "Energy",
                                },
                                "mood": {
                                    "anyOf": [
                                        {"maxLength": 50, "type": "string"},
                                        {"type": "null"},
                                    ],
                                    "title": "Mood",
                                },
                            },
                            "required": ["energy"],
                            "type": "object",
                        },
                        {
                            "properties": {
                                "energy": {
                                    "anyOf": [
                                        {"maximum": 10.0, "minimum": 0.0, "type": "integer"},
                                        {"type": "null"},
                                    ],
                                    "title": "Energy",
                                },
                                "mood": {
                                    "anyOf": [
                                        {"maxLength": 50, "type": "string"},
                                        {"type": "null"},
                                    ],
                                    "title": "Mood",
                                },
                            },
                            "required": ["mood"],
                            "type": "object",
                        },
                    ]
                }
            ],
            "minProperties": 1,
        }
    )

    energy: int | None = Field(default=None, ge=0, le=10)
    mood: str | None = Field(default=None, max_length=50)

    @field_validator("mood")
    @classmethod
    def _normalize_mood(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def _requires_touched_field(self) -> "PoolVibeOverrideIn":
        if not {"energy", "mood"} & self.model_fields_set:
            raise ValueError("energy or mood is required")
        return self


class VibeEnrichmentResult(BaseModel):
    """Result of an enrichment run, plus the refreshed vibe state."""

    enriched: int
    cached: int
    failed: int
    llm_calls: int
    vibes: PoolVibesState


# ---------------------------------------------------------------------------
# Export (issue #396)


# Engine DJ and Lexicon have no proprietary import format — both ingest the
# Rekordbox DJ_PLAYLISTS XML — so they are distinct format keys that render the
# same XML (kept distinct, not aliased, so the UI lists them separately).
ExportTarget = Literal["tidal", "rekordbox", "m3u", "txt", "enginedj", "lexicon"]
ExportFileFormat = Literal["rekordbox", "m3u", "txt", "enginedj", "lexicon"]


class ExportPreflightIn(BaseModel):
    """Body for the pre-export resolution check."""

    target: ExportTarget


class UnresolvedTrackOut(BaseModel):
    """One track that can't be exported to the chosen target."""

    position: int
    title: str
    artist: str
    track_id: str | None
    reason: Literal["no_tidal_match", "missing_metadata"]


class ExportPreflightOut(BaseModel):
    """Resolution summary the DJ confirms before exporting."""

    target: ExportTarget
    source: Literal["timeline", "pool"]
    total: int
    resolved_count: int
    unresolved: list[UnresolvedTrackOut]
    # Only set for target="tidal"; None for file targets.
    tidal_connected: bool | None = None


class ExportTidalIn(BaseModel):
    """Body for the Tidal export. skip_unresolved is the DJ's explicit choice."""

    skip_unresolved: bool = False


class ExportTidalOut(BaseModel):
    """Successful Tidal export result."""

    playlist_id: str
    playlist_url: str
    added: int
    skipped: int
    exported_at: datetime
    status: Literal["draft", "locked", "exported"]


class ExportFileIn(BaseModel):
    """Body for the file (Rekordbox XML / M3U / txt) export."""

    format: ExportFileFormat
    skip_unresolved: bool = False


class UnresolvedTracksDetail(BaseModel):
    """Detail payload of the 409 unresolved-tracks interrupt."""

    code: Literal["unresolved_tracks"]
    unresolved: list[UnresolvedTrackOut]


class UnresolvedTracksError(BaseModel):
    """409 response body — export blocked until retried with skip_unresolved=true."""

    detail: UnresolvedTracksDetail


# ---------------------------------------------------------------------------
# Play-history feedback loop (issue #403) — derive-on-read planned-vs-actual.

SlotOutcome = Literal["played", "skipped", "out_of_order", "substituted"]


class PlaybackSlotOutcomeOut(BaseModel):
    """One planned slot's planned-vs-actual outcome."""

    slot_id: int
    position: int
    track_id: str | None
    title: str | None
    artist: str | None
    outcome: SlotOutcome
    play_order: int | None = None
    played_at: datetime | None = None
    deck: str | None = None


class UnplannedPlayOut(BaseModel):
    """A played track that matched no planned slot (a live substitution)."""

    play_order: int
    title: str
    artist: str
    played_at: datetime | None = None
    deck: str | None = None
    outcome: SlotOutcome = "substituted"


class PlaybackReportSummary(BaseModel):
    """Headline counts for the report header."""

    total_planned: int
    total_played: int
    played: int
    skipped: int
    out_of_order: int
    unplanned: int


class PlayHistoryFeedbackOut(BaseModel):
    """Derive-on-read planned-vs-actual report for a set's attached event."""

    event_id: int
    slots: list[PlaybackSlotOutcomeOut]
    unplanned: list[UnplannedPlayOut]
    summary: PlaybackReportSummary


class ApplyPairingFeedbackOut(BaseModel):
    """Result of the explicit consecutive-pairing bump action."""

    bumped: int
    pairings: PairingsState

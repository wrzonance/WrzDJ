from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.recommendation import PlaylistInfo

PoolEnrichmentStatus = Literal["pending", "enriched", "failed"]


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
    enrichment_status: PoolEnrichmentStatus
    created_at: datetime


class PoolEnrichmentSummary(BaseModel):
    """Set-level background enrichment progress for pool imports."""

    total: int
    enriched: int
    failed: int
    pending: int
    in_progress: bool


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
    """Full pool snapshot: sources + tracks + total candidate runtime."""

    sources: list[PoolSourceOut]
    tracks: list[PoolTrackOut]
    enrichment: PoolEnrichmentSummary
    # Total pool runtime in seconds (Σ duration_sec with the builder's avg
    # fallback), surfaced before generation so the build dialog can show pool
    # size vs. target and the resulting slot count (#538).
    runtime_sec: int = 0


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

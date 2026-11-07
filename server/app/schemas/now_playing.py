"""Schemas for StageLinQ now-playing and play history."""

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, IsoDatetime, OptionalIsoDatetime

# --- Bridge Inbound Payloads ---


class NowPlayingBridgePayload(BaseModel):
    """Payload from bridge when a new track starts playing."""

    event_code: str = Field(..., min_length=1, max_length=10)
    title: str = Field(..., min_length=1, max_length=255)
    artist: str = Field(..., min_length=1, max_length=255)
    album: str | None = Field(default=None, max_length=255)
    deck: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, max_length=20)
    # A track the Bridge buffered while the server was unreachable and is now sending again:
    # it goes to play history only (no now-playing change, no live update to screens).
    delayed: bool = False
    # How long ago the DJ played it, by the Bridge's clock (relative, so clock skew doesn't
    # matter). Places it in the history next to the song that was on screen.
    played_ago_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class BridgeStatusPayload(BaseModel):
    """Payload from bridge reporting connection status."""

    event_code: str = Field(..., min_length=1, max_length=10)
    connected: bool
    device_name: str | None = Field(default=None, max_length=100)
    # Optional enriched fields (backward compatible — bridge may omit all of these)
    circuit_breaker_state: str | None = Field(default=None, max_length=20)
    buffer_size: int | None = Field(default=None, ge=0)
    plugin_id: str | None = Field(default=None, max_length=50)
    deck_count: int | None = Field(default=None, ge=0)
    uptime_seconds: int | None = Field(default=None, ge=0)


# --- Public Outbound Responses ---


class NowPlayingResponse(BaseSchema):
    """Response for current now-playing track."""

    title: str
    artist: str
    album: str | None = None
    album_art_url: str | None = None
    spotify_uri: str | None = None
    started_at: IsoDatetime
    source: str
    matched_request_id: int | None = None
    bridge_connected: bool = False


class BridgeStatusResponse(BaseModel):
    """Public response for bridge connection status (independent of track data)."""

    connected: bool = False
    device_name: str | None = None
    last_seen: OptionalIsoDatetime = None
    # Enriched fields (populated from most recent SSE event, not persisted)
    circuit_breaker_state: str | None = None
    buffer_size: int | None = None
    plugin_id: str | None = None
    deck_count: int | None = None
    uptime_seconds: int | None = None


class PlayHistoryEntry(BaseSchema):
    """Single entry in play history."""

    id: int
    title: str
    artist: str
    album: str | None = None
    album_art_url: str | None = None
    spotify_uri: str | None = None
    matched_request_id: int | None = None
    source: str
    started_at: IsoDatetime
    ended_at: OptionalIsoDatetime = None
    play_order: int


class PlayHistoryResponse(BaseModel):
    """Paginated response for play history."""

    items: list[PlayHistoryEntry]
    total: int

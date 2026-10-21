from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.setbuilder_curves import SlotOut, TransitionScoreOut

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

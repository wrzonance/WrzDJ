from datetime import datetime

from pydantic import BaseModel

from app.schemas.setbuilder_history_types import SlotOutcome
from app.schemas.setbuilder_pool import PairingsState


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

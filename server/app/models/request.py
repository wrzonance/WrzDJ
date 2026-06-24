from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class RequestStatus(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    PLAYING = "playing"
    PLAYED = "played"
    REJECTED = "rejected"


class RequestSource(str, Enum):
    MANUAL = "manual"
    MUSICBRAINZ = "musicbrainz"
    SPOTIFY = "spotify"
    SHARE_LINK = "share_link"
    TIDAL = "tidal"
    BEATPORT = "beatport"


class TidalSyncStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    NOT_FOUND = "not_found"
    ERROR = "error"


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    song_title: Mapped[str] = mapped_column(String(255))
    artist: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(20), default=RequestSource.MANUAL.value)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RequestStatus.NEW.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # First moment this request entered ACCEPTED. Backs the DJ "date accepted"
    # sort (issue #478): a historical fact preserved through later status changes,
    # unlike updated_at which moves on every metadata refresh/play. NULL until the
    # request is first accepted.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    guest_id: Mapped[int | None] = mapped_column(
        ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)

    # Multi-service sync
    raw_search_query: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sync_results_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Track metadata (populated from search results when available)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # ISRC carried from the chosen search result (#552). Enrichment uses it as the
    # ISRC-first master-store cache key + identity, rather than re-deriving it.
    isrc: Mapped[str | None] = mapped_column(String(15), nullable=True)

    # Voting
    vote_count: Mapped[int] = mapped_column(Integer, default=0)

    # Tidal collection playlist tracking — set when a request is successfully synced
    tidal_collection_track_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )

    # Pre-event collection flag — set on insert when event.phase == "collection"
    submitted_during_collection: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0", index=True
    )

    event: Mapped["Event"] = relationship(
        "Event", back_populates="requests", foreign_keys=[event_id]
    )
    votes: Mapped[list["RequestVote"]] = relationship(
        "RequestVote", back_populates="request", cascade="all, delete-orphan"
    )

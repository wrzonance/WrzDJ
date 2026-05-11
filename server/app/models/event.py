from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


def _strip_tz(dt: datetime | None) -> datetime | None:
    """Return a naive UTC datetime so comparisons with utcnow() never raise.

    Project stores naive UTC. Defends against an in-memory aware datetime
    that hasn't yet been round-tripped through the DB (Pydantic parses
    ISO-with-Z as aware).
    """
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Tidal playlist sync
    tidal_playlist_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tidal_collection_playlist_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tidal_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tidal_collection_bidirectional: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

    # Beatport sync
    beatport_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    beatport_playlist_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Display settings
    now_playing_auto_hide_minutes: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False, server_default="10"
    )
    requests_open: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="1"
    )

    # Kiosk display-only mode (hide request button, enable auto-scroll)
    kiosk_display_only: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

    # Custom banner image
    banner_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    banner_colors: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pre-event collection
    collection_opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    live_starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submission_cap_per_guest: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False, server_default="15"
    )
    collection_phase_override: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_by: Mapped["User"] = relationship("User", back_populates="events")
    requests: Mapped[list["Request"]] = relationship(
        "Request", back_populates="event", foreign_keys="Request.event_id"
    )
    play_history: Mapped[list["PlayHistory"]] = relationship("PlayHistory", back_populates="event")

    @property
    def phase(self) -> Literal["pre_announce", "collection", "live", "closed"]:
        if self.collection_phase_override == "force_live":
            return "live"
        if self.collection_phase_override == "force_collection":
            return "collection"
        now = utcnow()
        opens = _strip_tz(self.collection_opens_at)
        live = _strip_tz(self.live_starts_at)
        expires = _strip_tz(self.expires_at)
        if opens and now < opens:
            return "pre_announce"
        if live and now < live:
            return "collection"
        if now < expires:
            return "live"
        return "closed"

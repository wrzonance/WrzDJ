"""WrzDJSet DJ-curated transition pairings (issue #392)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class SetPairing(Base):
    """A set-scoped "from track -> into track" transition the DJ trusts."""

    __tablename__ = "set_pairings"
    __table_args__ = (
        UniqueConstraint("set_id", "from_track_id", "into_track_id", name="uq_set_pairing_tracks"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    into_track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cue_in_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    set: Mapped["Set"] = relationship("Set", back_populates="pairings")

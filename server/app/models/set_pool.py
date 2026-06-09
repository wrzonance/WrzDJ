"""WrzDJSet pool models (issue #388).

The pool is a set's candidate-track surface. Every track is tagged with the
SetPoolSource it was imported through ("importedVia") so removal flows can
operate per-source. Both tables cascade-delete with their parent Set; tracks
also cascade with their source row (remove-by-source).

`track_id` is the namespaced free-form string convention shared with
TrackVibe (e.g. "tidal:12345", "beatport:678", "spotify:abc", "request:9") —
deliberately NOT an FK because no unified track table exists.

`dedupe_sig` is the normalized artist+title hash (see services/setbuilder/
pool.dedupe_signature) and is unique per set: dedupe-on-import is the
feature, and the constraint keeps it honest under concurrent imports.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class SetPoolSource(Base):
    __tablename__ = "set_pool_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "event" | "tidal" | "beatport" | "public_url" | "manual"
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # event id / playlist id / sanitized playlist URL; NULL for the manual bucket
    external_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    meta: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    set: Mapped["Set"] = relationship("Set", back_populates="pool_sources")
    tracks: Mapped[list["SetPoolTrack"]] = relationship(
        "SetPoolTrack",
        back_populates="source",
        cascade="all, delete-orphan",
    )


class SetPoolTrack(Base):
    __tablename__ = "set_pool_tracks"
    __table_args__ = (UniqueConstraint("set_id", "dedupe_sig", name="uq_set_pool_track_sig"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("set_pool_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    track_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    camelot: Mapped[str | None] = mapped_column(String(3), nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10 (#391 fills)
    isrc: Mapped[str | None] = mapped_column(String(15), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dedupe_sig: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    set: Mapped["Set"] = relationship("Set", back_populates="pool_tracks")
    source: Mapped["SetPoolSource"] = relationship("SetPoolSource", back_populates="tracks")

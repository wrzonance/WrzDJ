"""WrzDJSet core models (Phase 0 scaffold).

A Set is a standalone, owner-private DJ set with an optional event link.
SetSlot rows are the ordered timeline; SetCurvePoint rows are the energy
curve; SetCollaborator is modeled now (per exec-summary) but invite/enforce
flows ship in v3. Child rows cascade-delete with their parent Set.

Enum-like columns are String(N) (matching every other WrzDJ model);
allowed values are enforced at the API boundary via Pydantic Literals.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class Set(Base):
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vibe_theme: Mapped[str | None] = mapped_column(String(50), nullable=True)

    target_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm_ceiling: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0.0 ignore Camelot ... 1.0 strict +/-1
    key_strictness: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.2, server_default="0.2"
    )

    # "draft" | "locked" | "exported"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    # "private" | "invite_only"  (v3 enforced)
    sharing_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default="private"
    )

    tidal_playlist_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    slots: Mapped[list["SetSlot"]] = relationship(
        "SetSlot",
        back_populates="set",
        cascade="all, delete-orphan",
    )
    curve_points: Mapped[list["SetCurvePoint"]] = relationship(
        "SetCurvePoint",
        back_populates="set",
        cascade="all, delete-orphan",
    )
    collaborators: Mapped[list["SetCollaborator"]] = relationship(
        "SetCollaborator",
        back_populates="set",
        cascade="all, delete-orphan",
    )
    pool_sources: Mapped[list["SetPoolSource"]] = relationship(
        "SetPoolSource",
        back_populates="set",
        cascade="all, delete-orphan",
    )
    pool_tracks: Mapped[list["SetPoolTrack"]] = relationship(
        "SetPoolTrack",
        back_populates="set",
        cascade="all, delete-orphan",
    )


class SetSlot(Base):
    __tablename__ = "set_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    track_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    transition_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    set: Mapped["Set"] = relationship("Set", back_populates="slots")


class SetCurvePoint(Base):
    __tablename__ = "set_curve_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-10
    label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_slow_window_start: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    is_slow_window_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    set: Mapped["Set"] = relationship("Set", back_populates="curve_points")


class SetCollaborator(Base):
    """Modeled v1, enforced v3."""

    __tablename__ = "set_collaborators"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "editor" | "viewer"
    invited_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    set: Mapped["Set"] = relationship("Set", back_populates="collaborators")

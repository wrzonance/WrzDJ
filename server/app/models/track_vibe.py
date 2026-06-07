"""WrzDJSet vibe-signal models (Phase 0 scaffold).

TrackVibe is a GLOBAL LLM cache — one row per (track, provider, model,
prompt_version, schema_version). TrackVibeOverride is a per-DJ taste signal
that aggregates upward into a community consensus (read-time precedence:
DJ override -> community consensus -> LLM cached). Vibe-signal columns are
nullable: they are filled by the enrichment pipeline in a later phase.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class TrackVibe(Base):
    """Global LLM vibe cache. One row per track+provider+model+prompt+schema."""

    __tablename__ = "track_vibes"
    __table_args__ = (
        UniqueConstraint(
            "track_id",
            "llm_provider",
            "llm_model",
            "prompt_version",
            "schema_version",
            name="uq_track_vibe_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Vibe signal (LLM-derived, filled by enrichment in a later phase)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10
    mood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    era: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sing_along: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dance_floor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # "intro" | "build" | "peak" | "cool" | "any"
    transitional_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-1

    # Provenance / granular invalidation (identity columns — part of UNIQUE)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrackVibeOverride(Base):
    """Per-DJ taste override. Aggregated upward into community consensus."""

    __tablename__ = "track_vibe_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    energy_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_override: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Good-citizen provenance for future taste training
    overridden_from_vibe_id: Mapped[int | None] = mapped_column(
        ForeignKey("track_vibes.id", ondelete="SET NULL"), nullable=True
    )
    energy_was: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood_was: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # "explicit_edit" | "upvote" | "downvote_implicit"
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

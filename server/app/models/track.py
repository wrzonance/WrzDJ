"""Master enriched-track table (#540) — single source of truth for song data.

ISRC-first identity with a normalized artist/title signature fallback, so every
track gets exactly one row. Typed value columns are queryable; per-field
source/freshness lives in the `provenance` JSON sidecar (see services/tracks).
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        UniqueConstraint("isrc", name="uq_tracks_isrc"),
        UniqueConstraint("signature", name="uq_tracks_signature"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    isrc: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    soundcharts_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    camelot: Mapped[str | None] = mapped_column(String(3), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10
    danceability: Mapped[float | None] = mapped_column(Float, nullable=True)
    valence: Mapped[float | None] = mapped_column(Float, nullable=True)
    acousticness: Mapped[float | None] = mapped_column(Float, nullable=True)
    instrumentalness: Mapped[float | None] = mapped_column(Float, nullable=True)
    speechiness: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness: Mapped[float | None] = mapped_column(Float, nullable=True)
    loudness_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_signature: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explicit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

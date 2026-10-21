"""Shared track metadata model used by music services."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TrackProfile:
    """A track with metadata for scoring."""

    title: str
    artist: str
    bpm: float | None = None
    key: str | None = None
    genre: str | None = None
    source: str = "unknown"
    track_id: str | None = None
    url: str | None = None
    cover_url: str | None = None
    duration_seconds: int | None = None

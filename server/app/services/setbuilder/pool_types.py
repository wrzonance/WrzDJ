"""Shared value types for SetBuilder pool operations."""

from dataclasses import dataclass

from app.services.music_matching import parse_key


def camelot_code(key: str | None) -> str | None:
    """Convert any common key notation to a Camelot code (for example, ``8B``)."""
    pos = parse_key(key)
    return str(pos) if pos else None


class PoolImportError(Exception):
    """Import failed for a user-presentable reason (message is safe to surface)."""


@dataclass(frozen=True)
class PoolCandidate:
    """A track candidate produced by an import flow, pre-insert."""

    title: str
    artist: str
    track_id: str | None = None
    album: str | None = None
    genre: str | None = None
    bpm: float | None = None
    key: str | None = None
    energy: int | None = None
    isrc: str | None = None
    duration_sec: int | None = None
    artwork_url: str | None = None

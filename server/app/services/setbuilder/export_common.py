"""Shared export-tracklist collection for WrzDJSet exports (issue #396).

The exported setlist is the ordered SetSlot timeline, with track metadata
joined from the pool via the namespaced ``track_id`` convention
("tidal:123", "beatport:45", ...). Until timeline auto-fill (#390) lands,
sets typically have no slots — in that case we fall back to the pool in
insertion order and report ``source="pool"`` so the UI can say so
(visible, never silent).

A slot whose ``track_id`` has no matching pool row is an "orphan": it
exports as a metadata-less ExportTrack and surfaces in the unresolved
list — never silently dropped (exec summary §10).
"""

from dataclasses import dataclass
from typing import Literal

from app.models.set import Set
from app.models.set_pool import SetPoolTrack

ExportSource = Literal["timeline", "pool"]

_TIDAL_PREFIX = "tidal:"


@dataclass(frozen=True)
class ExportTrack:
    """One ordered entry of the exportable setlist."""

    position: int
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    bpm: float | None = None
    key: str | None = None
    camelot: str | None = None
    isrc: str | None = None
    duration_sec: int | None = None
    track_id: str | None = None  # namespaced pool/slot id, e.g. "tidal:123"

    @property
    def tidal_id(self) -> str | None:
        """Tidal track id when the namespaced id is a Tidal one."""
        if self.track_id and self.track_id.startswith(_TIDAL_PREFIX):
            return self.track_id[len(_TIDAL_PREFIX) :]
        return None

    @property
    def has_metadata(self) -> bool:
        """True when the track carries enough text metadata to export."""
        return bool(self.title and self.artist)


def _from_pool_track(position: int, pt: SetPoolTrack) -> ExportTrack:
    return ExportTrack(
        position=position,
        title=pt.title,
        artist=pt.artist,
        album=pt.album,
        genre=pt.genre,
        bpm=pt.bpm,
        key=pt.key,
        camelot=pt.camelot,
        isrc=pt.isrc,
        duration_sec=pt.duration_sec,
        track_id=pt.track_id,
    )


def collect_export_tracks(set_obj: Set) -> tuple[ExportSource, list[ExportTrack]]:
    """Ordered exportable tracklist for a set.

    Timeline slots (sorted by position) joined to pool metadata when any
    non-empty slots exist; otherwise the pool in insertion order.
    """
    slots = sorted((s for s in set_obj.slots if s.track_id), key=lambda s: s.position)
    if slots:
        pool_by_tid = {pt.track_id: pt for pt in set_obj.pool_tracks if pt.track_id}
        tracks: list[ExportTrack] = []
        for idx, slot in enumerate(slots):
            pt = pool_by_tid.get(slot.track_id)
            if pt is not None:
                tracks.append(_from_pool_track(idx, pt))
            else:  # orphan slot — keep it visible, never drop
                tracks.append(
                    ExportTrack(position=idx, title="", artist="", track_id=slot.track_id)
                )
        return "timeline", tracks

    pool = sorted(set_obj.pool_tracks, key=lambda pt: pt.id)
    return "pool", [_from_pool_track(idx, pt) for idx, pt in enumerate(pool)]

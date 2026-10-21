"""Canonical metadata projection for SetBuilder pool tracks."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.set_pool import SetPoolTrack
from app.services.setbuilder import taste_profile as taste_profile_service
from app.services.setbuilder.taste_profile import TasteProfile
from app.services.setbuilder.vibe_resolver import ResolvedVibe


@dataclass(frozen=True)
class TrackMeta:
    pool_id: int
    slot_track_id: str
    title: str
    artist: str
    bpm: float | None
    key: str | None
    energy: float | None
    mood: str | None = None
    genre: str | None = None
    transitional_role: str | None = None


def build_track_meta(
    track: SetPoolTrack,
    resolved: ResolvedVibe | None = None,
    profile: TasteProfile | None = None,
) -> TrackMeta:
    """Project pool, resolved-vibe, and profile data into transition metadata."""
    energy = track.energy
    mood = None
    if resolved is not None:
        if resolved.energy is not None:
            energy = taste_profile_service.taste_adjusted_energy(resolved, profile)
        mood = resolved.mood
    return TrackMeta(
        pool_id=track.id,
        slot_track_id=track.track_id or f"pool:{track.id}",
        title=track.title,
        artist=track.artist,
        bpm=track.bpm,
        key=track.camelot or track.key,
        energy=energy,
        mood=mood,
        genre=track.genre,
    )

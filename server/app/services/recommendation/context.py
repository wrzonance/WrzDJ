"""Immutable inputs shared by recommendation generation stages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.recommendation.scorer import EventProfile
from app.services.tracks.profile import TrackProfile

if TYPE_CHECKING:
    from app.models.request import Request


@dataclass(frozen=True)
class RecommendationContext:
    """Read-only event and source data used to build recommendations.

    ``event_profile`` is a borrowed read-only domain object. Sequence inputs are
    copied into tuples so the context owns its collection bindings and callers
    can continue mutating their original lists without changing this snapshot.
    """

    event_profile: EventProfile
    accepted_tracks: Sequence[TrackProfile] = ()
    rejected_tracks: Sequence[tuple[str, str]] = ()
    currently_playing: tuple[str, str, float | None] | None = None
    requests: Sequence[Request] = ()
    template_tracks: Sequence[TrackProfile] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_tracks", tuple(self.accepted_tracks))
        object.__setattr__(
            self,
            "rejected_tracks",
            tuple((artist, title) for artist, title in self.rejected_tracks),
        )
        object.__setattr__(self, "requests", tuple(self.requests))
        object.__setattr__(self, "template_tracks", tuple(self.template_tracks))

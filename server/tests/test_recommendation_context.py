from dataclasses import FrozenInstanceError

import pytest

from app.services.recommendation.context import RecommendationContext
from app.services.recommendation.scorer import EventProfile
from app.services.tracks.profile import TrackProfile


def test_context_owns_immutable_copies_of_caller_sequences():
    accepted_tracks = [TrackProfile(title="Blue Monday", artist="New Order")]
    rejected_tracks = [("Aqua", "Barbie Girl")]
    requests = []
    template_tracks = []
    context = RecommendationContext(
        event_profile=EventProfile(track_count=1),
        accepted_tracks=accepted_tracks,
        rejected_tracks=rejected_tracks,
        requests=requests,
        template_tracks=template_tracks,
    )

    accepted_tracks.append(TrackProfile(title="One More Time", artist="Daft Punk"))
    rejected_tracks.append(("Vengaboys", "Boom Boom Boom Boom"))
    requests.append(object())
    template_tracks.append(TrackProfile(title="Around the World", artist="Daft Punk"))

    assert [track.title for track in context.accepted_tracks] == ["Blue Monday"]
    assert context.rejected_tracks == (("Aqua", "Barbie Girl"),)
    assert context.requests == ()
    assert context.template_tracks == ()
    with pytest.raises(FrozenInstanceError):
        context.accepted_tracks = ()

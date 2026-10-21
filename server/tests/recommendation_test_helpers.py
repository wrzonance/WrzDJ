"""Shared recommendation test builders."""

from unittest.mock import MagicMock

from app.services.recommendation.context import RecommendationContext
from app.services.recommendation.scorer import EventProfile


def _make_user(tidal=True, beatport=True):
    user = MagicMock()
    user.tidal_access_token = "tok" if tidal else None
    user.beatport_access_token = "tok" if beatport else None
    return user


def _make_event(code="TEST1"):
    event = MagicMock()
    event.id = 1
    event.code = code
    return event


def _recommendation_context(profile=None, requests=(), template_tracks=()):
    return RecommendationContext(
        event_profile=profile or EventProfile(track_count=0),
        requests=requests,
        template_tracks=template_tracks,
    )

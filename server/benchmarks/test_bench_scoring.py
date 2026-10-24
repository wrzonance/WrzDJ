"""Benchmarks for request priority scoring and recommendation ranking."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.music_matching import compatibility_score, parse_key
from app.services.priority_scorer import RequestScoreInput, rank_requests_by_priority
from app.services.recommendation.deduplication import (
    deduplicate_against_template,
    deduplicate_candidates,
)
from app.services.recommendation.scorer import (
    TrackProfile,
    build_event_profile,
    rank_candidates,
)

NOW = datetime(2026, 1, 1, 22, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def profiles(tracks) -> list[TrackProfile]:
    return [
        TrackProfile(
            title=t["title"],
            artist=t["artist"],
            bpm=t["bpm"],
            key=t["key"],
            genre=t["genre"],
            source="tidal" if t["index"] % 2 else "beatport",
        )
        for t in tracks
    ]


@pytest.fixture(scope="module")
def score_inputs(tracks) -> list[RequestScoreInput]:
    return [
        RequestScoreInput(
            request_id=t["index"],
            vote_count=(t["popularity"] * 7) % 25,
            created_at=NOW - timedelta(minutes=(t["index"] * 13) % 180),
            musical_key=t["key"],
            bpm=t["bpm"],
        )
        for t in tracks
    ]


@pytest.mark.benchmark
def test_rank_requests_by_priority(score_inputs):
    rank_requests_by_priority(score_inputs, now_playing_key="8A", now_playing_bpm=126.0, now=NOW)


@pytest.mark.benchmark
def test_camelot_parse_and_compatibility(tracks):
    parsed = [parse_key(t["key"]) for t in tracks]
    anchor = parse_key("8A")
    for p in parsed:
        compatibility_score(anchor, p)


@pytest.mark.benchmark
def test_build_profile_and_rank_candidates(profiles):
    event_profile = build_event_profile(profiles[:40])
    rank_candidates(profiles, event_profile, max_results=20)


@pytest.mark.benchmark
def test_deduplicate_candidates(profiles):
    deduplicate_candidates(profiles[:40])


@pytest.mark.benchmark
def test_deduplicate_against_template(profiles):
    deduplicate_against_template(profiles[:40], profiles[40:60])

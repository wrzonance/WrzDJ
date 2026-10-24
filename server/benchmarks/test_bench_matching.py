"""Benchmarks for track normalization, fuzzy matching, and search merging."""

from types import SimpleNamespace

import pytest

from app.schemas.beatport import BeatportSearchResult
from app.schemas.tidal import TidalSearchResult
from app.services.intent_parser import parse_intent
from app.services.search_merge import build_search_results
from app.services.track_match import find_best_match
from app.services.track_normalizer import (
    artist_match_score,
    fuzzy_match_score,
    normalize_track,
)
from app.services.version_filter import is_unwanted_version

QUERIES = [
    "sandstorm darude",
    "levels avicii",
    "one more time daft punk",
    "titanium sped up",
    "selected kaiser remix",
    "blue monday live",
    "innerbloom rufus du sol acoustic",
    "latch disclosure",
]


@pytest.mark.benchmark
def test_normalize_track(tracks):
    for t in tracks:
        normalize_track(t["title"], t["artist"])


@pytest.mark.benchmark
def test_fuzzy_and_artist_match_scores(tracks):
    head = tracks[:20]
    for a in head:
        for b in head:
            fuzzy_match_score(a["title"], b["title"])
            artist_match_score(a["artist"], b["artist"])


@pytest.mark.benchmark
def test_parse_intent():
    for q in QUERIES * 10:
        parse_intent(q)


@pytest.mark.benchmark
def test_is_unwanted_version(tracks):
    intent = parse_intent("titanium sped up")
    for t in tracks:
        is_unwanted_version(t["title"])
        is_unwanted_version(t["title"], intent)


@pytest.mark.benchmark
def test_find_best_match(tracks):
    results = [
        SimpleNamespace(
            title=t["title"],
            artist=t["artist"],
            bpm=t["bpm"],
            mix_name="Original Mix" if t["index"] % 3 == 0 else None,
        )
        for t in tracks[:40]
    ]
    for q in tracks[:10]:
        find_best_match(results, q["title"], q["artist"])


@pytest.fixture(scope="module")
def search_inputs(tracks):
    tidal = [
        TidalSearchResult(
            track_id=str(t["index"]),
            title=t["title"],
            artist=t["artist"],
            bpm=t["bpm"],
            key=t["key"],
            popularity=t["popularity"],
            isrc=t["isrc"],
        )
        for t in tracks[:60]
    ]
    beatport = [
        BeatportSearchResult(
            track_id=f"bp{t['index']}",
            title=t["title"],
            artist=t["artist"],
            mix_name="Extended Mix",
            genre=t["genre"],
            bpm=int(t["bpm"]) if t["bpm"] else None,
            key=t["key"],
        )
        for t in tracks[60:90]
    ]
    return tidal, beatport


@pytest.mark.benchmark
def test_build_search_results(search_inputs):
    tidal, beatport = search_inputs
    build_search_results(
        tidal_results=tidal,
        beatport_results=beatport,
        intent=parse_intent("one more time"),
    )

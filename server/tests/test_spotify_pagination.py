"""Regression coverage for #792 (limit=20 in 9ceb5e0801eabe681269f9c475f297c36e7059e3)."""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from requests import Response
from requests.exceptions import ReadTimeout
from spotipy import Spotify
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.search_cache import SearchCache
from app.services.spotify import search_songs


def response(body: dict, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://api.spotify.com/v1/search"
    result._content = json.dumps(body).encode()
    return result


def page(start: int, count: int, has_next: bool = False) -> Response:
    return response(
        {
            "tracks": {
                "href": "https://api.spotify.com/v1/search",
                "limit": 10,
                "offset": start,
                "total": 30 if has_next else start + count,
                "next": "https://api.spotify.com/v1/search?offset=10" if has_next else None,
                "previous": None,
                "items": [
                    {
                        "id": f"track{i}",
                        "name": f"Song {i}",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album", "images": []},
                        "external_ids": {"isrc": f"ISRC{i}"},
                        "preview_url": None,
                    }
                    for i in range(start, start + count)
                ],
            }
        }
    )


@pytest.fixture
def spotify_http():
    """Keep Spotipy real; stub only its HTTP transport, including the new limit."""
    client = Spotify(auth="test-token")
    responses = MagicMock()
    calls = []

    def request(method, url, **kwargs):
        params = kwargs["params"]
        calls.append(params.copy())
        assert method == "GET"
        assert url == "https://api.spotify.com/v1/search"
        if params["limit"] > 10:
            return response({"error": {"status": 400, "message": "Invalid limit"}}, 400)
        return responses()

    with (
        patch("app.services.spotify._get_spotify_client", return_value=client),
        patch.object(client._session, "request", side_effect=request),
        patch("app.services.spotify.time.sleep"),
    ):
        yield responses, calls
    client._session.close()


def test_twenty_results_use_two_legal_pages_and_cache_all_results(db: Session, spotify_http):
    responses, calls = spotify_http
    responses.side_effect = [page(0, 10, True), page(10, 10, True)]

    results = search_songs(db, "  Artist  ")

    assert len(results) == 20
    assert [r.spotify_id for r in results] == [f"track{i}" for i in range(20)]
    assert results[10].title == "Song 10"
    assert results[10].isrc == "ISRC10"
    assert results[10].popularity == 0
    assert [(c["q"], c["type"], c["limit"], c["offset"]) for c in calls] == [
        ("artist", "track", 10, 0),
        ("artist", "track", 10, 10),
    ]
    assert search_songs(db, "ARTIST") == results
    assert len(calls) == 2


@pytest.mark.parametrize("count", [1, 10])
def test_stops_when_spotify_has_no_next_page(db: Session, spotify_http, count):
    responses, calls = spotify_http
    responses.return_value = page(0, count)

    results = search_songs(db, "artist")

    assert len(results) == count
    assert len(calls) == 1


@pytest.mark.parametrize("count", [0, 3])
def test_short_second_page_preserves_available_results(db: Session, spotify_http, count):
    responses, calls = spotify_http
    responses.side_effect = [page(0, 10, True), page(10, count)]

    results = search_songs(db, "artist")

    assert [r.spotify_id for r in results] == [f"track{i}" for i in range(10 + count)]
    assert len(calls) == 2


def test_retries_only_the_timed_out_page_without_duplicates(db: Session, spotify_http):
    responses, calls = spotify_http
    responses.side_effect = [page(0, 10, True), ReadTimeout("timeout"), page(10, 10)]

    results = search_songs(db, "artist")

    assert [r.spotify_id for r in results] == [f"track{i}" for i in range(20)]
    assert [c["offset"] for c in calls] == [0, 10, 10]


@pytest.mark.parametrize("slow_page", [0, 1])
def test_slow_pages_share_the_original_search_time_budget(
    db: Session, spotify_http, monkeypatch, slow_page
):
    responses, calls = spotify_http
    elapsed = 0.0
    attempts = 0

    def slow_response():
        nonlocal elapsed, attempts
        elapsed += 15  # A full connect + read timeout allowance.
        attempts += 1
        if attempts < 3:
            raise ReadTimeout("timeout")
        return page(slow_page * 10, 10, not slow_page)

    def next_response():
        nonlocal elapsed
        if slow_page == 1 and len(calls) == 1:
            elapsed += 15
            return page(0, 10, True)
        return slow_response()

    def advance_time(seconds):
        nonlocal elapsed
        elapsed += seconds

    monkeypatch.setattr("app.services.spotify.time.monotonic", lambda: elapsed)
    monkeypatch.setattr("app.services.spotify.time.sleep", advance_time)
    responses.side_effect = next_response

    assert search_songs(db, "artist") == []
    assert elapsed <= 46.5  # Previous three 15s attempts plus 0.5s + 1s backoff.
    assert [c["offset"] for c in calls] == ([0, 0, 0] if slow_page == 0 else [0, 10, 10])
    assert db.query(SearchCache).count() == 0


@pytest.mark.parametrize("failed_page", [0, 1])
@pytest.mark.parametrize("failure", ["http", "timeout"])
def test_failed_search_is_not_cached_and_next_search_can_recover(
    db: Session, spotify_http, failed_page, failure
):
    responses, calls = spotify_http
    failures = (
        [ReadTimeout("timeout")] * 3
        if failure == "timeout"
        else [response({"error": {"status": 400, "message": "Invalid limit"}}, 400)]
    )
    responses.side_effect = [page(0, 10, True)] * failed_page + failures

    assert search_songs(db, "artist") == []
    assert db.query(SearchCache).count() == 0
    assert len(calls) == failed_page + len(failures)

    responses.side_effect = [page(0, 10, True), page(10, 10)]
    assert len(search_songs(db, "artist")) == 20
    assert db.query(SearchCache).count() == 1


def test_empty_search_is_not_cached(db: Session, spotify_http):
    responses, calls = spotify_http
    responses.return_value = page(0, 0)

    assert search_songs(db, "missing song") == []
    assert db.query(SearchCache).count() == 0
    assert len(calls) == 1


def test_legacy_empty_cache_is_refreshed_before_expiry(db: Session, spotify_http):
    responses, calls = spotify_http
    cached = SearchCache(
        query="artist",
        source="spotify",
        results_json="[]",
        expires_at=utcnow() + timedelta(hours=1),
    )
    db.add(cached)
    db.commit()
    responses.side_effect = [page(0, 10, True), page(10, 10)]

    assert len(search_songs(db, "artist")) == 20
    assert len(json.loads(cached.results_json)) == 20
    assert db.query(SearchCache).count() == 1
    assert len(calls) == 2

"""Integration tests for multi-service sync orchestration.

Validates that Tidal + Beatport sync produce correct sync_results_json.
"""

import json

from app.services.sync.base import SyncResult, SyncStatus, TrackMatch


def test_multi_service_sync_results_structure(test_request, db):
    """Both Tidal and Beatport results populate sync_results_json correctly."""
    from app.services.sync.orchestrator import _persist_sync_result

    # Simulate Tidal sync result (ADDED)
    tidal_result = SyncResult(
        service="tidal",
        status=SyncStatus.ADDED,
        track_match=TrackMatch(
            service="tidal",
            track_id="tidal-123",
            title="Test Song",
            artist="Test Artist",
            match_confidence=0.95,
            url="https://tidal.com/track/123",
            duration_seconds=240,
        ),
        playlist_id="tidal-playlist-1",
        error=None,
    )
    _persist_sync_result(test_request, tidal_result)
    db.commit()

    # Simulate Beatport sync result (MATCHED — search only)
    beatport_result = SyncResult(
        service="beatport",
        status=SyncStatus.MATCHED,
        track_match=TrackMatch(
            service="beatport",
            track_id="bp-456",
            title="Test Song",
            artist="Test Artist",
            match_confidence=0.88,
            url="https://beatport.com/track/test-song/456",
            duration_seconds=240,
        ),
        playlist_id=None,
        error=None,
    )
    _persist_sync_result(test_request, beatport_result)
    db.commit()

    # Verify sync_results_json
    results = json.loads(test_request.sync_results_json)
    assert len(results) == 2

    tidal = next(r for r in results if r["service"] == "tidal")
    assert tidal["status"] == "added"
    assert tidal["track_id"] == "tidal-123"
    assert tidal["confidence"] == 0.95
    assert tidal["url"] == "https://tidal.com/track/123"
    assert tidal["playlist_id"] == "tidal-playlist-1"

    beatport = next(r for r in results if r["service"] == "beatport")
    assert beatport["status"] == "matched"
    assert beatport["track_id"] == "bp-456"
    assert beatport["confidence"] == 0.88
    assert beatport["url"] == "https://beatport.com/track/test-song/456"
    assert beatport["playlist_id"] is None


def test_not_found_on_one_service_added_on_another(test_request, db):
    """One service finds the track, another doesn't — both recorded correctly."""
    from app.services.sync.orchestrator import _persist_sync_result

    tidal_result = SyncResult(
        service="tidal",
        status=SyncStatus.ADDED,
        track_match=TrackMatch(
            service="tidal",
            track_id="tidal-found",
            title="Found Song",
            artist="Artist",
            match_confidence=0.92,
        ),
        playlist_id="pl-1",
        error=None,
    )
    _persist_sync_result(test_request, tidal_result)

    beatport_result = SyncResult(
        service="beatport",
        status=SyncStatus.NOT_FOUND,
        track_match=None,
        playlist_id=None,
        error=None,
    )
    _persist_sync_result(test_request, beatport_result)
    db.commit()

    results = json.loads(test_request.sync_results_json)
    assert len(results) == 2

    tidal = next(r for r in results if r["service"] == "tidal")
    assert tidal["status"] == "added"
    assert tidal["track_id"] == "tidal-found"

    beatport = next(r for r in results if r["service"] == "beatport")
    assert beatport["status"] == "not_found"
    assert beatport["track_id"] is None


def test_persist_sync_result_with_non_list_json(test_request, db):
    """Persist handles sync_results_json that parses as non-list (e.g., null)."""
    from app.services.sync.orchestrator import _persist_sync_result

    test_request.sync_results_json = "null"
    db.commit()

    result = SyncResult(
        service="beatport",
        status=SyncStatus.MATCHED,
        track_match=TrackMatch(
            service="beatport",
            track_id="bp-guard",
            title="Guard Test",
            artist="Test",
            match_confidence=0.9,
        ),
    )
    _persist_sync_result(test_request, result)
    db.commit()

    results = json.loads(test_request.sync_results_json)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["service"] == "beatport"


def test_sync_results_exposed_in_api_response(client, auth_headers, test_request, db):
    """GET /api/events/{code}/requests returns sync_results_json."""
    from app.services.sync.orchestrator import _persist_sync_result

    tidal_result = SyncResult(
        service="tidal",
        status=SyncStatus.ADDED,
        track_match=TrackMatch(
            service="tidal",
            track_id="api-test-tidal",
            title="API Test",
            artist="API Artist",
            match_confidence=0.9,
        ),
        playlist_id="pl-api",
        error=None,
    )
    _persist_sync_result(test_request, tidal_result)
    db.commit()

    event = test_request.event
    response = client.get(f"/api/events/{event.code}/requests", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()["requests"]
    assert len(data) > 0
    req = next(r for r in data if r["id"] == test_request.id)
    assert req["sync_results_json"] is not None

    results = json.loads(req["sync_results_json"])
    assert results[0]["service"] == "tidal"
    assert results[0]["status"] == "added"

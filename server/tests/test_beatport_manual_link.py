"""Tests for Beatport manual track linking."""

import json
from unittest.mock import MagicMock, patch

from app.schemas.beatport import BeatportSearchResult
from app.services.providers.beatport import manual_link_beatport_track


def test_manual_link_stores_in_sync_results_json():
    """Manual link stores Beatport track info in sync_results_json."""
    db = MagicMock()
    request = MagicMock()
    request.sync_results_json = None

    track = BeatportSearchResult(
        track_id="12345",
        title="Strobe",
        artist="deadmau5",
        mix_name="Original Mix",
        beatport_url="https://beatport.com/track/strobe/12345",
        duration_seconds=630,
    )

    manual_link_beatport_track(db, request, track)

    result = json.loads(request.sync_results_json)
    assert len(result) == 1
    assert result[0]["service"] == "beatport"
    assert result[0]["status"] == "matched"
    assert result[0]["track_id"] == "12345"
    assert result[0]["track_title"] == "Strobe"
    assert result[0]["track_artist"] == "deadmau5"
    assert result[0]["confidence"] == 1.0
    assert result[0]["url"] == "https://beatport.com/track/strobe/12345"
    assert result[0]["duration_seconds"] == 630
    db.commit.assert_called_once()


def test_manual_link_replaces_existing_beatport_entry():
    """Manual link replaces any existing Beatport entry in sync_results_json."""
    db = MagicMock()
    request = MagicMock()
    request.sync_results_json = json.dumps(
        [
            {"service": "beatport", "status": "not_found", "track_id": None},
            {"service": "tidal", "status": "added", "track_id": "tidal-999"},
        ]
    )

    track = BeatportSearchResult(
        track_id="456",
        title="Levels",
        artist="Avicii",
        beatport_url="https://beatport.com/track/levels/456",
    )

    manual_link_beatport_track(db, request, track)

    result = json.loads(request.sync_results_json)
    assert len(result) == 2
    services = {r["service"] for r in result}
    assert services == {"tidal", "beatport"}
    beatport = next(r for r in result if r["service"] == "beatport")
    assert beatport["status"] == "matched"
    assert beatport["track_id"] == "456"
    # Tidal entry preserved
    tidal = next(r for r in result if r["service"] == "tidal")
    assert tidal["track_id"] == "tidal-999"


def test_manual_link_handles_corrupt_json():
    """Manual link handles corrupt sync_results_json gracefully."""
    db = MagicMock()
    request = MagicMock()
    request.sync_results_json = "not valid json"

    track = BeatportSearchResult(
        track_id="789",
        title="Test",
        artist="Test Artist",
    )

    manual_link_beatport_track(db, request, track)

    result = json.loads(request.sync_results_json)
    assert len(result) == 1
    assert result[0]["service"] == "beatport"
    assert result[0]["status"] == "matched"


def test_link_endpoint_requires_auth(client):
    """Link endpoint requires authentication."""
    response = client.post(
        "/api/beatport/requests/1/link",
        json={"beatport_track_id": "12345"},
    )
    assert response.status_code == 401


def test_link_endpoint_request_not_found(client, auth_headers, db):
    """Link endpoint returns 404 for nonexistent request."""
    response = client.post(
        "/api/beatport/requests/9999/link",
        json={"beatport_track_id": "12345"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_link_endpoint_not_authorized(client, auth_headers, test_event, test_request, db):
    """Link endpoint returns 404 for requests not owned by user (avoids leaking existence)."""
    # Create another user
    from app.models.user import User

    other_user = User(
        username="other_dj",
        password_hash="hash",
        role="dj",
    )
    db.add(other_user)
    db.flush()

    # Reassign event to other user
    test_event.created_by_user_id = other_user.id
    db.commit()

    response = client.post(
        f"/api/beatport/requests/{test_request.id}/link",
        json={"beatport_track_id": "12345"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_link_endpoint_no_beatport_account(client, auth_headers, test_request):
    """Link endpoint returns 400 when Beatport not linked."""
    response = client.post(
        f"/api/beatport/requests/{test_request.id}/link",
        json={"beatport_track_id": "12345"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "not linked" in response.json()["detail"]


def test_link_endpoint_track_not_on_beatport(client, auth_headers, test_user, test_request, db):
    """Link endpoint returns 404 when track not found on Beatport."""
    test_user.beatport_access_token = "valid-token"
    db.commit()

    with patch("app.api.beatport.get_beatport_track", return_value=None):
        response = client.post(
            f"/api/beatport/requests/{test_request.id}/link",
            json={"beatport_track_id": "99999"},
            headers=auth_headers,
        )
    assert response.status_code == 404
    assert "not found on Beatport" in response.json()["detail"]


def test_manual_link_with_non_list_sync_results_json():
    """Manual link handles sync_results_json that parses as non-list."""
    db = MagicMock()
    request = MagicMock()
    request.sync_results_json = '"not a list"'  # Valid JSON but not a list

    track = BeatportSearchResult(
        track_id="999",
        title="NonList",
        artist="Test",
    )

    manual_link_beatport_track(db, request, track)

    result = json.loads(request.sync_results_json)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["service"] == "beatport"


def test_link_endpoint_success(client, auth_headers, test_user, test_request, db):
    """Link endpoint succeeds when track found on Beatport."""
    test_user.beatport_access_token = "valid-token"
    db.commit()

    mock_track = BeatportSearchResult(
        track_id="12345",
        title="Strobe",
        artist="deadmau5",
        beatport_url="https://beatport.com/track/strobe/12345",
        duration_seconds=630,
    )

    with patch("app.api.beatport.get_beatport_track", return_value=mock_track):
        with patch("app.api.beatport.manual_link_beatport_track") as mock_link:
            response = client.post(
                f"/api/beatport/requests/{test_request.id}/link",
                json={"beatport_track_id": "12345"},
                headers=auth_headers,
            )
    assert response.status_code == 200
    assert response.json()["status"] == "linked"
    mock_link.assert_called_once()

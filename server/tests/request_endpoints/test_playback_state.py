"""Song request endpoint tests grouped by behavior."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.now_playing import NowPlaying


class TestMarkPlayingSingleActive:
    """Tests for single-active-playing enforcement and NowPlaying sync."""

    def _create_accepted_request(
        self, client: TestClient, auth_headers: dict, event: Event, title: str, artist: str
    ) -> int:
        """Helper: create and accept a request, return its ID."""
        resp = client.post(
            f"/api/events/{event.code}/requests",
            json={"artist": artist, "title": title, "source": "manual"},
        )
        req_id = resp.json()["id"]
        client.patch(
            f"/api/requests/{req_id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        return req_id

    def test_mark_playing_clears_previous(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Marking a second request PLAYING transitions the first to PLAYED."""
        req1 = self._create_accepted_request(
            client, auth_headers, test_event, "First Song", "Artist A"
        )
        req2 = self._create_accepted_request(
            client, auth_headers, test_event, "Second Song", "Artist B"
        )

        # Mark first as playing
        resp1 = client.patch(
            f"/api/requests/{req1}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "playing"

        # Mark second as playing — first should transition to played
        resp2 = client.patch(
            f"/api/requests/{req2}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "playing"

        # Verify first request is now played
        resp_check = client.get(
            f"/api/events/{test_event.code}/requests?status=played",
            headers=auth_headers,
        )
        played_ids = [r["id"] for r in resp_check.json()["requests"]]
        assert req1 in played_ids

    def test_mark_playing_updates_now_playing_table(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Mark playing upserts the NowPlaying row with source='manual'."""
        req_id = self._create_accepted_request(
            client, auth_headers, test_event, "Test Track", "Test Artist"
        )

        client.patch(
            f"/api/requests/{req_id}",
            json={"status": "playing"},
            headers=auth_headers,
        )

        np = db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first()
        assert np is not None
        assert np.title == "Test Track"
        assert np.artist == "Test Artist"
        assert np.source == "manual"
        assert np.matched_request_id == req_id

    def test_mark_played_clears_now_playing(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        """Marking a manually-playing request as played clears NowPlaying track data."""
        req_id = self._create_accepted_request(
            client, auth_headers, test_event, "Played Track", "Some Artist"
        )

        # Mark playing then played
        client.patch(
            f"/api/requests/{req_id}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        client.patch(
            f"/api/requests/{req_id}",
            json={"status": "played"},
            headers=auth_headers,
        )

        np = db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first()
        # NowPlaying should exist but with cleared track data
        if np:
            assert np.title == ""
            assert np.artist == ""

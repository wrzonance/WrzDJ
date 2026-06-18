"""Integration tests for priority sort on the request list endpoint.

TDD Phase 2: RED — tests for GET /api/events/{code}/requests?sort=best_match.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.request import Request, RequestStatus


def _create_request(
    db: Session,
    event: Event,
    title: str = "Song",
    artist: str = "Artist",
    *,
    vote_count: int = 0,
    bpm: float | None = None,
    musical_key: str | None = None,
    genre: str | None = None,
    status: str = RequestStatus.NEW.value,
    created_offset_minutes: int = 0,
) -> Request:
    """Helper to create a request with metadata."""
    req = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="manual",
        status=status,
        vote_count=vote_count,
        bpm=bpm,
        musical_key=musical_key,
        genre=genre,
        dedupe_key=f"dedupe_{title}_{artist}".lower().replace(" ", "_"),
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Shift created_at to simulate older requests
    if created_offset_minutes:
        req.created_at = utcnow() - timedelta(minutes=created_offset_minutes)
        db.commit()
        db.refresh(req)

    return req


class TestPrioritySortEndpoint:
    def test_default_sort_is_chronological(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        """Default sort (no param) should return requests by created_at DESC."""
        _create_request(db, test_event, "First", created_offset_minutes=10)
        _create_request(db, test_event, "Second", created_offset_minutes=5)
        _create_request(db, test_event, "Third", created_offset_minutes=1)

        resp = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["requests"]
        assert len(data) == 3
        # Newest first (Third, then Second, then First)
        assert data[0]["song_title"] == "Third"
        assert data[2]["song_title"] == "First"
        # priority_score should be null in chronological mode
        assert data[0].get("priority_score") is None

    def test_sort_by_priority_returns_scored_requests(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        """Priority sort should return requests with priority_score, ordered by score."""
        # High votes, old
        _create_request(
            db,
            test_event,
            "Popular",
            vote_count=10,
            created_offset_minutes=60,
        )
        # No votes, new
        _create_request(
            db,
            test_event,
            "Fresh",
            vote_count=0,
            created_offset_minutes=1,
        )
        # Some votes, medium age
        _create_request(
            db,
            test_event,
            "Moderate",
            vote_count=5,
            created_offset_minutes=30,
        )

        resp = client.get(
            f"/api/events/{test_event.code}/requests?sort=best_match",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["requests"]
        assert len(data) == 3

        # All should have priority_score
        for item in data:
            assert item["priority_score"] is not None
            assert 0.0 <= item["priority_score"] <= 1.0

        # Popular (10 votes + long wait) should be first
        assert data[0]["song_title"] == "Popular"

    def test_priority_sort_with_now_playing(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        """Harmonically compatible requests should rank higher with now-playing context."""
        # Create a now-playing track with known key/BPM via matched request
        np_request = _create_request(
            db,
            test_event,
            "Now Playing Track",
            bpm=128.0,
            musical_key="8A",
            status=RequestStatus.PLAYING.value,
        )
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Now Playing Track",
            artist="Artist",
            matched_request_id=np_request.id,
            source="manual",
        )
        db.add(now_playing)
        db.commit()

        # Compatible request (same key, close BPM)
        _create_request(
            db,
            test_event,
            "Compatible",
            vote_count=3,
            bpm=130.0,
            musical_key="8A",
            created_offset_minutes=30,
        )
        # Incompatible request (distant key, far BPM) but same votes/age
        _create_request(
            db,
            test_event,
            "Incompatible",
            vote_count=3,
            bpm=180.0,
            musical_key="3B",
            created_offset_minutes=30,
        )

        resp = client.get(
            f"/api/events/{test_event.code}/requests?sort=best_match&status=new",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["requests"]
        new_requests = [d for d in data if d["status"] == "new"]
        assert len(new_requests) == 2
        # Compatible should rank higher
        assert new_requests[0]["song_title"] == "Compatible"

    def test_priority_sort_without_now_playing(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        """Without now-playing, priority should still work (votes + time only)."""
        _create_request(
            db,
            test_event,
            "Popular",
            vote_count=8,
            created_offset_minutes=30,
        )
        _create_request(
            db,
            test_event,
            "Unpopular",
            vote_count=0,
            created_offset_minutes=30,
        )

        resp = client.get(
            f"/api/events/{test_event.code}/requests?sort=best_match",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["requests"]
        assert len(data) == 2
        # Popular should be first even without harmonic context
        assert data[0]["song_title"] == "Popular"
        # Scores should still be present
        assert data[0]["priority_score"] is not None

    def test_priority_score_null_when_chronological(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        """Default sort should NOT compute priority scores (performance)."""
        _create_request(db, test_event, "Song")

        resp = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["requests"]
        assert data[0]["priority_score"] is None

    def test_sort_param_validation(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
    ):
        """Invalid sort param should return 422."""
        resp = client.get(
            f"/api/events/{test_event.code}/requests?sort=invalid",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_priority_sort_with_status_filter(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        db: Session,
    ):
        """Priority sort combined with status filter should work."""
        _create_request(
            db,
            test_event,
            "New Song",
            vote_count=5,
            status=RequestStatus.NEW.value,
            created_offset_minutes=30,
        )
        _create_request(
            db,
            test_event,
            "Accepted Song",
            vote_count=10,
            status=RequestStatus.ACCEPTED.value,
            created_offset_minutes=60,
        )

        resp = client.get(
            f"/api/events/{test_event.code}/requests?sort=best_match&status=new",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["requests"]
        # Only NEW requests
        assert len(data) == 1
        assert data[0]["song_title"] == "New Song"
        assert data[0]["priority_score"] is not None

    def test_priority_sort_no_auth_returns_401(
        self,
        client: TestClient,
        test_event: Event,
    ):
        """Unauthenticated request should fail."""
        resp = client.get(
            f"/api/events/{test_event.code}/requests?sort=best_match",
        )
        assert resp.status_code == 401

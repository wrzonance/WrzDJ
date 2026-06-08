"""Tests for public/kiosk endpoints."""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.now_playing import NowPlaying
from app.models.request import Request, RequestStatus


def _make_guest_and_cookie(client: TestClient, db: Session, suffix: str = "a") -> Guest:
    g = Guest(
        token=suffix.ljust(64, "0"),
        fingerprint_hash=f"fp_{suffix}",
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    client.cookies.clear()
    client.cookies.set("wrzdj_guest", g.token)
    return g


class TestMyRequests:
    """Tests for GET /api/public/events/{code}/my-requests endpoint."""

    def test_my_requests_returns_own_requests(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """my-requests returns only requests with matching guest_id."""
        guest = _make_guest_and_cookie(client, db)
        req1 = Request(
            event_id=test_event.id,
            song_title="My Song",
            artist="My Artist",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="my_req_001",
            guest_id=guest.id,
        )
        req2 = Request(
            event_id=test_event.id,
            song_title="Other Song",
            artist="Other Artist",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="other_req_001",
        )
        db.add_all([req1, req2])
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/my-requests")
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) == 1
        assert data["requests"][0]["title"] == "My Song"

    def test_my_requests_returns_all_statuses(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """my-requests includes all statuses, not just new/accepted."""
        guest = _make_guest_and_cookie(client, db)
        statuses = [
            RequestStatus.NEW,
            RequestStatus.ACCEPTED,
            RequestStatus.PLAYING,
            RequestStatus.PLAYED,
            RequestStatus.REJECTED,
        ]
        for i, status in enumerate(statuses):
            req = Request(
                event_id=test_event.id,
                song_title=f"Song {status.value}",
                artist="Artist",
                source="spotify",
                status=status.value,
                dedupe_key=f"status_test_{i}",
                guest_id=guest.id,
            )
            db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/my-requests")
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) == 5
        returned_statuses = {r["status"] for r in data["requests"]}
        assert returned_statuses == {"new", "accepted", "playing", "played", "rejected"}

    def test_my_requests_empty(self, client: TestClient, test_event: Event):
        """my-requests returns empty list when no requests match."""
        response = client.get(f"/api/public/events/{test_event.join_code}/my-requests")
        assert response.status_code == 200
        data = response.json()
        assert data["requests"] == []

    def test_my_requests_event_not_found(self, client: TestClient):
        """my-requests for nonexistent event returns 404."""
        response = client.get("/api/public/events/NOTFOUND/my-requests")
        assert response.status_code == 404

    def test_my_requests_includes_metadata(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """my-requests includes all expected fields."""
        guest = _make_guest_and_cookie(client, db)
        req = Request(
            event_id=test_event.id,
            song_title="Detailed Song",
            artist="Detailed Artist",
            artwork_url="https://example.com/art.jpg",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="detailed_test_001",
            vote_count=5,
            guest_id=guest.id,
        )
        db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/my-requests")
        assert response.status_code == 200
        data = response.json()
        r = data["requests"][0]
        assert r["title"] == "Detailed Song"
        assert r["artist"] == "Detailed Artist"
        assert r["artwork_url"] == "https://example.com/art.jpg"
        assert r["status"] == "accepted"
        assert r["vote_count"] == 5
        assert "created_at" in r


class TestKioskDisplay:
    """Tests for GET /api/public/events/{code}/display endpoint."""

    def test_kiosk_display_success(self, client: TestClient, test_event: Event):
        """Test getting kiosk display data."""
        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["event"]["code"] == test_event.join_code
        assert data["event"]["name"] == test_event.name
        assert "qr_join_url" in data
        assert "accepted_queue" in data
        assert "now_playing" in data
        assert "updated_at" in data

    def test_kiosk_display_event_not_found(self, client: TestClient):
        """Test kiosk display for nonexistent event."""
        response = client.get("/api/public/events/NOTFOUND/display")
        assert response.status_code == 404

    def test_kiosk_display_accepted_queue(self, client: TestClient, test_event: Event, db: Session):
        """Test that accepted requests appear in queue."""
        request = Request(
            event_id=test_event.id,
            song_title="Accepted Song",
            artist="Queue Artist",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="accepted_queue_test_123",
        )
        db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert len(data["accepted_queue"]) == 1
        assert data["accepted_queue"][0]["title"] == "Accepted Song"
        assert data["accepted_queue"][0]["artist"] == "Queue Artist"

    def test_kiosk_display_now_playing(self, client: TestClient, test_event: Event, db: Session):
        """Test that now_playing shows the current song."""
        request = Request(
            event_id=test_event.id,
            song_title="Now Playing Song",
            artist="Playing Artist",
            source="manual",
            status=RequestStatus.PLAYING.value,
            dedupe_key="now_playing_test_123",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        np = NowPlaying(
            event_id=test_event.id,
            title="Now Playing Song",
            artist="Playing Artist",
            matched_request_id=request.id,
            source="manual",
        )
        db.add(np)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing"] is not None
        assert data["now_playing"]["title"] == "Now Playing Song"
        assert data["now_playing"]["artist"] == "Playing Artist"

    def test_kiosk_display_no_now_playing(self, client: TestClient, test_event: Event):
        """Test kiosk display when nothing is playing."""
        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["now_playing"] is None

    def test_kiosk_display_qr_url_format(self, client: TestClient, test_event: Event):
        """Test QR join URL is properly formatted and uses the join_code (not collection code)."""
        from urllib.parse import urlparse

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        # QR target is the frictionless live URL — must use join_code on the
        # /join/ path segment exactly (avoid loose substring checks that can
        # pass when code is a substring of join_code or vice versa).
        path = urlparse(data["qr_join_url"]).path
        assert path == f"/join/{test_event.join_code}"

    def test_kiosk_display_nickname_in_queue(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that nickname appears in accepted queue items."""
        request = Request(
            event_id=test_event.id,
            song_title="Party Song",
            artist="DJ Artist",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="nickname_queue_test",
            nickname="Sarah",
        )
        db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert len(data["accepted_queue"]) == 1
        assert data["accepted_queue"][0]["nickname"] == "Sarah"

    def test_kiosk_display_null_nickname(self, client: TestClient, test_event: Event, db: Session):
        """Test that nickname is null when not provided."""
        request = Request(
            event_id=test_event.id,
            song_title="No Name Song",
            artist="Anonymous",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="no_nickname_test",
        )
        db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert data["accepted_queue"][0]["nickname"] is None


class TestGuestRequestList:
    """Tests for GET /api/public/events/{code}/requests endpoint."""

    def test_nickname_in_guest_list(self, client: TestClient, test_event: Event, db: Session):
        """Test that nicknames appear in guest request list."""
        request = Request(
            event_id=test_event.id,
            song_title="My Jam",
            artist="Cool Artist",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="guest_nick_test",
            nickname="Mike",
        )
        db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) == 1
        assert data["requests"][0]["nickname"] == "Mike"

    def test_no_nickname_in_guest_list(self, client: TestClient, test_event: Event, db: Session):
        """Test that nickname is null when not set."""
        request = Request(
            event_id=test_event.id,
            song_title="Anonymous Song",
            artist="Unknown",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="guest_no_nick_test",
        )
        db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["requests"][0]["nickname"] is None

    def test_paginates_and_reports_total(self, client: TestClient, test_event: Event, db: Session):
        """limit/offset slice the list; total reports the full count."""
        for i in range(5):
            db.add(
                Request(
                    event_id=test_event.id,
                    song_title=f"Track {i:03d}",
                    artist="Artist",
                    source="spotify",
                    status=RequestStatus.NEW.value,
                    dedupe_key=f"pub_pg_{i}",
                    vote_count=i,  # distinct → deterministic vote_count desc order
                )
            )
        db.commit()

        # Order is vote_count desc → Track 004 (4), 003 (3), 002 (2), 001 (1), 000 (0)
        r1 = client.get(f"/api/public/events/{test_event.join_code}/requests?limit=2&offset=0")
        assert r1.status_code == 200
        b1 = r1.json()
        assert [x["title"] for x in b1["requests"]] == ["Track 004", "Track 003"]
        assert b1["total"] == 5

        r2 = client.get(f"/api/public/events/{test_event.join_code}/requests?limit=2&offset=2")
        b2 = r2.json()
        assert [x["title"] for x in b2["requests"]] == ["Track 002", "Track 001"]
        assert b2["total"] == 5

    def test_total_reflects_full_count_beyond_page(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Regression: the list was hard-capped at .limit(50); total must be honest."""
        for i in range(6):
            db.add(
                Request(
                    event_id=test_event.id,
                    song_title=f"S{i}",
                    artist="Artist",
                    source="spotify",
                    status=RequestStatus.NEW.value,
                    dedupe_key=f"pub_tot_{i}",
                    vote_count=0,
                )
            )
        db.commit()

        r = client.get(f"/api/public/events/{test_event.join_code}/requests?limit=2")
        assert r.status_code == 200
        body = r.json()
        assert len(body["requests"]) == 2
        assert body["total"] == 6

    def test_rejects_oversized_limit(self, client: TestClient, test_event: Event):
        r = client.get(f"/api/public/events/{test_event.join_code}/requests?limit=99999")
        assert r.status_code == 422

    def test_tiebreaker_orders_by_id_desc(self, client: TestClient, test_event: Event, db: Session):
        """Rows tied on (vote_count, created_at) order by id desc so offset pages
        stay stable (no dup/skip). Pins the CodeRabbit pagination finding."""
        same_time = utcnow()
        ids = []
        for i in range(3):
            r = Request(
                event_id=test_event.id,
                song_title=f"Tie {i}",
                artist="Artist",
                source="spotify",
                status=RequestStatus.NEW.value,
                dedupe_key=f"tie_{i}",
                vote_count=0,
                created_at=same_time,
            )
            db.add(r)
            db.flush()
            ids.append(r.id)
        db.commit()

        r = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert r.status_code == 200
        returned = [x["id"] for x in r.json()["requests"]]
        assert returned == sorted(ids, reverse=True)


class TestPublicRequestsEnrichmentFields:
    """bpm/musical_key/genre are exposed in /events/{code}/requests response."""

    def test_enrichment_fields_present_when_set(
        self, client: TestClient, test_event: Event, db: Session
    ):
        from app.models.request import Request, RequestStatus

        req = Request(
            event_id=test_event.id,
            song_title="Levels",
            artist="Avicii",
            source="beatport",
            status=RequestStatus.NEW.value,
            dedupe_key="levels_avicii_001",
            bpm=128.0,
            musical_key="8A",
            genre="Progressive House",
        )
        db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        requests = response.json()["requests"]
        assert len(requests) == 1
        assert requests[0]["bpm"] == 128
        assert requests[0]["musical_key"] == "8A"
        assert requests[0]["genre"] == "Progressive House"

    def test_enrichment_fields_null_when_not_set(
        self, client: TestClient, test_event: Event, db: Session
    ):
        from app.models.request import Request, RequestStatus

        req = Request(
            event_id=test_event.id,
            song_title="Unknown",
            artist="Someone",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="unknown_someone_001",
        )
        db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        requests = response.json()["requests"]
        assert len(requests) == 1
        assert requests[0]["bpm"] is None
        assert requests[0]["musical_key"] is None
        assert requests[0]["genre"] is None


class TestSubmitRequestNickname:
    """Tests for nickname field in POST /api/events/{code}/requests."""

    def test_submit_with_nickname(self, client: TestClient, test_event: Event, db: Session):
        """Test submitting a request with a nickname."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Test Artist",
                "title": "Test Song",
                "nickname": "Sarah",
                "source": "manual",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nickname"] == "Sarah"

    def test_submit_without_nickname(self, client: TestClient, test_event: Event, db: Session):
        """Test submitting a request without a nickname."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Test Artist",
                "title": "Test Song No Nick",
                "source": "manual",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nickname"] is None

    def test_nickname_max_length(self, client: TestClient, test_event: Event, db: Session):
        """Test that nickname rejects values over 30 chars."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Test Artist",
                "title": "Long Nick Song",
                "nickname": "A" * 31,
                "source": "manual",
            },
        )
        assert response.status_code == 422

    def test_nickname_whitespace_normalized(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that nickname whitespace is normalized."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Test Artist",
                "title": "Whitespace Nick Song",
                "nickname": "  Sarah  ",
                "source": "manual",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nickname"] == "Sarah"

    def test_empty_nickname_becomes_null(self, client: TestClient, test_event: Event, db: Session):
        """Test that empty string nickname becomes null."""
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={
                "artist": "Test Artist",
                "title": "Empty Nick Song",
                "nickname": "   ",
                "source": "manual",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nickname"] is None


class TestRequesterVerifiedField:
    """requester_verified field in GET /api/public/events/{code}/requests."""

    def test_verified_guest_shows_badge(self, client: TestClient, test_event: Event, db: Session):
        from app.models.guest import Guest

        guest = Guest(token="verified_public_test", email_verified_at=datetime(2026, 5, 1))
        db.add(guest)
        db.flush()
        req = Request(
            event_id=test_event.id,
            song_title="Badge Song",
            artist="Badge Artist",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="badge_test_001",
            guest_id=guest.id,
            nickname="Verified",
        )
        db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["requests"][0]["requester_verified"] is True

    def test_no_guest_shows_false(self, client: TestClient, test_event: Event, db: Session):
        req = Request(
            event_id=test_event.id,
            song_title="Orphan Song",
            artist="Orphan Artist",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="orphan_test_001",
        )
        db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["requests"][0]["requester_verified"] is False

    def test_unverified_guest_shows_false(self, client: TestClient, test_event: Event, db: Session):
        from app.models.guest import Guest

        guest = Guest(token="unverified_public_test", email_verified_at=None)
        db.add(guest)
        db.flush()
        req = Request(
            event_id=test_event.id,
            song_title="Unverified Song",
            artist="Unverified Artist",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="unverified_test_001",
            guest_id=guest.id,
        )
        db.add(req)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/requests")
        assert response.status_code == 200
        data = response.json()
        assert data["requests"][0]["requester_verified"] is False

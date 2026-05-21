"""Tests for request voting feature."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request, RequestStatus
from app.models.request_vote import RequestVote
from app.services.vote import RequestNotFoundError, add_vote, get_vote_count, has_voted, remove_vote


def _make_guest(db: Session, suffix: str) -> Guest:
    g = Guest(
        token=suffix.ljust(64, "0"),
        fingerprint_hash=f"fp_{suffix}",
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


class TestVoteService:
    """Tests for vote service functions."""

    def test_add_vote_creates_vote(self, db: Session, test_request: Request):
        """Test that add_vote creates a vote and increments count."""
        guest = _make_guest(db, "a")
        request, is_new = add_vote(db, test_request.id, guest_id=guest.id)
        assert is_new is True
        assert request.vote_count == 1

        # Verify vote record exists
        vote = (
            db.query(RequestVote)
            .filter(
                RequestVote.request_id == test_request.id,
                RequestVote.guest_id == guest.id,
            )
            .first()
        )
        assert vote is not None

    def test_add_vote_idempotent(self, db: Session, test_request: Request):
        """Test that voting twice from same guest is idempotent."""
        guest = _make_guest(db, "a")
        add_vote(db, test_request.id, guest_id=guest.id)
        request, is_new = add_vote(db, test_request.id, guest_id=guest.id)
        assert is_new is False
        assert request.vote_count == 1

    def test_add_vote_multiple_guests(self, db: Session, test_request: Request):
        """Test that different guests can vote independently."""
        for suffix in ("a", "b", "c"):
            g = _make_guest(db, suffix)
            add_vote(db, test_request.id, guest_id=g.id)
        db.refresh(test_request)
        assert test_request.vote_count == 3

    def test_add_vote_request_not_found(self, db: Session):
        """Test that voting for nonexistent request raises error."""
        guest = _make_guest(db, "a")
        try:
            add_vote(db, 99999, guest_id=guest.id)
            assert False, "Should have raised RequestNotFoundError"
        except RequestNotFoundError:
            pass

    def test_remove_vote(self, db: Session, test_request: Request):
        """Test removing a vote decrements count."""
        guest = _make_guest(db, "a")
        add_vote(db, test_request.id, guest_id=guest.id)
        request, was_removed = remove_vote(db, test_request.id, guest_id=guest.id)
        assert was_removed is True
        assert request.vote_count == 0

    def test_remove_vote_idempotent(self, db: Session, test_request: Request):
        """Test removing non-existent vote is idempotent."""
        guest = _make_guest(db, "a")
        request, was_removed = remove_vote(db, test_request.id, guest_id=guest.id)
        assert was_removed is False
        assert request.vote_count == 0

    def test_has_voted(self, db: Session, test_request: Request):
        """Test has_voted returns correct status."""
        guest = _make_guest(db, "a")
        assert has_voted(db, test_request.id, guest_id=guest.id) is False
        add_vote(db, test_request.id, guest_id=guest.id)
        assert has_voted(db, test_request.id, guest_id=guest.id) is True

    def test_get_vote_count(self, db: Session, test_request: Request):
        """Test get_vote_count returns correct count."""
        assert get_vote_count(db, test_request.id) == 0
        for suffix in ("a", "b"):
            g = _make_guest(db, suffix)
            add_vote(db, test_request.id, guest_id=g.id)
        assert get_vote_count(db, test_request.id) == 2

    def test_get_vote_count_nonexistent(self, db: Session):
        """Test get_vote_count for nonexistent request returns 0."""
        assert get_vote_count(db, 99999) == 0

    def test_vote_count_never_negative(self, db: Session, test_request: Request):
        """Test vote_count never goes below 0."""
        guest = _make_guest(db, "a")
        remove_vote(db, test_request.id, guest_id=guest.id)
        assert test_request.vote_count == 0

    def test_vote_count_clamped_at_zero_on_remove(self, db: Session, test_request: Request):
        """Test that vote_count stays at 0 when removing a vote with count already at 0."""
        guest = _make_guest(db, "a")
        add_vote(db, test_request.id, guest_id=guest.id)
        test_request.vote_count = 0
        db.commit()
        db.refresh(test_request)
        assert test_request.vote_count == 0

        # Remove the vote — SQL should clamp to 0, not go to -1
        request, was_removed = remove_vote(db, test_request.id, guest_id=guest.id)
        assert was_removed is True
        assert request.vote_count == 0


class TestVoteEndpoints:
    """Tests for vote API endpoints (cookie-required after IP-identity removal)."""

    def _set_cookie(self, client: TestClient, db: Session, suffix: str = "a") -> Guest:
        guest = _make_guest(db, suffix)
        client.cookies.clear()
        client.cookies.set("wrzdj_guest", guest.token)
        return guest

    def test_vote_success(self, client: TestClient, db: Session, test_request: Request):
        """Test POST /api/requests/{id}/vote succeeds with cookie."""
        self._set_cookie(client, db)
        response = client.post(f"/api/requests/{test_request.id}/vote")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "voted"
        assert data["vote_count"] == 1
        assert data["has_voted"] is True

    def test_vote_idempotent(self, client: TestClient, db: Session, test_request: Request):
        """Test voting twice from same guest is idempotent."""
        self._set_cookie(client, db)
        client.post(f"/api/requests/{test_request.id}/vote")
        response = client.post(f"/api/requests/{test_request.id}/vote")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "already_voted"
        assert data["vote_count"] == 1

    def test_vote_not_found(self, client: TestClient, db: Session):
        """Test voting for nonexistent request returns 404."""
        self._set_cookie(client, db)
        response = client.post("/api/requests/99999/vote")
        assert response.status_code == 404

    def test_unvote_success(self, client: TestClient, db: Session, test_request: Request):
        """Test DELETE /api/requests/{id}/vote removes vote."""
        self._set_cookie(client, db)
        client.post(f"/api/requests/{test_request.id}/vote")
        response = client.delete(f"/api/requests/{test_request.id}/vote")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unvoted"
        assert data["vote_count"] == 0
        assert data["has_voted"] is False

    def test_unvote_not_voted(self, client: TestClient, db: Session, test_request: Request):
        """Test unvoting when not voted is idempotent."""
        self._set_cookie(client, db)
        response = client.delete(f"/api/requests/{test_request.id}/vote")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_voted"
        assert data["vote_count"] == 0


class TestDuplicateAutoVote:
    """Tests for auto-voting on duplicate request submission."""

    def _set_cookie(self, client: TestClient, db: Session, suffix: str = "a") -> Guest:
        guest = _make_guest(db, suffix)
        client.cookies.clear()
        client.cookies.set("wrzdj_guest", guest.token)
        return guest

    def test_duplicate_request_auto_votes(self, client: TestClient, db: Session, test_event: Event):
        """Test that submitting a duplicate request auto-votes."""
        self._set_cookie(client, db, "a")
        response1 = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Vote Artist", "title": "Vote Song", "source": "manual"},
        )
        assert response1.status_code == 200
        assert response1.json()["is_duplicate"] is False

        # Different guest, duplicate submission should auto-vote
        self._set_cookie(client, db, "b")
        response2 = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Vote Artist", "title": "Vote Song", "source": "manual"},
        )
        assert response2.status_code == 200
        data = response2.json()
        assert data["is_duplicate"] is True
        assert data["vote_count"] >= 1

    def test_duplicate_auto_vote_idempotent(
        self, client: TestClient, db: Session, test_event: Event
    ):
        """Test that repeated duplicate submissions from same guest don't double-vote."""
        self._set_cookie(client, db, "a")
        client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Idempotent Artist", "title": "Idempotent Song", "source": "manual"},
        )
        # Same guest re-submits the same song
        client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Idempotent Artist", "title": "Idempotent Song", "source": "manual"},
        )
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Idempotent Artist", "title": "Idempotent Song", "source": "manual"},
        )
        data = response.json()
        # Vote count should be 1 (first duplicate submission auto-votes;
        # subsequent duplicates from same guest are idempotent — guest_id-keyed)
        assert data["vote_count"] == 1


class TestVoteCountInResponses:
    """Tests for vote counts in various API responses."""

    def _set_cookie(self, client: TestClient, db: Session, suffix: str = "a") -> Guest:
        guest = _make_guest(db, suffix)
        client.cookies.clear()
        client.cookies.set("wrzdj_guest", guest.token)
        return guest

    def test_submit_response_includes_vote_count(
        self, client: TestClient, db: Session, test_event: Event
    ):
        """Test that submit request response includes vote_count."""
        self._set_cookie(client, db)
        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Count Artist", "title": "Count Song", "source": "manual"},
        )
        assert response.status_code == 200
        assert "vote_count" in response.json()
        assert response.json()["vote_count"] == 0

    def test_list_requests_includes_vote_count(
        self,
        client: TestClient,
        auth_headers: dict,
        test_event: Event,
        test_request: Request,
    ):
        """Test that list requests response includes vote_count."""
        response = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "vote_count" in data[0]
        assert data[0]["vote_count"] == 0

    def test_update_status_includes_vote_count(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        """Test that update request response includes vote_count."""
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "vote_count" in response.json()

    def test_kiosk_display_includes_vote_count(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that kiosk display includes vote_count in accepted queue."""
        request = Request(
            event_id=test_event.id,
            song_title="Voted Song",
            artist="Voted Artist",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="voted_kiosk_test_123",
            vote_count=5,
        )
        db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        data = response.json()
        assert len(data["accepted_queue"]) == 1
        assert data["accepted_queue"][0]["vote_count"] == 5

    def test_kiosk_display_sorted_by_votes(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Test that kiosk accepted queue is sorted by vote_count descending."""
        for title, votes in [("Low Song", 1), ("High Song", 10), ("Mid Song", 5)]:
            request = Request(
                event_id=test_event.id,
                song_title=title,
                artist="Sort Artist",
                source="manual",
                status=RequestStatus.ACCEPTED.value,
                dedupe_key=f"sort_test_{title.lower().replace(' ', '_')}",
                vote_count=votes,
            )
            db.add(request)
        db.commit()

        response = client.get(f"/api/public/events/{test_event.join_code}/display")
        assert response.status_code == 200
        queue = response.json()["accepted_queue"]
        assert len(queue) == 3
        assert queue[0]["title"] == "High Song"
        assert queue[1]["title"] == "Mid Song"
        assert queue[2]["title"] == "Low Song"

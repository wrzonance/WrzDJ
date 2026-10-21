"""Event API tests grouped by behavior."""

from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.schemas.search import SearchResult
from tests.events.helpers import _enforce_human_verification


class TestEventSearch:
    """Tests for GET /api/events/{code}/search endpoint."""

    @patch("app.services.providers.spotify.search_songs")
    def test_event_search_returns_spotify_results(
        self, mock_search, client: TestClient, test_event: Event
    ):
        """Basic search returns Spotify results."""
        mock_search.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                album="For Lack of a Better Name",
                popularity=72,
                spotify_id="sp_strobe",
                source="spotify",
            )
        ]

        response = client.get(f"/api/events/{test_event.code}/search?q=deadmau5")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Strobe"
        assert data[0]["source"] == "spotify"

    @patch("app.services.providers.beatport.search_beatport_tracks")
    @patch("app.services.providers.spotify.search_songs")
    def test_event_search_includes_beatport_fallback(
        self, mock_spotify, mock_beatport, client: TestClient, db: Session, test_user: User
    ):
        """Event with Beatport-linked owner includes Beatport results."""
        # Give test_user Beatport tokens
        test_user.beatport_access_token = "bp_token"
        test_user.beatport_refresh_token = "bp_refresh"
        test_user.beatport_token_expires_at = utcnow() + timedelta(hours=1)
        db.flush()

        event = Event(
            code="BPSRCH",
            join_code="L8QGF8",
            name="BP Search Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            beatport_sync_enabled=True,
        )
        db.add(event)
        db.commit()

        mock_spotify.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                popularity=72,
                spotify_id="sp_strobe",
                source="spotify",
            )
        ]
        mock_beatport.return_value = [
            BeatportSearchResult(
                track_id="bp_99",
                title="Acid Phase",
                artist="DJ Pierre",
                beatport_url="https://www.beatport.com/track/acid-phase/99",
            )
        ]

        response = client.get(f"/api/events/{event.code}/search?q=acid+phase")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        sources = [r["source"] for r in data]
        assert "spotify" in sources
        assert "beatport" in sources

    @patch("app.services.providers.spotify.search_songs")
    def test_event_search_no_beatport_when_not_linked(
        self, mock_search, client: TestClient, test_event: Event
    ):
        """DJ without Beatport linked -> Spotify only, no errors."""
        mock_search.return_value = [
            SearchResult(
                title="Levels",
                artist="Avicii",
                popularity=85,
                spotify_id="sp_levels",
                source="spotify",
            )
        ]

        response = client.get(f"/api/events/{test_event.code}/search?q=levels")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert all(r["source"] == "spotify" for r in data)

    def test_event_search_expired_event_returns_410(
        self, client: TestClient, db: Session, test_user: User
    ):
        """Expired event returns 410 for search."""
        expired_event = Event(
            code="EXPSRC",
            join_code="TM2WQM",
            name="Expired Search Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(expired_event)
        db.commit()

        response = client.get(f"/api/events/{expired_event.code}/search?q=test")
        assert response.status_code == 410

    def test_event_search_not_found_returns_404(self, client: TestClient):
        """Nonexistent event returns 404 for search."""
        response = client.get("/api/events/NOEXST/search?q=test")
        assert response.status_code == 404

    def test_event_search_query_too_short(self, client: TestClient, test_event: Event):
        """Query shorter than 2 characters returns 422."""
        response = client.get(f"/api/events/{test_event.code}/search?q=x")
        assert response.status_code == 422

    def test_event_search_query_too_long(self, client: TestClient, test_event: Event):
        """Query longer than 200 characters returns 422."""
        long_query = "a" * 201
        response = client.get(f"/api/events/{test_event.code}/search?q={long_query}")
        assert response.status_code == 422

    @patch("app.services.providers.tidal.search_tidal_tracks")
    def test_event_search_tidal_primary(
        self, mock_tidal, client: TestClient, db: Session, test_user: User
    ):
        """Tidal is used as primary source when owner has Tidal linked."""
        from app.schemas.tidal import TidalSearchResult

        test_user.tidal_access_token = "tidal_token"
        db.flush()

        event = Event(
            code="TDSRCH",
            join_code="53VUXU",
            name="Tidal Search Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        mock_tidal.return_value = [
            TidalSearchResult(
                track_id="t123",
                title="Strobe",
                artist="deadmau5",
                tidal_url="https://tidal.com/browse/track/t123",
                popularity=80,
                isrc="USRC12345",
            )
        ]

        response = client.get(f"/api/events/{event.code}/search?q=strobe")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "tidal"
        assert data[0]["popularity"] == 80
        mock_tidal.assert_called_once()

    @patch("app.services.providers.spotify.search_songs")
    @patch("app.services.providers.tidal.search_tidal_tracks")
    def test_event_search_spotify_fallback_when_tidal_empty(
        self, mock_tidal, mock_spotify, client: TestClient, db: Session, test_user: User
    ):
        """Spotify is used when Tidal returns no results."""
        test_user.tidal_access_token = "tidal_token"
        db.flush()

        event = Event(
            code="FBSRCH",
            join_code="6DX252",
            name="Fallback Search Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        mock_tidal.return_value = []
        mock_spotify.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                popularity=72,
                spotify_id="sp_strobe",
                source="spotify",
            )
        ]

        response = client.get(f"/api/events/{event.code}/search?q=strobe")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "spotify"


class TestEventSearchOwnerBypass:
    """GET /api/events/{code}/search: authenticated event owners bypass the
    guest human-verification gate; everyone else is still gated when enforced.

    Regression for the production 403 a DJ hit using the dashboard "Search for
    Song" button: the DJ is JWT-authenticated but holds no guest wrzdj_human
    cookie, so with human_verification_enforced=True the public search rejected
    them with 403.
    """

    @patch("app.services.providers.spotify.search_songs")
    def test_owner_bypasses_human_gate_when_enforced(
        self, mock_search, client: TestClient, db: Session, test_event: Event, auth_headers: dict
    ):
        """Event owner with a valid JWT searches successfully even with
        enforcement on and no human cookie (was 403 before the fix)."""
        _enforce_human_verification(db)
        mock_search.return_value = [
            SearchResult(title="Levels", artist="Avicii", popularity=85, spotify_id="sp_levels")
        ]

        response = client.get(
            f"/api/events/{test_event.code}/search?q=levels", headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()[0]["title"] == "Levels"

    def test_anonymous_still_gated_when_enforced(
        self, client: TestClient, db: Session, test_event: Event
    ):
        """A request with no JWT and no human cookie stays 403 when enforced."""
        _enforce_human_verification(db)

        response = client.get(f"/api/events/{test_event.code}/search?q=levels")

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "human_verification_required"

    def test_non_owner_authenticated_still_gated_when_enforced(
        self, client: TestClient, db: Session, test_event: Event, admin_headers: dict
    ):
        """A different authenticated user (not the event owner) is still gated:
        the bypass is owner-only, not 'any logged-in user'."""
        _enforce_human_verification(db)

        response = client.get(
            f"/api/events/{test_event.code}/search?q=levels", headers=admin_headers
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "human_verification_required"


class TestSubmitRequestOwnerBypass:
    """POST /api/events/{code}/requests: authenticated event owners bypass the
    guest human-verification gate; everyone else is still gated when enforced.

    Regression for the production 403 a DJ hit using the dashboard "Add" button
    in the song-search modal: the DJ is JWT-authenticated but holds no guest
    wrzdj_human cookie, so with human_verification_enforced=True the public
    submit endpoint rejected them with 403 on their own event.
    """

    def test_owner_bypasses_human_gate_when_enforced(
        self, client: TestClient, db: Session, test_event: Event, auth_headers: dict
    ):
        """Event owner with a valid JWT submits a request even with enforcement
        on and no human cookie (was 403 before the fix)."""
        _enforce_human_verification(db)

        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Avicii", "title": "Levels"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["song_title"] == "Levels"

    def test_anonymous_still_gated_when_enforced(
        self, client: TestClient, db: Session, test_event: Event
    ):
        """A request with no JWT and no human cookie stays 403 when enforced."""
        _enforce_human_verification(db)

        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Avicii", "title": "Levels"},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "human_verification_required"

    def test_non_owner_authenticated_still_gated_when_enforced(
        self, client: TestClient, db: Session, test_event: Event, admin_headers: dict
    ):
        """A different authenticated user (not the event owner) is still gated:
        the bypass is owner-only, not 'any logged-in user'."""
        _enforce_human_verification(db)

        response = client.post(
            f"/api/events/{test_event.code}/requests",
            json={"artist": "Avicii", "title": "Levels"},
            headers=admin_headers,
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "human_verification_required"

"""Tests for search API endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.search_cache import SearchCache
from app.models.user import User


class TestSearchEndpoint:
    """Tests for GET /api/search."""

    @patch("app.services.providers.tidal.search_tidal_tracks")
    def test_search_tidal_primary(
        self, mock_tidal, client: TestClient, auth_headers: dict, test_user: User, db: Session
    ):
        """Tidal is used as primary when user has Tidal linked."""
        from app.schemas.tidal import TidalSearchResult

        test_user.tidal_access_token = "test_token"
        db.commit()

        mock_tidal.return_value = [
            TidalSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                tidal_url="https://tidal.com/browse/track/123",
                popularity=80,
            )
        ]

        response = client.get("/api/search?q=strobe", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Strobe"
        assert data[0]["source"] == "tidal"
        assert data[0]["popularity"] == 80
        mock_tidal.assert_called_once()

    @patch("app.services.providers.spotify.search_songs")
    @patch("app.services.providers.tidal.search_tidal_tracks")
    def test_search_spotify_fallback(
        self,
        mock_tidal,
        mock_spotify,
        client: TestClient,
        auth_headers: dict,
        test_user: User,
        db: Session,
    ):
        """Spotify is used as fallback when Tidal returns nothing."""
        test_user.tidal_access_token = "test_token"
        db.commit()
        mock_tidal.return_value = []

        from app.schemas.search import SearchResult

        mock_spotify.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                spotify_id="sp123",
                url="https://open.spotify.com/track/sp123",
                popularity=75,
            )
        ]

        response = client.get("/api/search?q=strobe", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["source"] == "spotify"

    @patch("app.services.providers.spotify.search_songs")
    def test_search_spotify_only_no_tidal(
        self, mock_search, client: TestClient, auth_headers: dict
    ):
        """Spotify used when user has no Tidal linked."""
        from app.schemas.search import SearchResult

        mock_search.return_value = [
            SearchResult(
                title="Strobe",
                artist="deadmau5",
                spotify_id="sp123",
                url="https://open.spotify.com/track/sp123",
            )
        ]

        response = client.get("/api/search?q=strobe", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Strobe"
        mock_search.assert_called_once()

    def test_search_requires_min_length(self, client: TestClient, auth_headers: dict):
        response = client.get("/api/search?q=a", headers=auth_headers)
        assert response.status_code == 422

    def test_search_rejects_empty_query(self, client: TestClient, auth_headers: dict):
        response = client.get("/api/search?q=", headers=auth_headers)
        assert response.status_code == 422

    @patch("app.services.providers.spotify.search_songs")
    def test_search_returns_empty_list(self, mock_search, client: TestClient, auth_headers: dict):
        mock_search.return_value = []

        response = client.get("/api/search?q=nonexistent", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    @patch("app.api.search.get_system_settings")
    def test_search_unavailable_returns_503(
        self, mock_settings, client: TestClient, auth_headers: dict, db: Session
    ):
        mock_obj = MagicMock()
        mock_obj.spotify_enabled = False
        mock_settings.return_value = mock_obj

        response = client.get("/api/search?q=test", headers=auth_headers)
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()


class TestClearSearchCache:
    """Tests for DELETE /api/search/cache."""

    def test_admin_can_clear_cache(self, client: TestClient, admin_headers: dict, db: Session):
        # Insert a cache entry
        entry = SearchCache(
            query="test_query",
            results_json="[]",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        db.add(entry)
        db.commit()

        response = client.delete("/api/search/cache", headers=admin_headers)
        assert response.status_code == 200
        assert "1" in response.json()["message"]

    def test_non_admin_cannot_clear_cache(self, client: TestClient, auth_headers: dict):
        response = client.delete("/api/search/cache", headers=auth_headers)
        assert response.status_code == 403

    def test_unauthenticated_cannot_clear_cache(self, client: TestClient):
        response = client.delete("/api/search/cache")
        assert response.status_code == 401

    def test_clear_empty_cache(self, client: TestClient, admin_headers: dict):
        response = client.delete("/api/search/cache", headers=admin_headers)
        assert response.status_code == 200
        assert "0" in response.json()["message"]

"""Tests for Spotify search service."""

import json
import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.search_cache import SearchCache
from app.schemas.search import SearchResult
from app.services.providers.spotify import search_songs, search_spotify_api

# --- Fixtures ---

SPOTIFY_API_RESPONSE = {
    "tracks": {
        "items": [
            {
                "name": "Strobe",
                "id": "abc123",
                "popularity": 75,
                "preview_url": "https://p.scdn.co/preview/abc123",
                "artists": [{"name": "deadmau5"}],
                "external_ids": {"isrc": "USRC17600001"},
                "album": {
                    "name": "For Lack of a Better Name",
                    "images": [
                        {"url": "https://i.scdn.co/image/large", "width": 640, "height": 640},
                        {"url": "https://i.scdn.co/image/medium", "width": 300, "height": 300},
                        {"url": "https://i.scdn.co/image/small", "width": 64, "height": 64},
                    ],
                },
            },
            {
                "name": "Ghosts N Stuff",
                "id": "def456",
                "popularity": 80,
                "preview_url": None,
                "artists": [{"name": "deadmau5"}, {"name": "Rob Swire"}],
                "album": {
                    "name": "For Lack of a Better Name",
                    "images": [
                        {"url": "https://i.scdn.co/image/large2", "width": 640, "height": 640},
                    ],
                },
            },
        ]
    }
}


class TestCallSpotifyApi:
    """Tests for search_spotify_api (raw API call with retry)."""

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_success_parsing(self, mock_get_client: MagicMock):
        """Test successful response parsing."""
        mock_sp = MagicMock()
        mock_sp.search.return_value = SPOTIFY_API_RESPONSE
        mock_get_client.return_value = mock_sp

        results = search_spotify_api("deadmau5 strobe")

        assert len(results) == 2
        assert results[0].title == "Strobe"
        assert results[0].artist == "deadmau5"
        assert results[0].spotify_id == "abc123"
        assert results[0].album == "For Lack of a Better Name"
        assert results[0].popularity == 75
        # Should pick 300x300 image
        assert results[0].album_art == "https://i.scdn.co/image/medium"
        # ISRC extracted from external_ids
        assert results[0].isrc == "USRC17600001"
        # Second track has no external_ids
        assert results[1].isrc is None

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_album_art_fallback_to_first(self, mock_get_client: MagicMock):
        """Test album art falls back to first image when no 300x300."""
        mock_sp = MagicMock()
        mock_sp.search.return_value = SPOTIFY_API_RESPONSE
        mock_get_client.return_value = mock_sp

        results = search_spotify_api("deadmau5")

        # Second track has no 300x300 image — falls back to first (640x640)
        assert results[1].album_art == "https://i.scdn.co/image/large2"

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_timeout_retry(self, mock_get_client: MagicMock):
        """Test timeout triggers retry."""
        from requests.exceptions import ReadTimeout

        mock_sp = MagicMock()
        mock_sp.search.side_effect = [
            ReadTimeout("timeout"),
            SPOTIFY_API_RESPONSE,
        ]
        mock_get_client.return_value = mock_sp

        with patch("app.services.providers.spotify.time.sleep"):
            results = search_spotify_api("deadmau5")

        assert len(results) == 2
        assert mock_sp.search.call_count == 2

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_max_retries_exhausted(self, mock_get_client: MagicMock):
        """Test returns empty list when all retries fail."""
        from requests.exceptions import ReadTimeout

        mock_sp = MagicMock()
        mock_sp.search.side_effect = ReadTimeout("timeout")
        mock_get_client.return_value = mock_sp

        with patch("app.services.providers.spotify.time.sleep"):
            results = search_spotify_api("deadmau5")

        assert results == []
        assert mock_sp.search.call_count == 3  # initial + 2 retries

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_general_error_returns_empty(self, mock_get_client: MagicMock):
        """Test non-timeout errors return empty immediately (no retry)."""
        mock_sp = MagicMock()
        mock_sp.search.side_effect = ValueError("API error")
        mock_get_client.return_value = mock_sp

        results = search_spotify_api("deadmau5")

        assert results == []
        assert mock_sp.search.call_count == 1

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_provider_error_log_omits_credential_url(self, mock_get_client: MagicMock, caplog):
        mock_sp = MagicMock()
        mock_sp.search.side_effect = ValueError(
            "https://api.spotify.com/v1/search?q=SECRET-LEAK-CANARY"
        )
        mock_get_client.return_value = mock_sp

        with caplog.at_level(logging.ERROR, logger="app.services.providers.spotify"):
            assert search_spotify_api("deadmau5") == []

        assert "SECRET-LEAK-CANARY" not in caplog.text
        assert "ValueError" in caplog.text

    @patch("app.services.providers.spotify.get_spotify_client")
    def test_timeout_log_omits_credential_url(self, mock_get_client: MagicMock, caplog):
        from requests.exceptions import ReadTimeout

        mock_sp = MagicMock()
        mock_sp.search.side_effect = ReadTimeout(
            "https://api.spotify.com/v1/search?q=SECRET-LEAK-CANARY"
        )
        mock_get_client.return_value = mock_sp

        with (
            patch("app.services.providers.spotify.time.sleep"),
            caplog.at_level(logging.WARNING, logger="app.services.providers.spotify"),
        ):
            assert search_spotify_api("deadmau5") == []

        assert "SECRET-LEAK-CANARY" not in caplog.text
        assert "ReadTimeout" in caplog.text


class TestSearchSongs:
    """Tests for search_songs (with caching)."""

    @patch("app.services.providers.spotify.search_spotify_api")
    def test_cache_miss_calls_api(self, mock_api: MagicMock, db: Session):
        """Test cache miss triggers API call and stores result."""
        mock_api.return_value = [
            SearchResult(artist="deadmau5", title="Strobe", spotify_id="abc123")
        ]

        results = search_songs(db, "deadmau5 strobe")

        assert len(results) == 1
        assert results[0].title == "Strobe"
        mock_api.assert_called_once_with("deadmau5 strobe")

        # Verify cache was created
        cached = db.query(SearchCache).filter(SearchCache.query == "deadmau5 strobe").first()
        assert cached is not None

    @patch("app.services.providers.spotify.search_spotify_api")
    def test_cache_hit_skips_api(self, mock_api: MagicMock, db: Session):
        """Test cache hit returns cached results without API call."""
        # Pre-populate cache
        cache_entry = SearchCache(
            query="deadmau5 strobe",
            results_json=json.dumps(
                [{"artist": "deadmau5", "title": "Strobe", "spotify_id": "abc123"}]
            ),
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(cache_entry)
        db.commit()

        results = search_songs(db, "deadmau5 strobe")

        assert len(results) == 1
        assert results[0].title == "Strobe"
        mock_api.assert_not_called()

    @patch("app.services.providers.spotify.search_spotify_api")
    def test_expired_cache_calls_api(self, mock_api: MagicMock, db: Session):
        """Test expired cache triggers new API call."""
        # Pre-populate expired cache
        cache_entry = SearchCache(
            query="deadmau5 strobe",
            results_json=json.dumps([{"artist": "old", "title": "old"}]),
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(cache_entry)
        db.commit()

        mock_api.return_value = [
            SearchResult(artist="deadmau5", title="Strobe", spotify_id="abc123")
        ]

        results = search_songs(db, "deadmau5 strobe")

        assert len(results) == 1
        assert results[0].title == "Strobe"
        mock_api.assert_called_once()

    @patch("app.services.providers.spotify.search_spotify_api")
    def test_empty_query_returns_empty(self, mock_api: MagicMock, db: Session):
        """Test empty query returns empty list without API call."""
        results = search_songs(db, "   ")

        assert results == []
        mock_api.assert_not_called()

    @patch("app.services.providers.spotify.search_spotify_api")
    def test_cache_upsert_existing(self, mock_api: MagicMock, db: Session):
        """Test that existing cache entries get updated (upserted)."""
        # Pre-populate expired cache
        cache_entry = SearchCache(
            query="deadmau5",
            results_json=json.dumps([{"artist": "old", "title": "old"}]),
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(cache_entry)
        db.commit()
        original_id = cache_entry.id

        mock_api.return_value = [
            SearchResult(artist="deadmau5", title="Strobe", spotify_id="new123")
        ]

        search_songs(db, "deadmau5")

        # Should update existing entry, not create new one
        entries = db.query(SearchCache).filter(SearchCache.query == "deadmau5").all()
        assert len(entries) == 1
        assert entries[0].id == original_id
        assert "new123" in entries[0].results_json

"""Tests for the MusicBrainz artist genre enrichment service."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.musicbrainz import (
    USER_AGENT,
    _throttle,
    _throttled_get,
    check_artist_exists,
    lookup_artist_genre,
    lookup_artist_genres,
)


@pytest.fixture(autouse=True)
def _reset_throttle():
    """Reset the throttle timer between tests."""
    _throttle.last_request_time = 0.0
    yield


def _mock_search_response(artists):
    """Build a mock artist search response."""
    return {"artists": artists}


def _mock_artist_response(genres):
    """Build a mock artist lookup response with genres."""
    return {"id": "test-mbid", "name": "Test Artist", "genres": genres}


class TestLookupArtistGenre:
    def test_returns_top_genre(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Radiohead", "score": 100}])
        artist_data = _mock_artist_response(
            [
                {"name": "alternative rock", "count": 15},
                {"name": "art rock", "count": 10},
                {"name": "electronic", "count": 5},
            ]
        )

        with patch("app.services.musicbrainz._throttled_get") as mock_get:
            mock_get.side_effect = [search_data, artist_data]
            result = lookup_artist_genre("Radiohead")

        assert result == "alternative rock"

    def test_returns_none_on_empty_artist_name(self):
        assert lookup_artist_genre("") is None
        assert lookup_artist_genre("   ") is None

    def test_returns_none_when_search_fails(self):
        with patch("app.services.musicbrainz._throttled_get", return_value=None):
            result = lookup_artist_genre("Nonexistent")

        assert result is None

    def test_returns_none_when_no_results(self):
        with patch(
            "app.services.musicbrainz._throttled_get",
            return_value=_mock_search_response([]),
        ):
            result = lookup_artist_genre("Nonexistent")

        assert result is None

    def test_returns_none_when_score_too_low(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Close Match", "score": 50}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            result = lookup_artist_genre("Something Else")

        assert result is None

    def test_returns_none_when_no_genres(self):
        search_data = _mock_search_response(
            [{"id": "abc-123", "name": "Obscure Artist", "score": 95}]
        )
        artist_data = _mock_artist_response([])

        with patch("app.services.musicbrainz._throttled_get") as mock_get:
            mock_get.side_effect = [search_data, artist_data]
            result = lookup_artist_genre("Obscure Artist")

        assert result is None

    def test_returns_none_when_artist_lookup_fails(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Radiohead", "score": 100}])
        with patch("app.services.musicbrainz._throttled_get") as mock_get:
            mock_get.side_effect = [search_data, None]
            result = lookup_artist_genre("Radiohead")

        assert result is None


class TestCheckArtistExists:
    def test_returns_true_with_mbid_for_match(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Radiohead", "score": 100}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Radiohead")

        assert verified is True
        assert mbid == "abc-123"

    def test_returns_false_when_score_too_low(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Close Match", "score": 50}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Something Else")

        assert verified is False
        assert mbid is None

    def test_returns_false_on_empty_name(self):
        assert check_artist_exists("") == (False, None)
        assert check_artist_exists("   ") == (False, None)

    def test_returns_false_when_search_fails(self):
        with patch("app.services.musicbrainz._throttled_get", return_value=None):
            verified, mbid = check_artist_exists("Nonexistent")

        assert verified is False
        assert mbid is None

    def test_returns_false_when_no_results(self):
        with patch(
            "app.services.musicbrainz._throttled_get",
            return_value=_mock_search_response([]),
        ):
            verified, mbid = check_artist_exists("Nonexistent")

        assert verified is False
        assert mbid is None

    def test_returns_false_when_no_mbid(self):
        search_data = _mock_search_response([{"name": "NoID Artist", "score": 95}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("NoID Artist")

        assert verified is False
        assert mbid is None

    def test_picks_first_high_score_match(self):
        search_data = _mock_search_response(
            [
                {"id": "low-id", "name": "Wrong", "score": 50},
                {"id": "high-id", "name": "Right", "score": 95},
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Right")

        assert verified is True
        assert mbid == "high-id"

    def test_rejects_various_artists_false_positive(self):
        """MB returns 'Various Artists' score=100 for nearly anything — must reject."""
        search_data = _mock_search_response(
            [{"id": "89ad4ac3", "name": "Various Artists", "score": 100}]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("electrofab music")

        assert verified is False
        assert mbid is None

    def test_rejects_unknown_false_positive(self):
        """MB returns '[unknown]' — must reject."""
        search_data = _mock_search_response([{"id": "some-id", "name": "[unknown]", "score": 95}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("random stock artist")

        assert verified is False
        assert mbid is None

    def test_rejects_partial_name_match(self):
        """'bombombini gusini brainrot' → MB returns 'Brainrot' (fuzzy < 0.7) → reject."""
        search_data = _mock_search_response([{"id": "75c51736", "name": "Brainrot", "score": 100}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("bombombini gusini brainrot")

        assert verified is False
        assert mbid is None

    def test_accepts_exact_match(self):
        """'deadmau5' → MB returns 'deadmau5' score=100 → accept."""
        search_data = _mock_search_response([{"id": "good-mbid", "name": "deadmau5", "score": 100}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("deadmau5")

        assert verified is True
        assert mbid == "good-mbid"

    def test_accepts_close_name_match(self):
        """Slight casing difference should still pass fuzzy threshold."""
        search_data = _mock_search_response([{"id": "mbid-123", "name": "Deadmau5", "score": 100}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("deadmau5")

        assert verified is True
        assert mbid == "mbid-123"

    def test_skips_false_positive_finds_real_match(self):
        """If first result is 'Various Artists', but second is a real match, accept the second."""
        search_data = _mock_search_response(
            [
                {"id": "va-id", "name": "Various Artists", "score": 100},
                {"id": "real-id", "name": "Field Music", "score": 92},
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Field Music")

        assert verified is True
        assert mbid == "real-id"

    def test_rejects_stock_disambiguation_royalty_free(self):
        """Artist with 'royalty-free' disambiguation should be rejected."""
        search_data = _mock_search_response(
            [
                {
                    "id": "stock-id",
                    "name": "Bobby Cole",
                    "score": 100,
                    "disambiguation": "royalty-free music producer",
                }
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Bobby Cole")

        assert verified is False
        assert mbid is None

    def test_rejects_stock_disambiguation_production_music(self):
        """Artist with 'production music' disambiguation should be rejected."""
        search_data = _mock_search_response(
            [
                {
                    "id": "pm-id",
                    "name": "Stock Artist",
                    "score": 95,
                    "disambiguation": "production music composer",
                }
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Stock Artist")

        assert verified is False
        assert mbid is None

    def test_rejects_stock_disambiguation_library_music(self):
        """Artist with 'library music' disambiguation should be rejected."""
        search_data = _mock_search_response(
            [
                {
                    "id": "lm-id",
                    "name": "Library Composer",
                    "score": 95,
                    "disambiguation": "library music",
                }
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Library Composer")

        assert verified is False
        assert mbid is None

    def test_accepts_normal_disambiguation(self):
        """Artist with normal disambiguation should pass."""
        search_data = _mock_search_response(
            [
                {
                    "id": "good-id",
                    "name": "Bobby Cole",
                    "score": 100,
                    "disambiguation": "British jazz pianist",
                }
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Bobby Cole")

        assert verified is True
        assert mbid == "good-id"

    def test_accepts_no_disambiguation(self):
        """Artist with no disambiguation field should pass."""
        search_data = _mock_search_response([{"id": "good-id", "name": "Deadmau5", "score": 100}])
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Deadmau5")

        assert verified is True
        assert mbid == "good-id"

    def test_skips_stock_finds_real_match(self):
        """If first result has stock disambiguation but second is clean, accept the second."""
        search_data = _mock_search_response(
            [
                {
                    "id": "stock-id",
                    "name": "Bobby Cole",
                    "score": 100,
                    "disambiguation": "royalty-free",
                },
                {
                    "id": "real-id",
                    "name": "Bobby Cole",
                    "score": 95,
                    "disambiguation": "British jazz pianist",
                },
            ]
        )
        with patch("app.services.musicbrainz._throttled_get", return_value=search_data):
            verified, mbid = check_artist_exists("Bobby Cole")

        assert verified is True
        assert mbid == "real-id"


class TestLookupArtistGenres:
    def test_returns_genres_sorted_by_count(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Daft Punk", "score": 100}])
        artist_data = _mock_artist_response(
            [
                {"name": "house", "count": 5},
                {"name": "electronic", "count": 20},
                {"name": "french house", "count": 10},
            ]
        )

        with patch("app.services.musicbrainz._throttled_get") as mock_get:
            mock_get.side_effect = [search_data, artist_data]
            result = lookup_artist_genres("Daft Punk")

        assert result == ["electronic", "french house", "house"]

    def test_skips_genres_without_name(self):
        search_data = _mock_search_response([{"id": "abc-123", "name": "Artist", "score": 95}])
        artist_data = _mock_artist_response(
            [
                {"name": "rock", "count": 10},
                {"name": "", "count": 5},
                {"count": 3},
            ]
        )

        with patch("app.services.musicbrainz._throttled_get") as mock_get:
            mock_get.side_effect = [search_data, artist_data]
            result = lookup_artist_genres("Artist")

        assert result == ["rock"]


class TestThrottledGet:
    def test_sends_user_agent_header(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"test": True}
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.musicbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = _throttled_get("http://example.com", {"q": "test"})

        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["headers"]["User-Agent"] == USER_AGENT
        assert result == {"test": True}

    def test_returns_none_on_http_error(self):
        with patch("app.services.musicbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.HTTPStatusError(
                "503", request=MagicMock(), response=MagicMock()
            )
            mock_client_cls.return_value = mock_client

            result = _throttled_get("http://example.com", {})

        assert result is None

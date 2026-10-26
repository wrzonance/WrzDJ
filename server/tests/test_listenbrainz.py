"""Tests for the ListenBrainz artist popularity client."""

from unittest.mock import MagicMock, patch

import httpx

from app.services.listenbrainz import fetch_artist_popularity


class TestFetchArtistPopularity:
    def test_returns_popularity_for_multiple_mbids(self):
        mock_response = [
            {
                "artist_mbid": "mbid-1",
                "total_listen_count": 5000,
                "total_user_count": 120,
            },
            {
                "artist_mbid": "mbid-2",
                "total_listen_count": 200,
                "total_user_count": 8,
            },
        ]

        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1", "mbid-2"])

        assert result == {
            "mbid-1": {"total_listen_count": 5000, "total_user_count": 120},
            "mbid-2": {"total_listen_count": 200, "total_user_count": 8},
        }

    def test_empty_input_returns_empty(self):
        result = fetch_artist_popularity([])
        assert result == {}

    def test_http_error_returns_empty(self):
        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.ConnectError("connection refused")
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1"])

        assert result == {}

    def test_malformed_response_returns_empty(self):
        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"error": "unexpected"}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1"])

        assert result == {}

    def test_partial_data_returns_available(self):
        """Only some MBIDs in response — missing ones are absent from result."""
        mock_response = [
            {
                "artist_mbid": "mbid-1",
                "total_listen_count": 5000,
                "total_user_count": 120,
            },
        ]

        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1", "mbid-missing"])

        assert "mbid-1" in result
        assert "mbid-missing" not in result

    def test_entries_without_mbid_skipped(self):
        mock_response = [
            {"total_listen_count": 100, "total_user_count": 5},
            {"artist_mbid": "mbid-1", "total_listen_count": 200, "total_user_count": 10},
        ]

        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1"])

        assert len(result) == 1
        assert "mbid-1" in result

    def test_non_dict_entries_skipped(self):
        mock_response = [
            "not-a-dict",
            {"artist_mbid": "mbid-1", "total_listen_count": 100, "total_user_count": 5},
        ]

        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1"])

        assert len(result) == 1

    def test_posts_to_the_live_popularity_endpoint(self):
        """Regression: the API path is /1/popularity/artist (singular). The plural path the
        code used returns 404, so the popularity gate silently never applied (checked live
        2026-10-26: singular 200 with this response shape, plural 404)."""
        with patch("app.services.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = []
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            fetch_artist_popularity(["mbid-1"])

        url = mock_client.post.call_args.args[0]
        assert url.endswith("/1/popularity/artist")

"""Tests for the ListenBrainz artist popularity client."""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.providers.listenbrainz import USER_AGENT as LISTENBRAINZ_USER_AGENT
from app.services.providers.listenbrainz import (
    LBRadioTrack,
    fetch_artist_popularity,
    lb_radio_discover,
)
from app.services.providers.musicbrainz import USER_AGENT as MUSICBRAINZ_USER_AGENT


def test_music_services_share_the_same_application_identity():
    expected = "WrzDJ/1.0 (https://github.com/wrzdjband/WrzDJ)"

    assert LISTENBRAINZ_USER_AGENT == expected
    assert MUSICBRAINZ_USER_AGENT == expected


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

        with patch("app.services.providers.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1", "mbid-2"])

            assert (
                mock_client.post.call_args.kwargs["headers"]["User-Agent"] == MUSICBRAINZ_USER_AGENT
            )

        assert result == {
            "mbid-1": {"total_listen_count": 5000, "total_user_count": 120},
            "mbid-2": {"total_listen_count": 200, "total_user_count": 8},
        }

    def test_empty_input_returns_empty(self):
        result = fetch_artist_popularity([])
        assert result == {}

    def test_http_error_returns_empty(self):
        with patch("app.services.providers.listenbrainz.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.ConnectError("connection refused")
            mock_client_cls.return_value = mock_client

            result = fetch_artist_popularity(["mbid-1"])

        assert result == {}

    def test_malformed_response_returns_empty(self):
        with patch("app.services.providers.listenbrainz.httpx.Client") as mock_client_cls:
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

        with patch("app.services.providers.listenbrainz.httpx.Client") as mock_client_cls:
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

        with patch("app.services.providers.listenbrainz.httpx.Client") as mock_client_cls:
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

        with patch("app.services.providers.listenbrainz.httpx.Client") as mock_client_cls:
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


class TestLBRadioDiscover:
    token = "private-listenbrainz-token"

    def _client(self, response=None, *, get_error=None):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        if get_error is not None:
            client.get.side_effect = get_error
        else:
            response.raise_for_status.return_value = None
            client.get.return_value = response
        return client

    def test_maps_valid_playlist_and_sends_authenticated_request(self):
        response = MagicMock()
        response.json.return_value = {
            "payload": {
                "jspf": {
                    "playlist": {
                        "track": [
                            {
                                "title": "Around the World",
                                "creator": "Daft Punk",
                                "identifier": ["https://musicbrainz.org/recording/recording-123"],
                            },
                            {"title": "One More Time", "creator": "Daft Punk"},
                            {"title": "Incomplete track"},
                        ]
                    }
                }
            }
        }
        client = self._client(response)

        with (
            patch("app.services.providers.listenbrainz._get_lb_token", return_value=self.token),
            patch(
                "app.services.providers.listenbrainz.httpx.Client", return_value=client
            ) as factory,
        ):
            tracks = lb_radio_discover("artist:(Daft Punk)", mode="medium")

        assert tracks == [
            LBRadioTrack("Around the World", "Daft Punk", "recording-123"),
            LBRadioTrack("One More Time", "Daft Punk"),
        ]
        factory.assert_called_once_with(timeout=15.0)
        client.get.assert_called_once_with(
            "https://api.listenbrainz.org/1/explore/lb-radio",
            params={"prompt": "artist:(Daft Punk)", "mode": "medium"},
            headers={
                "Authorization": f"Token {self.token}",
                "User-Agent": LISTENBRAINZ_USER_AGENT,
            },
        )

    def test_missing_token_skips_http_request(self):
        with (
            patch("app.services.providers.listenbrainz._get_lb_token", return_value=None),
            patch("app.services.providers.listenbrainz.httpx.Client") as client_factory,
        ):
            assert lb_radio_discover("tag:(trance)") == []

        client_factory.assert_not_called()

    def test_empty_token_skips_http_request(self):
        with (
            patch("app.services.providers.listenbrainz._get_lb_token", return_value=""),
            patch("app.services.providers.listenbrainz.httpx.Client") as client_factory,
        ):
            assert lb_radio_discover("tag:(trance)") == []

        client_factory.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            [],
            {"payload": []},
            {"payload": {"jspf": []}},
            {"payload": {"jspf": {"playlist": []}}},
            {"payload": {"jspf": {"playlist": {"track": {"title": "wrong shape"}}}}},
        ],
    )
    @patch("app.services.providers.listenbrainz._get_lb_token", return_value="configured-token")
    @patch("app.services.providers.listenbrainz.httpx.Client")
    def test_malformed_provider_shapes_return_empty(self, client_factory, _token, payload):
        # Regression: 57cfcdc6867f trusted nested provider objects and could raise.
        response = MagicMock()
        response.json.return_value = payload
        client_factory.return_value = self._client(response)

        assert lb_radio_discover("tag:(trance)") == []

    @patch("app.services.providers.listenbrainz._get_lb_token", return_value="configured-token")
    @patch("app.services.providers.listenbrainz.httpx.Client")
    def test_malformed_track_entries_are_skipped(self, client_factory, _token):
        # Regression: 57cfcdc6867f dereferenced malformed playlist entries.
        response = MagicMock()
        response.json.return_value = {
            "payload": {
                "jspf": {
                    "playlist": {
                        "track": [
                            None,
                            {"title": "Good track", "creator": "Good artist", "identifier": None},
                        ]
                    }
                }
            }
        }
        client_factory.return_value = self._client(response)

        assert lb_radio_discover("tag:(trance)") == [LBRadioTrack("Good track", "Good artist")]

    @patch("app.services.providers.listenbrainz._get_lb_token", return_value="configured-token")
    @patch("app.services.providers.listenbrainz.httpx.Client")
    def test_transport_failure_is_suppressed_without_logging_token(
        self, client_factory, _token, caplog
    ):
        client_factory.return_value = self._client(get_error=httpx.ConnectError("configured-token"))

        with caplog.at_level(logging.WARNING, logger="app.services.providers.listenbrainz"):
            assert lb_radio_discover("tag:(trance)") == []

        assert "configured-token" not in caplog.text
        assert "ConnectError" in caplog.text

    @patch("app.services.providers.listenbrainz._get_lb_token", return_value="configured-token")
    @patch("app.services.providers.listenbrainz.httpx.Client")
    def test_http_status_failure_is_suppressed_without_logging_token(
        self, client_factory, _token, caplog
    ):
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "configured-token",
            request=httpx.Request("GET", "https://api.listenbrainz.org/1/explore/lb-radio"),
            response=httpx.Response(503),
        )
        client_factory.return_value = self._client(response)

        with caplog.at_level(logging.WARNING, logger="app.services.providers.listenbrainz"):
            assert lb_radio_discover("tag:(trance)") == []

        assert "configured-token" not in caplog.text
        assert "HTTPStatusError" in caplog.text

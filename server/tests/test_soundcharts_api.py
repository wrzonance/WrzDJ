"""Soundcharts metadata, discovery, and redaction tests."""

import logging
from unittest.mock import MagicMock, patch

import httpx

from app.services.providers.soundcharts import (
    SoundchartsAudioFeatures,
    SoundchartsTrack,
    discover_songs,
    get_related_songs_by_isrc,
    get_song_features_by_isrc,
)


class TestGetSongFeaturesByIsrc:
    """Audio-features lookup by ISRC — primary energy source for #544.

    Dark by default: gated on a dedicated SOUNDCHARTS_AUDIO_FEATURES_ENABLED
    flag *and* credentials, so production keeps its Soundcharts discovery key
    while audio-features stays off until licensing is validated.
    """

    def _settings(self, *, enabled=True, app_id="test-id", api_key="test-key"):
        return MagicMock(
            soundcharts_audio_features_enabled=enabled,
            soundcharts_app_id=app_id,
            soundcharts_api_key=api_key,
        )

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_disabled_returns_none_without_calling_api(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(enabled=False)
        assert get_song_features_by_isrc("USUM71900764") is None
        mock_get.assert_not_called()

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_not_configured_returns_none(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(app_id="", api_key="")
        assert get_song_features_by_isrc("USUM71900764") is None
        mock_get.assert_not_called()

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_two_call_resolve_returns_normalized_features(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        # by-isrc returns identity (no audio) → second call fetches full metadata.
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "7d534228-5165-11e9-9375-549f35161576"}}),
            _mock_get_response({"object": _FULL_SONG_OBJECT}),
        ]

        result = get_song_features_by_isrc("USUM71900764")

        assert result == SoundchartsAudioFeatures(
            isrc="USUM71900764",
            soundcharts_uuid="7d534228-5165-11e9-9375-549f35161576",
            energy=4,  # 0.43 → 4 on the 0–10 scale
            danceability=0.7,
            valence=0.56,
            acousticness=0.33,
            instrumentalness=0.13,
            speechiness=0.38,
            liveness=0.1,
            loudness_db=-10.97,
            tempo_bpm=135.13,
            key=7,
            mode=1,
            time_signature=4,
            explicit=False,
            duration_sec=194,
            genres=("alternative", "electronic", "dance", "rock"),
        )
        assert mock_get.call_count == 2

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_single_call_when_by_isrc_includes_audio(self, mock_settings, mock_get):
        """Quota-saver: if by-isrc already carries the audio block, skip call 2."""
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": _FULL_SONG_OBJECT})

        result = get_song_features_by_isrc("USUM71900764")

        assert result is not None
        assert result.energy == 4
        assert mock_get.call_count == 1

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_invalid_json_payload_returns_none(self, mock_settings, mock_get):
        """A non-JSON payload (HTML error page, truncated body) degrades to a
        miss instead of raising and breaking the best-effort enrichment flow."""
        mock_settings.return_value = self._settings()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        mock_get.return_value = resp

        assert get_song_features_by_isrc("USUM71900764") is None
        assert mock_get.call_count == 1

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_isrc_normalized_before_request(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": _FULL_SONG_OBJECT})

        get_song_features_by_isrc("usum7-1900764")

        first_url = mock_get.call_args_list[0][0][0]
        assert first_url.endswith("/song/by-isrc/USUM71900764")

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_isrc_not_found_returns_none(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": None, "errors": ["not found"]})
        assert get_song_features_by_isrc("USUM71900764") is None

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_api_error_returns_none(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        assert get_song_features_by_isrc("USUM71900764") is None

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_missing_audio_returns_record_with_none_energy(self, mock_settings, mock_get):
        """A song with no audio analysis still yields metadata; energy is None."""
        mock_settings.return_value = self._settings()
        no_audio = {
            "uuid": "u-1",
            "isrc": {"value": "USUM71900764"},
            "duration": 200,
            "explicit": True,
            "genres": [{"root": "pop", "sub": ["pop"]}],
        }
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "u-1"}}),
            _mock_get_response({"object": no_audio}),
        ]

        result = get_song_features_by_isrc("USUM71900764")

        assert result is not None
        assert result.energy is None
        assert result.danceability is None
        assert result.explicit is True
        assert result.duration_sec == 200
        assert result.genres == ("pop",)


class TestGetRelatedSongsByIsrc:
    """Paid-tier related-tracks lookup by ISRC — candidate source for #556.

    Dark by default: gated on a dedicated SOUNDCHARTS_RELATED_TRACKS_ENABLED
    flag *and* credentials, so the discovery key stays usable in production
    while the paid related-tracks path never spends until explicitly enabled.
    """

    def _settings(self, *, enabled=True, app_id="test-id", api_key="test-key"):
        return MagicMock(
            soundcharts_related_tracks_enabled=enabled,
            soundcharts_app_id=app_id,
            soundcharts_api_key=api_key,
        )

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_disabled_returns_empty_without_calling_api(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(enabled=False)
        assert get_related_songs_by_isrc("USUM71900764") == []
        mock_get.assert_not_called()

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_not_configured_returns_empty(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(app_id="", api_key="")
        assert get_related_songs_by_isrc("USUM71900764") == []
        mock_get.assert_not_called()

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_blank_isrc_returns_empty_without_calling_api(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        assert get_related_songs_by_isrc("") == []
        assert get_related_songs_by_isrc(None) == []  # type: ignore[arg-type]
        mock_get.assert_not_called()

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_resolves_isrc_then_related(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(_RELATED_PAYLOAD_DIRECT),
        ]

        result = get_related_songs_by_isrc("USUM71900764")

        assert result == [
            SoundchartsTrack(
                title="Similar Song One", artist="Artist One", soundcharts_uuid="rel-uuid-1"
            ),
            SoundchartsTrack(
                title="Similar Song Two", artist="Artist Two", soundcharts_uuid="rel-uuid-2"
            ),
        ]
        # First call resolves ISRC, second hits the related endpoint with the UUID.
        assert mock_get.call_count == 2
        related_url = mock_get.call_args_list[1][0][0]
        assert related_url.endswith("/song/seed-uuid/related")

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_parses_nested_song_shape(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(_RELATED_PAYLOAD_NESTED),
        ]

        result = get_related_songs_by_isrc("USUM71900764")

        assert result == [
            SoundchartsTrack(
                title="Nested Song", artist="Nested Artist", soundcharts_uuid="rel-uuid-3"
            )
        ]

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_isrc_not_found_returns_empty(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": None})
        assert get_related_songs_by_isrc("USUM71900764") == []
        # Only the resolve call fires; no related call without a UUID.
        assert mock_get.call_count == 1

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_isrc_normalized_before_request(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(_RELATED_PAYLOAD_DIRECT),
        ]

        get_related_songs_by_isrc("usum7-1900764")

        first_url = mock_get.call_args_list[0][0][0]
        assert first_url.endswith("/song/by-isrc/USUM71900764")

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_api_error_returns_empty(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            httpx.ConnectError("Connection refused"),
        ]
        assert get_related_songs_by_isrc("USUM71900764") == []

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_limit_passed_as_query_param(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(_RELATED_PAYLOAD_DIRECT),
        ]

        get_related_songs_by_isrc("USUM71900764", limit=5)

        related_kwargs = mock_get.call_args_list[1].kwargs
        assert related_kwargs["params"]["limit"] == 5

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_items_missing_fields_skipped(self, mock_settings, mock_get):
        """Items lacking a name, artist, or uuid are dropped, not crashed on."""
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(
                {
                    "items": [
                        {"uuid": "ok", "name": "Good", "creditName": "Real Artist"},
                        {"uuid": "no-name", "creditName": "Artist"},
                        {"name": "No UUID", "creditName": "Artist"},
                        {"uuid": "no-artist", "name": "Orphan"},
                    ]
                }
            ),
        ]

        result = get_related_songs_by_isrc("USUM71900764")

        assert result == [
            SoundchartsTrack(title="Good", artist="Real Artist", soundcharts_uuid="ok")
        ]

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_related_http_status_error_returns_empty(self, mock_settings, mock_get):
        """A 403 (endpoint not in plan) or other HTTP status degrades to []."""
        mock_settings.return_value = self._settings()
        error_resp = MagicMock()
        error_resp.status_code = 403
        error_resp.text = "Forbidden"
        status_error = httpx.HTTPStatusError("403", request=MagicMock(), response=error_resp)
        related_resp = MagicMock()
        related_resp.raise_for_status.side_effect = status_error
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            related_resp,
        ]

        assert get_related_songs_by_isrc("USUM71900764") == []

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_related_invalid_json_returns_empty(self, mock_settings, mock_get):
        """A non-JSON related payload degrades to [] instead of raising."""
        mock_settings.return_value = self._settings()
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json.side_effect = ValueError("Expecting value")
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            bad_resp,
        ]

        assert get_related_songs_by_isrc("USUM71900764") == []

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_malformed_isrc_returns_empty_without_calling_api(self, mock_settings, mock_get):
        """A crafted ISRC (path-injection chars / wrong shape) is rejected before
        any HTTP call, so it can never be interpolated into the request URL (#556)."""
        mock_settings.return_value = self._settings()
        for bad in ("US/UM71900764", "../../secret", "USUM7190076", "not-an-isrc"):
            assert get_related_songs_by_isrc(bad) == []
        mock_get.assert_not_called()

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_non_list_items_degrades_to_empty(self, mock_settings, mock_get):
        """A malformed related payload ({"items": null}) degrades to [], not a crash."""
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response({"items": None}),
        ]
        assert get_related_songs_by_isrc("USUM71900764") == []

    @patch("app.services.providers.soundcharts.httpx.get")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_status_error_does_not_log_response_body(self, mock_settings, mock_get, caplog):
        """The auth-failure log records only the status code, never the upstream
        response body, so a leaked credential in the body can't reach the logs."""
        mock_settings.return_value = self._settings()
        error_resp = MagicMock()
        error_resp.status_code = 403
        error_resp.text = "SECRET-LEAK-CANARY-x-api-key=test-key"
        status_error = httpx.HTTPStatusError("403", request=MagicMock(), response=error_resp)
        related_resp = MagicMock()
        related_resp.raise_for_status.side_effect = status_error
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            related_resp,
        ]

        with caplog.at_level(logging.WARNING, logger="app.services.providers.soundcharts"):
            assert get_related_songs_by_isrc("USUM71900764") == []

        assert "SECRET-LEAK-CANARY" not in caplog.text
        assert "403" in caplog.text


class TestDiscoverSongs:
    @patch("app.services.providers.soundcharts.get_settings")
    def test_not_configured_returns_empty(self, mock_settings):
        mock_settings.return_value = MagicMock(soundcharts_app_id="", soundcharts_api_key="")
        result = discover_songs(genres=["Country"])
        assert result == []

    @patch("app.services.providers.soundcharts.httpx.post")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_successful_discovery(self, mock_settings, mock_post):
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "song": {
                        "uuid": "abc-123",
                        "name": "Country Roads",
                        "creditName": "John Denver",
                        "imageUrl": "https://example.com/img.jpg",
                        "releaseDate": "1971-01-01",
                    }
                },
                {
                    "song": {
                        "uuid": "def-456",
                        "name": "Jolene",
                        "creditName": "Dolly Parton",
                        "imageUrl": None,
                        "releaseDate": None,
                    }
                },
            ],
            "page": {"total": 2},
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = discover_songs(genres=["Country"], bpm_min=100, bpm_max=130)
        assert len(result) == 2
        assert result[0] == SoundchartsTrack(
            title="Country Roads",
            artist="John Denver",
            soundcharts_uuid="abc-123",
        )
        assert result[1].title == "Jolene"

    @patch("app.services.providers.soundcharts.httpx.post")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_api_error_returns_empty(self, mock_settings, mock_post):
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Access Denied"
        mock_post.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=mock_response
        )

        result = discover_songs(genres=["Country"])
        assert result == []

    @patch("app.services.providers.soundcharts.httpx.post")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_network_error_returns_empty(self, mock_settings, mock_post):
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection refused")

        result = discover_songs(genres=["Country"])
        assert result == []

    @patch("app.services.providers.soundcharts.httpx.post")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_malformed_items_skipped(self, mock_settings, mock_post):
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {"song": {"uuid": "abc", "name": None, "creditName": "Artist"}},
                {"song": {"uuid": "def", "name": "Good Song", "creditName": "Good Artist"}},
                {"song": {}},
            ],
            "page": {"total": 3},
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = discover_songs(genres=["Pop"])
        assert len(result) == 1
        assert result[0].title == "Good Song"

    @patch("app.services.providers.soundcharts.httpx.post")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_credit_name_object_extracts_name(self, mock_settings, mock_post):
        """Regression: creditName can be a dict like {"name": "Artist", "type": "main"}."""
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "song": {
                        "uuid": "abc-123",
                        "name": "Some Song",
                        "creditName": {"name": "Object Artist", "type": "main"},
                    }
                },
            ],
            "page": {"total": 1},
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = discover_songs(genres=["Pop"])
        assert len(result) == 1
        assert result[0].artist == "Object Artist"
        assert isinstance(result[0].artist, str)

    @patch("app.services.providers.soundcharts.httpx.post")
    @patch("app.services.providers.soundcharts.get_settings")
    def test_credit_name_object_without_name_skipped(self, mock_settings, mock_post):
        """creditName dict with no 'name' key should be skipped (empty string)."""
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "song": {
                        "uuid": "abc-123",
                        "name": "Some Song",
                        "creditName": {"type": "main"},
                    }
                },
            ],
            "page": {"total": 1},
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = discover_songs(genres=["Pop"])
        assert len(result) == 0  # Skipped because artist is empty


@patch("app.services.providers.soundcharts.httpx.post")
@patch("app.services.providers.soundcharts.get_settings")
def test_discovery_network_log_omits_credential_url(mock_settings, mock_post, caplog):
    mock_settings.return_value = MagicMock(soundcharts_app_id="id", soundcharts_api_key="key")
    mock_post.side_effect = httpx.ConnectError(
        "https://customer.api.soundcharts.com/?api_key=SECRET-LEAK-CANARY"
    )

    with caplog.at_level(logging.WARNING, logger="app.services.providers.soundcharts"):
        assert discover_songs(genres=["House"]) == []

    assert "SECRET-LEAK-CANARY" not in caplog.text
    assert "ConnectError" in caplog.text


@patch("app.services.providers.soundcharts.httpx.get")
@patch("app.services.providers.soundcharts.get_settings")
def test_song_lookup_network_log_omits_credential_url(mock_settings, mock_get, caplog):
    mock_settings.return_value = MagicMock(
        soundcharts_audio_features_enabled=True,
        soundcharts_app_id="id",
        soundcharts_api_key="key",
    )
    mock_get.side_effect = httpx.ConnectError(
        "https://customer.api.soundcharts.com/song?api_key=SECRET-LEAK-CANARY"
    )

    with caplog.at_level(logging.WARNING, logger="app.services.providers.soundcharts"):
        assert get_song_features_by_isrc("USUM71900764") is None

    assert "SECRET-LEAK-CANARY" not in caplog.text
    assert "ConnectError" in caplog.text


@patch("app.services.providers.soundcharts.httpx.get")
@patch("app.services.providers.soundcharts.get_settings")
def test_song_lookup_invalid_json_log_omits_response(mock_settings, mock_get, caplog):
    mock_settings.return_value = MagicMock(
        soundcharts_audio_features_enabled=True,
        soundcharts_app_id="id",
        soundcharts_api_key="key",
    )
    response = MagicMock()
    response.json.side_effect = ValueError("SECRET-LEAK-CANARY provider response")
    mock_get.return_value = response

    with caplog.at_level(logging.WARNING, logger="app.services.providers.soundcharts"):
        assert get_song_features_by_isrc("USUM71900764") is None

    assert "SECRET-LEAK-CANARY" not in caplog.text
    assert "ValueError" in caplog.text


@patch("app.services.providers.soundcharts.httpx.get")
@patch("app.services.providers.soundcharts.get_settings")
def test_related_lookup_network_log_omits_credential_url(mock_settings, mock_get, caplog):
    mock_settings.return_value = MagicMock(
        soundcharts_related_tracks_enabled=True,
        soundcharts_app_id="id",
        soundcharts_api_key="key",
    )
    seed = _mock_get_response({"object": {"uuid": "seed"}})
    mock_get.side_effect = [
        seed,
        httpx.ConnectError("https://customer.api.soundcharts.com/?api_key=SECRET-LEAK-CANARY"),
    ]

    with caplog.at_level(logging.WARNING, logger="app.services.providers.soundcharts"):
        assert get_related_songs_by_isrc("USUM71900764") == []

    assert "SECRET-LEAK-CANARY" not in caplog.text
    assert "ConnectError" in caplog.text


@patch("app.services.providers.soundcharts.httpx.get")
@patch("app.services.providers.soundcharts.get_settings")
def test_related_lookup_invalid_json_log_omits_response(mock_settings, mock_get, caplog):
    mock_settings.return_value = MagicMock(
        soundcharts_related_tracks_enabled=True,
        soundcharts_app_id="id",
        soundcharts_api_key="key",
    )
    seed = _mock_get_response({"object": {"uuid": "seed"}})
    related_response = _mock_get_response({})
    related_response.json.side_effect = ValueError("SECRET-LEAK-CANARY provider response")
    mock_get.side_effect = [seed, related_response]

    with caplog.at_level(logging.WARNING, logger="app.services.providers.soundcharts"):
        assert get_related_songs_by_isrc("USUM71900764") == []

    assert "SECRET-LEAK-CANARY" not in caplog.text
    assert "ValueError" in caplog.text


def _mock_get_response(payload: dict) -> MagicMock:
    """Build a mock httpx GET response whose .json() returns ``payload``."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# A trimmed copy of the real GET /api/v2.25/song/{uuid} payload for "bad guy".
_FULL_SONG_OBJECT = {
    "uuid": "7d534228-5165-11e9-9375-549f35161576",
    "name": "bad guy",
    "isrc": {"value": "USUM71900764", "countryCode": "US"},
    "duration": 194,
    "explicit": False,
    "genres": [
        {"root": "alternative", "sub": ["alternative"]},
        {"root": "electro", "sub": ["electronic", "dance"]},
        {"root": "rock", "sub": ["rock"]},
    ],
    "audio": {
        "acousticness": 0.33,
        "danceability": 0.7,
        "energy": 0.43,
        "instrumentalness": 0.13,
        "key": 7,
        "liveness": 0.1,
        "loudness": -10.97,
        "mode": 1,
        "speechiness": 0.38,
        "tempo": 135.13,
        "timeSignature": 4,
        "valence": 0.56,
    },
}

# A trimmed copy of a real /api/v2/song/{uuid}/related items payload. Soundcharts
# returns the related songs directly in ``items`` (each carrying uuid/name/
# creditName), so we model that shape here.
_RELATED_PAYLOAD_DIRECT = {
    "items": [
        {
            "uuid": "rel-uuid-1",
            "name": "Similar Song One",
            "creditName": "Artist One",
            "isrc": {"value": "USABC1111111"},
        },
        {
            "uuid": "rel-uuid-2",
            "name": "Similar Song Two",
            "creditName": {"name": "Artist Two"},
        },
    ],
    "page": {"offset": 0, "total": 2, "limit": 20},
}

# Some Soundcharts collection endpoints nest the object under a ``song`` key
# (the shape ``discover_songs`` parses). The adapter tolerates both.
_RELATED_PAYLOAD_NESTED = {
    "items": [
        {
            "song": {
                "uuid": "rel-uuid-3",
                "name": "Nested Song",
                "creditName": "Nested Artist",
            }
        }
    ]
}

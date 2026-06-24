"""Tests for Soundcharts API client and key conversion utilities."""

from unittest.mock import MagicMock, patch

import httpx

from app.services.soundcharts import (
    SoundchartsAudioFeatures,
    SoundchartsTrack,
    _build_request_body,
    _normalize_energy_0_10,
    discover_songs,
    get_related_songs_by_isrc,
    get_song_features_by_isrc,
    key_to_soundcharts_filter,
    pitch_class_to_key_string,
)


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


class TestKeyToSoundchartsFilter:
    def test_c_major(self):
        assert key_to_soundcharts_filter("C Major") == (0, 1)

    def test_g_major(self):
        assert key_to_soundcharts_filter("G Major") == (7, 1)

    def test_a_major(self):
        assert key_to_soundcharts_filter("A Major") == (9, 1)

    def test_d_minor(self):
        assert key_to_soundcharts_filter("D Minor") == (2, 0)

    def test_a_minor(self):
        assert key_to_soundcharts_filter("A Minor") == (9, 0)

    def test_c_minor(self):
        assert key_to_soundcharts_filter("C Minor") == (0, 0)

    def test_f_sharp_minor(self):
        assert key_to_soundcharts_filter("F# Minor") == (6, 0)

    def test_eb_major(self):
        assert key_to_soundcharts_filter("Eb Major") == (3, 1)

    def test_bare_key_defaults_major(self):
        # Bare key "Eb" defaults to Eb major via camelot.py
        assert key_to_soundcharts_filter("Eb") == (3, 1)

    def test_bare_key_f_sharp(self):
        assert key_to_soundcharts_filter("F#") == (6, 1)

    def test_camelot_code(self):
        # 8A = A minor
        assert key_to_soundcharts_filter("8A") == (9, 0)
        # 8B = C major
        assert key_to_soundcharts_filter("8B") == (0, 1)

    def test_none_returns_none(self):
        assert key_to_soundcharts_filter("") is None

    def test_invalid_returns_none(self):
        assert key_to_soundcharts_filter("not a key") is None


class TestPitchClassToKeyString:
    def test_d_minor(self):
        assert pitch_class_to_key_string(2, 0) == "D Minor"

    def test_g_major(self):
        assert pitch_class_to_key_string(7, 1) == "G Major"

    def test_c_major(self):
        assert pitch_class_to_key_string(0, 1) == "C Major"

    def test_c_minor(self):
        assert pitch_class_to_key_string(0, 0) == "C Minor"

    def test_all_pitch_classes(self):
        expected_notes = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
        for pc in range(12):
            result = pitch_class_to_key_string(pc, 1)
            assert result == f"{expected_notes[pc]} Major"
            result = pitch_class_to_key_string(pc, 0)
            assert result == f"{expected_notes[pc]} Minor"


class TestBuildRequestBody:
    def test_genre_only(self):
        body = _build_request_body(genres=["Country", "Pop"])
        filters = body["filters"]
        assert len(filters) == 1
        assert filters[0]["type"] == "songGenres"
        assert filters[0]["data"]["values"] == ["Country", "Pop"]

    def test_genre_and_bpm(self):
        body = _build_request_body(genres=["House"], bpm_min=120, bpm_max=140)
        types = {f["type"] for f in body["filters"]}
        assert "songGenres" in types
        assert "tempo" in types
        tempo = next(f for f in body["filters"] if f["type"] == "tempo")
        assert tempo["data"]["min"] == 120
        assert tempo["data"]["max"] == 140

    def test_genre_bpm_and_keys(self):
        body = _build_request_body(
            genres=["Country"],
            bpm_min=100,
            bpm_max=130,
            keys=["G Major", "D Minor"],
        )
        types = {f["type"] for f in body["filters"]}
        assert "songGenres" in types
        assert "tempo" in types
        assert "songKey" in types
        assert "songMode" in types

        key_filter = next(f for f in body["filters"] if f["type"] == "songKey")
        mode_filter = next(f for f in body["filters"] if f["type"] == "songMode")
        # G Major = pitch 7, D Minor = pitch 2
        assert sorted(key_filter["data"]["values"]) == [2, 7]
        # Major=1, Minor=0
        assert sorted(mode_filter["data"]["values"]) == [0, 1]

    def test_empty_genres(self):
        body = _build_request_body(genres=[])
        assert body["filters"] == []

    def test_invalid_keys_skipped(self):
        body = _build_request_body(genres=["Pop"], keys=["not a key", "also invalid"])
        types = {f["type"] for f in body["filters"]}
        assert "songKey" not in types
        assert "songMode" not in types

    def test_sort_defaults(self):
        body = _build_request_body(genres=["Rock"])
        assert body["sort"]["platform"] == "spotify"
        assert body["sort"]["order"] == "desc"


class TestNormalizeEnergy:
    """Soundcharts returns energy on 0.0–1.0; WrzDJ stores energy as a 0–10 int."""

    def test_midrange_value(self):
        # "bad guy" energy 0.43 → 4 (standard rounding of 4.3)
        assert _normalize_energy_0_10(0.43) == 4

    def test_rounds_half_up(self):
        assert _normalize_energy_0_10(0.55) == 6
        assert _normalize_energy_0_10(0.45) == 5

    def test_bounds(self):
        assert _normalize_energy_0_10(0.0) == 0
        assert _normalize_energy_0_10(1.0) == 10

    def test_none_passthrough(self):
        assert _normalize_energy_0_10(None) is None

    def test_clamps_out_of_range(self):
        # Defensive: a provider value outside [0,1] must still land in [0,10].
        assert _normalize_energy_0_10(1.5) == 10
        assert _normalize_energy_0_10(-0.2) == 0


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

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_disabled_returns_none_without_calling_api(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(enabled=False)
        assert get_song_features_by_isrc("USUM71900764") is None
        mock_get.assert_not_called()

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_not_configured_returns_none(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(app_id="", api_key="")
        assert get_song_features_by_isrc("USUM71900764") is None
        mock_get.assert_not_called()

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_single_call_when_by_isrc_includes_audio(self, mock_settings, mock_get):
        """Quota-saver: if by-isrc already carries the audio block, skip call 2."""
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": _FULL_SONG_OBJECT})

        result = get_song_features_by_isrc("USUM71900764")

        assert result is not None
        assert result.energy == 4
        assert mock_get.call_count == 1

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_isrc_normalized_before_request(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": _FULL_SONG_OBJECT})

        get_song_features_by_isrc("usum7-1900764")

        first_url = mock_get.call_args_list[0][0][0]
        assert first_url.endswith("/song/by-isrc/USUM71900764")

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_isrc_not_found_returns_none(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": None, "errors": ["not found"]})
        assert get_song_features_by_isrc("USUM71900764") is None

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_api_error_returns_none(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        assert get_song_features_by_isrc("USUM71900764") is None

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_disabled_returns_empty_without_calling_api(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(enabled=False)
        assert get_related_songs_by_isrc("USUM71900764") == []
        mock_get.assert_not_called()

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_not_configured_returns_empty(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings(app_id="", api_key="")
        assert get_related_songs_by_isrc("USUM71900764") == []
        mock_get.assert_not_called()

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_blank_isrc_returns_empty_without_calling_api(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        assert get_related_songs_by_isrc("") == []
        assert get_related_songs_by_isrc(None) == []  # type: ignore[arg-type]
        mock_get.assert_not_called()

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_isrc_not_found_returns_empty(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.return_value = _mock_get_response({"object": None})
        assert get_related_songs_by_isrc("USUM71900764") == []
        # Only the resolve call fires; no related call without a UUID.
        assert mock_get.call_count == 1

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_isrc_normalized_before_request(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(_RELATED_PAYLOAD_DIRECT),
        ]

        get_related_songs_by_isrc("usum7-1900764")

        first_url = mock_get.call_args_list[0][0][0]
        assert first_url.endswith("/song/by-isrc/USUM71900764")

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_api_error_returns_empty(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            httpx.ConnectError("Connection refused"),
        ]
        assert get_related_songs_by_isrc("USUM71900764") == []

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
    def test_limit_passed_as_query_param(self, mock_settings, mock_get):
        mock_settings.return_value = self._settings()
        mock_get.side_effect = [
            _mock_get_response({"object": {"uuid": "seed-uuid"}}),
            _mock_get_response(_RELATED_PAYLOAD_DIRECT),
        ]

        get_related_songs_by_isrc("USUM71900764", limit=5)

        related_kwargs = mock_get.call_args_list[1].kwargs
        assert related_kwargs["params"]["limit"] == 5

    @patch("app.services.soundcharts.httpx.get")
    @patch("app.services.soundcharts.get_settings")
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


class TestDiscoverSongs:
    @patch("app.services.soundcharts.get_settings")
    def test_not_configured_returns_empty(self, mock_settings):
        mock_settings.return_value = MagicMock(soundcharts_app_id="", soundcharts_api_key="")
        result = discover_songs(genres=["Country"])
        assert result == []

    @patch("app.services.soundcharts.httpx.post")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.post")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.post")
    @patch("app.services.soundcharts.get_settings")
    def test_network_error_returns_empty(self, mock_settings, mock_post):
        mock_settings.return_value = MagicMock(
            soundcharts_app_id="test-id",
            soundcharts_api_key="test-key",
        )
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection refused")

        result = discover_songs(genres=["Country"])
        assert result == []

    @patch("app.services.soundcharts.httpx.post")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.post")
    @patch("app.services.soundcharts.get_settings")
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

    @patch("app.services.soundcharts.httpx.post")
    @patch("app.services.soundcharts.get_settings")
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

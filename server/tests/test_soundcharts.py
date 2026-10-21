"""Soundcharts key, energy, and request normalization tests."""

from app.services.providers.soundcharts import (
    _build_request_body,
    _normalize_energy_0_10,
    key_to_soundcharts_filter,
    pitch_class_to_key_string,
)


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
        # Bare key "Eb" defaults to Eb major via shared music matching.
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

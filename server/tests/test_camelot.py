"""Tests for Camelot wheel key parsing and compatibility scoring."""

import pytest

from app.services.music_matching import (
    CamelotPosition,
    compatibility_score,
    parse_key,
)


class TestParseKey:
    """Tests for parse_key function."""

    # Standard notation: "X minor", "X major"
    @pytest.mark.parametrize(
        "key_str,expected",
        [
            ("A minor", CamelotPosition(8, "A")),
            ("C major", CamelotPosition(8, "B")),
            ("D minor", CamelotPosition(7, "A")),
            ("G major", CamelotPosition(9, "B")),
            ("F minor", CamelotPosition(4, "A")),
            ("E major", CamelotPosition(12, "B")),
            ("B major", CamelotPosition(1, "B")),
            ("F# minor", CamelotPosition(11, "A")),
            ("Bb major", CamelotPosition(6, "B")),
            ("Eb minor", CamelotPosition(2, "A")),
        ],
    )
    def test_standard_notation(self, key_str, expected):
        assert parse_key(key_str) == expected

    # Abbreviated: "Am", "Cm", "Gmaj"
    @pytest.mark.parametrize(
        "key_str,expected",
        [
            ("Am", CamelotPosition(8, "A")),
            ("Cm", CamelotPosition(5, "A")),
            ("Fm", CamelotPosition(4, "A")),
            ("Cmaj", CamelotPosition(8, "B")),
            ("Gmaj", CamelotPosition(9, "B")),
            ("F#m", CamelotPosition(11, "A")),
            ("Bbm", CamelotPosition(3, "A")),
            ("Ebm", CamelotPosition(2, "A")),
        ],
    )
    def test_abbreviated_notation(self, key_str, expected):
        assert parse_key(key_str) == expected

    # Beatport format: "C maj", "A min"
    @pytest.mark.parametrize(
        "key_str,expected",
        [
            ("C maj", CamelotPosition(8, "B")),
            ("A min", CamelotPosition(8, "A")),
            ("D min", CamelotPosition(7, "A")),
            ("F# maj", CamelotPosition(2, "B")),
            ("Bb min", CamelotPosition(3, "A")),
            ("Ab maj", CamelotPosition(4, "B")),
        ],
    )
    def test_beatport_format(self, key_str, expected):
        assert parse_key(key_str) == expected

    # Camelot codes: "8A", "12B"
    @pytest.mark.parametrize(
        "key_str,expected",
        [
            ("8A", CamelotPosition(8, "A")),
            ("8B", CamelotPosition(8, "B")),
            ("1A", CamelotPosition(1, "A")),
            ("12B", CamelotPosition(12, "B")),
            ("12A", CamelotPosition(12, "A")),
            ("1B", CamelotPosition(1, "B")),
            ("6a", CamelotPosition(6, "A")),
            ("6b", CamelotPosition(6, "B")),
        ],
    )
    def test_camelot_codes(self, key_str, expected):
        assert parse_key(key_str) == expected

    # Edge cases
    def test_none_input(self):
        assert parse_key(None) is None

    def test_empty_string(self):
        assert parse_key("") is None

    def test_whitespace_only(self):
        assert parse_key("   ") is None

    def test_unknown_key(self):
        assert parse_key("unknown") is None

    def test_gibberish(self):
        assert parse_key("xyz123") is None

    def test_leading_trailing_whitespace(self):
        assert parse_key("  A minor  ") == CamelotPosition(8, "A")

    def test_case_insensitive(self):
        assert parse_key("a MINOR") == CamelotPosition(8, "A")
        assert parse_key("C MAJOR") == CamelotPosition(8, "B")

    # Enharmonic equivalents
    def test_enharmonic_sharps_flats(self):
        # G# minor = Ab minor = 1A
        assert parse_key("G# minor") == CamelotPosition(1, "A")
        assert parse_key("Ab minor") == CamelotPosition(1, "A")
        # D# minor = Eb minor = 2A
        assert parse_key("D# minor") == CamelotPosition(2, "A")
        assert parse_key("Eb minor") == CamelotPosition(2, "A")
        # C# minor = Db minor = 12A
        assert parse_key("C# minor") == CamelotPosition(12, "A")
        assert parse_key("Db minor") == CamelotPosition(12, "A")

    # Tidal bare key formats: "Eb", "G", "CSharp", "FSharp"
    @pytest.mark.parametrize(
        "key_str,expected",
        [
            # Single letter → major
            ("C", CamelotPosition(8, "B")),
            ("G", CamelotPosition(9, "B")),
            ("D", CamelotPosition(10, "B")),
            ("A", CamelotPosition(11, "B")),
            ("E", CamelotPosition(12, "B")),
            ("B", CamelotPosition(1, "B")),
            ("F", CamelotPosition(7, "B")),
            # Letter + accidental → major
            ("Eb", CamelotPosition(5, "B")),
            ("Bb", CamelotPosition(6, "B")),
            ("Ab", CamelotPosition(4, "B")),
            ("Db", CamelotPosition(3, "B")),
            ("F#", CamelotPosition(2, "B")),
            ("C#", CamelotPosition(3, "B")),
            # Tidal "XSharp" / "XFlat" format
            ("CSharp", CamelotPosition(3, "B")),
            ("FSharp", CamelotPosition(2, "B")),
            ("GSharp", CamelotPosition(4, "B")),
            ("ASharp", CamelotPosition(6, "B")),
            ("DSharp", CamelotPosition(5, "B")),
            ("BFlat", CamelotPosition(6, "B")),
            ("EFlat", CamelotPosition(5, "B")),
            ("AFlat", CamelotPosition(4, "B")),
            ("DFlat", CamelotPosition(3, "B")),
            ("GFlat", CamelotPosition(2, "B")),
        ],
    )
    def test_tidal_bare_key_formats(self, key_str, expected):
        assert parse_key(key_str) == expected

    def test_all_12_minor_keys_parse(self):
        """Every minor key from 1A to 12A should be parseable."""
        for i in range(1, 13):
            result = parse_key(f"{i}A")
            assert result is not None
            assert result.number == i
            assert result.letter == "A"

    def test_all_12_major_keys_parse(self):
        """Every major key from 1B to 12B should be parseable."""
        for i in range(1, 13):
            result = parse_key(f"{i}B")
            assert result is not None
            assert result.number == i
            assert result.letter == "B"


class TestCompatibilityScore:
    """Tests for compatibility_score function."""

    def test_same_key_perfect_match(self):
        a = CamelotPosition(8, "A")
        assert compatibility_score(a, a) == 1.0

    def test_same_key_different_objects(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(8, "A")
        assert compatibility_score(a, b) == 1.0

    def test_adjacent_plus_one(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(9, "A")
        assert compatibility_score(a, b) == 0.8

    def test_adjacent_minus_one(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(7, "A")
        assert compatibility_score(a, b) == 0.8

    def test_parallel_key(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(8, "B")
        assert compatibility_score(a, b) == 0.8

    def test_two_away(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(10, "A")
        assert compatibility_score(a, b) == 0.5

    def test_two_away_minus(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(6, "A")
        assert compatibility_score(a, b) == 0.5

    def test_incompatible(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(3, "A")
        assert compatibility_score(a, b) == 0.0

    def test_none_first(self):
        b = CamelotPosition(8, "A")
        assert compatibility_score(None, b) == 0.0

    def test_none_second(self):
        a = CamelotPosition(8, "A")
        assert compatibility_score(a, None) == 0.0

    def test_both_none(self):
        assert compatibility_score(None, None) == 0.0

    # Wrap-around tests
    def test_wraparound_12_to_1(self):
        a = CamelotPosition(12, "A")
        b = CamelotPosition(1, "A")
        assert compatibility_score(a, b) == 0.8

    def test_wraparound_1_to_12(self):
        a = CamelotPosition(1, "A")
        b = CamelotPosition(12, "A")
        assert compatibility_score(a, b) == 0.8

    def test_wraparound_two_away_11_to_1(self):
        a = CamelotPosition(11, "A")
        b = CamelotPosition(1, "A")
        assert compatibility_score(a, b) == 0.5

    def test_wraparound_two_away_1_to_11(self):
        a = CamelotPosition(1, "A")
        b = CamelotPosition(11, "A")
        assert compatibility_score(a, b) == 0.5

    # Cross-ring (different letter, different number) = incompatible
    def test_different_ring_different_number(self):
        a = CamelotPosition(8, "A")
        b = CamelotPosition(3, "B")
        assert compatibility_score(a, b) == 0.0

    def test_major_keys_adjacent(self):
        a = CamelotPosition(5, "B")
        b = CamelotPosition(6, "B")
        assert compatibility_score(a, b) == 0.8


class TestCamelotPositionStr:
    def test_str(self):
        assert str(CamelotPosition(8, "A")) == "8A"
        assert str(CamelotPosition(12, "B")) == "12B"

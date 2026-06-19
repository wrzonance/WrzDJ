"""Tests for track normalizer — TDD style, tests written first."""

from app.services.track_normalizer import (
    NormalizedTrack,
    artist_match_score,
    fuzzy_match_score,
    is_original_mix_name,
    is_remix_title,
    normalize_artist,
    normalize_bpm_to_context,
    normalize_track,
    normalize_track_title,
    primary_artist,
    split_artists,
)


class TestNormalizeTrackTitle:
    """Tests for normalize_track_title()."""

    def test_strips_original_mix(self):
        assert normalize_track_title("Strobe (Original Mix)") == "Strobe"

    def test_strips_extended_mix(self):
        assert normalize_track_title("Strobe (Extended Mix)") == "Strobe"

    def test_strips_radio_edit(self):
        assert normalize_track_title("Strobe (Radio Edit)") == "Strobe"

    def test_strips_club_mix(self):
        assert normalize_track_title("Strobe (Club Mix)") == "Strobe"

    def test_strips_album_version(self):
        assert normalize_track_title("Strobe (Album Version)") == "Strobe"

    def test_strips_brackets(self):
        assert normalize_track_title("Strobe [Original Mix]") == "Strobe"

    def test_strips_dash_suffix(self):
        assert normalize_track_title("Strobe - Original Mix") == "Strobe"

    def test_preserves_named_remix(self):
        assert normalize_track_title("Strobe (Maceo Plex Remix)") == "Strobe (Maceo Plex Remix)"

    def test_preserves_instrumental(self):
        assert normalize_track_title("Strobe (Instrumental)") == "Strobe (Instrumental)"

    def test_preserves_acoustic(self):
        assert normalize_track_title("Strobe (Acoustic)") == "Strobe (Acoustic)"

    def test_preserves_live(self):
        assert normalize_track_title("Strobe (Live at Wembley)") == "Strobe (Live at Wembley)"

    def test_preserves_vip(self):
        assert normalize_track_title("Scary Monsters (VIP)") == "Scary Monsters (VIP)"

    def test_preserves_remaster(self):
        assert normalize_track_title("Bohemian Rhapsody (2011 Remaster)") == (
            "Bohemian Rhapsody (2011 Remaster)"
        )

    def test_plain_title_unchanged(self):
        assert normalize_track_title("Strobe") == "Strobe"

    def test_strips_feat_parenthetical(self):
        # DJ equipment / streaming metadata embeds the featured artist in the
        # title; guests rarely type it. Strip it before fuzzy matching.
        assert normalize_track_title("Get Low (ft. Ying Yang Twins)") == "Get Low"

    def test_strips_featuring_parenthetical(self):
        assert normalize_track_title("Promiscuous (feat. Timbaland)") == "Promiscuous"

    def test_strips_feat_brackets(self):
        assert normalize_track_title("Get Low [ft. Ying Yang Twins]") == "Get Low"

    def test_strips_feat_trailing(self):
        assert normalize_track_title("Get Low feat. Ying Yang Twins") == "Get Low"

    def test_feat_strip_keeps_named_remix(self):
        # Strip the feat credit but preserve a following named remix.
        assert (
            normalize_track_title("Otherside (ft. Foo) (Skrillex Remix)")
            == "Otherside (Skrillex Remix)"
        )

    def test_feat_strip_ignores_plain_with(self):
        # "with" is not a feat marker in titles — don't eat real words.
        assert normalize_track_title("Dancing With Myself") == "Dancing With Myself"


class TestNormalizeArtist:
    """Tests for normalize_artist()."""

    def test_featuring_to_feat(self):
        assert normalize_artist("deadmau5 featuring Kaskade") == "deadmau5 feat. Kaskade"

    def test_feat_already(self):
        assert normalize_artist("deadmau5 feat. Kaskade") == "deadmau5 feat. Kaskade"

    def test_ft_to_feat(self):
        assert normalize_artist("deadmau5 ft. Kaskade") == "deadmau5 feat. Kaskade"

    def test_ft_no_dot_to_feat(self):
        assert normalize_artist("deadmau5 ft Kaskade") == "deadmau5 feat. Kaskade"

    def test_with_to_feat(self):
        assert normalize_artist("deadmau5 with Kaskade") == "deadmau5 feat. Kaskade"

    def test_collapses_spaces(self):
        assert normalize_artist("deadmau5  feat.  Kaskade") == "deadmau5 feat. Kaskade"

    def test_plain_artist_unchanged(self):
        assert normalize_artist("deadmau5") == "deadmau5"


class TestFuzzyMatchScore:
    """Tests for fuzzy_match_score()."""

    def test_identical(self):
        assert fuzzy_match_score("Strobe", "Strobe") == 1.0

    def test_case_insensitive(self):
        assert fuzzy_match_score("Strobe", "strobe") == 1.0

    def test_completely_different(self):
        score = fuzzy_match_score("Strobe", "ZZZZZ")
        assert score < 0.3

    def test_similar(self):
        score = fuzzy_match_score("Strobe", "Strobee")
        assert score > 0.8


class TestNormalizeTrack:
    """Tests for normalize_track() (NormalizedTrack output)."""

    def test_plain_track(self):
        result = normalize_track("Strobe", "deadmau5")
        assert isinstance(result, NormalizedTrack)
        assert result.title == "Strobe"
        assert result.artist == "deadmau5"
        assert result.raw_title == "Strobe"
        assert result.raw_artist == "deadmau5"
        assert result.remix_artist is None
        assert result.remix_type is None
        assert result.has_named_remix is False

    def test_original_mix_stripped(self):
        result = normalize_track("Strobe (Original Mix)", "deadmau5")
        assert result.title == "Strobe"
        assert result.raw_title == "Strobe (Original Mix)"

    def test_named_remix_detected(self):
        result = normalize_track("Strobe (Maceo Plex Remix)", "deadmau5")
        assert result.remix_artist == "Maceo Plex"
        assert result.remix_type == "remix"
        assert result.has_named_remix is True

    def test_named_edit_detected(self):
        result = normalize_track("Losing It (Patrick Topping Edit)", "Fisher")
        assert result.remix_artist == "Patrick Topping"
        assert result.remix_type == "edit"
        assert result.has_named_remix is True

    def test_named_bootleg_detected(self):
        result = normalize_track("One More Time (DJ Snake Bootleg)", "Daft Punk")
        assert result.remix_artist == "DJ Snake"
        assert result.remix_type == "bootleg"
        assert result.has_named_remix is True

    def test_dash_remix_detected(self):
        result = normalize_track("Strobe - Maceo Plex Remix", "deadmau5")
        assert result.remix_artist == "Maceo Plex"
        assert result.remix_type == "remix"
        assert result.has_named_remix is True

    def test_featuring_normalized(self):
        result = normalize_track("Strobe", "deadmau5 featuring Kaskade")
        assert result.artist == "deadmau5 feat. Kaskade"
        assert result.raw_artist == "deadmau5 featuring Kaskade"

    def test_frozen_dataclass(self):
        result = normalize_track("Strobe", "deadmau5")
        try:
            result.title = "Modified"
            assert False, "Should not be able to mutate frozen dataclass"
        except AttributeError:
            pass


class TestSplitArtists:
    """Tests for split_artists()."""

    def test_single_artist(self):
        assert split_artists("Darude") == ["Darude"]

    def test_comma_separated(self):
        assert split_artists("Darude, Ashley Wallbridge, Foux") == [
            "Darude",
            "Ashley Wallbridge",
            "Foux",
        ]

    def test_ampersand(self):
        assert split_artists("Big & Rich") == ["Big", "Rich"]

    def test_and_keyword(self):
        assert split_artists("Simon and Garfunkel") == ["Simon", "Garfunkel"]

    def test_x_collab(self):
        assert split_artists("Skrillex x Diplo") == ["Skrillex", "Diplo"]

    def test_featuring(self):
        assert split_artists("deadmau5 feat. Kaskade") == ["deadmau5", "Kaskade"]

    def test_ft_no_dot(self):
        assert split_artists("Drake ft Rihanna") == ["Drake", "Rihanna"]

    def test_featuring_full(self):
        assert split_artists("Eminem featuring Rihanna") == ["Eminem", "Rihanna"]

    def test_with_keyword(self):
        assert split_artists("Calvin Harris with Rihanna") == ["Calvin Harris", "Rihanna"]

    def test_mixed_delimiters(self):
        result = split_artists("Darude, Ashley Wallbridge feat. Foux")
        assert result == ["Darude", "Ashley Wallbridge", "Foux"]

    def test_strips_whitespace(self):
        assert split_artists("  Darude ,  Tiësto  ") == ["Darude", "Tiësto"]

    def test_empty_string_returns_list(self):
        assert split_artists("") == [""]

    def test_filters_empty_segments(self):
        # Edge case: consecutive delimiters could produce empty strings
        result = split_artists("Darude, , Tiësto")
        assert "" not in result
        assert "Darude" in result
        assert "Tiësto" in result


class TestArtistMatchScore:
    """Tests for artist_match_score()."""

    def test_identical_single_artists(self):
        assert artist_match_score("Darude", "Darude") == 1.0

    def test_single_in_multi(self):
        score = artist_match_score("Darude", "Darude, Ashley Wallbridge, Foux")
        assert score >= 0.95

    def test_multi_in_single(self):
        score = artist_match_score("Darude, Ashley Wallbridge, Foux", "Darude")
        assert score >= 0.95

    def test_overlapping_multi(self):
        score = artist_match_score("Darude, Ashley Wallbridge", "Ashley Wallbridge, Foux")
        assert score >= 0.95

    def test_no_overlap(self):
        score = artist_match_score("Darude", "deadmau5")
        assert score < 0.5

    def test_case_insensitive(self):
        score = artist_match_score("DARUDE", "darude")
        assert score >= 0.95

    def test_feat_vs_comma(self):
        score = artist_match_score("Drake feat. Rihanna", "Drake, Rihanna")
        assert score >= 0.95

    def test_full_normalized_exact(self):
        score = artist_match_score("Above & Beyond", "Above & Beyond")
        assert score == 1.0


class TestPrimaryArtist:
    """Tests for primary_artist()."""

    def test_single_artist(self):
        assert primary_artist("Darude") == "Darude"

    def test_comma_separated(self):
        assert primary_artist("Darude, Ashley Wallbridge, Foux") == "Darude"

    def test_featuring(self):
        assert primary_artist("deadmau5 feat. Kaskade") == "deadmau5"

    def test_ampersand(self):
        assert primary_artist("Big & Rich") == "Big"


class TestNormalizeBpmToContext:
    """Tests for normalize_bpm_to_context()."""

    def test_half_time_corrected_up(self):
        # 66 BPM in a trance set (128-132) → should double to 132
        assert normalize_bpm_to_context(66.0, [128, 130, 126, 132]) == 132.0

    def test_double_time_corrected_down(self):
        # 260 BPM in a 130 BPM set → should halve to 130
        assert normalize_bpm_to_context(260.0, [128, 130, 126, 132]) == 130.0

    def test_already_correct_unchanged(self):
        # 128 BPM in a 128-132 set → no correction needed
        assert normalize_bpm_to_context(128.0, [128, 130, 126, 132]) == 128.0

    def test_insufficient_context_returns_raw(self):
        # < 3 context values → return raw
        assert normalize_bpm_to_context(66.0, [128, 130]) == 66.0

    def test_empty_context_returns_raw(self):
        assert normalize_bpm_to_context(66.0, []) == 66.0

    def test_ambiguous_not_corrected(self):
        # 90 BPM in a 128-ish set: doubling gives 180, halving gives 45
        # Neither is close enough to median (129) to justify correction
        assert normalize_bpm_to_context(90.0, [128, 130, 126, 132]) == 90.0

    def test_hip_hop_context(self):
        # 45 BPM in a hip-hop set (85-95) → should double to 90
        assert normalize_bpm_to_context(45.0, [85, 90, 88, 92, 95]) == 90.0

    def test_zero_bpm_returns_raw(self):
        assert normalize_bpm_to_context(0.0, [128, 130, 126]) == 0.0


class TestIsRemixTitle:
    """Tests for is_remix_title()."""

    def test_original_mix_not_remix(self):
        assert is_remix_title("Surrender (Original Mix)") is False

    def test_named_remix_detected(self):
        assert is_remix_title("Surrender (Hardstyle Remix)") is True

    def test_plain_title_not_remix(self):
        assert is_remix_title("Surrender") is False

    def test_dash_remix_detected(self):
        assert is_remix_title("Surrender - DJ Snake Remix") is True

    def test_bootleg_detected(self):
        assert is_remix_title("Strobe (DJ Snake Bootleg)") is True

    def test_edit_detected(self):
        assert is_remix_title("Losing It (Patrick Topping Edit)") is True

    def test_extended_mix_not_remix(self):
        assert is_remix_title("Strobe (Extended Mix)") is False

    def test_radio_edit_not_remix(self):
        assert is_remix_title("Strobe (Radio Edit)") is False

    def test_radio_mix_not_remix(self):
        assert is_remix_title("Strobe (Radio Mix)") is False

    def test_instrumental_mix_not_remix(self):
        assert is_remix_title("Strobe (Instrumental Mix)") is False


class TestIsOriginalMixName:
    """Tests for is_original_mix_name()."""

    def test_original_mix(self):
        assert is_original_mix_name("Original Mix") is True

    def test_extended_mix(self):
        assert is_original_mix_name("Extended Mix") is True

    def test_radio_edit(self):
        assert is_original_mix_name("Radio Edit") is True

    def test_club_mix(self):
        assert is_original_mix_name("Club Mix") is True

    def test_named_remix_not_original(self):
        assert is_original_mix_name("Hardstyle Remix") is False

    def test_arbitrary_string_not_original(self):
        assert is_original_mix_name("DJ Snake Bootleg") is False

    def test_radio_mix(self):
        assert is_original_mix_name("Radio Mix") is True

    def test_instrumental_mix(self):
        assert is_original_mix_name("Instrumental Mix") is True

    def test_strips_whitespace(self):
        assert is_original_mix_name("  Original Mix  ") is True

    def test_remastered_original_mix(self):
        assert is_original_mix_name("Remastered Original Mix") is True

    def test_original_remastered_mix(self):
        assert is_original_mix_name("Original Remastered Mix") is True

    def test_just_remastered(self):
        assert is_original_mix_name("Remastered") is False

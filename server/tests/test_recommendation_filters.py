"""Recommendation filtering and diversity tests."""

from unittest.mock import MagicMock, patch

from app.services.recommendation.deduplication import (
    deduplicate_against_requests,
)
from app.services.recommendation.service import (
    _apply_artist_diversity,
    _enforce_artist_cap,
    _filter_unverified_artists,
    _is_blocked_genre,
    _is_junk_candidate,
    _is_stock_music_artist,
)
from app.services.tracks.profile import TrackProfile
from tests.recommendation_filter_test_helpers import _make_scored
from tests.recommendation_test_helpers import (  # noqa: F401
    _make_event,
    _make_user,
    _recommendation_context,
)


class TestIsBlockedGenre:
    def test_exact_match(self):
        assert _is_blocked_genre("DJ Tools") is True
        assert _is_blocked_genre("karaoke") is True
        assert _is_blocked_genre("Stems") is True

    def test_compound_genre(self):
        assert _is_blocked_genre("DJ Tools / Acapellas") is True
        assert _is_blocked_genre("Acapellas/DJ Tools") is True

    def test_none_and_empty(self):
        assert _is_blocked_genre(None) is False
        assert _is_blocked_genre("") is False

    def test_normal_genre_passes(self):
        assert _is_blocked_genre("House") is False
        assert _is_blocked_genre("Country") is False
        assert _is_blocked_genre("Tech House") is False

    def test_meditation_genre(self):
        assert _is_blocked_genre("Meditation") is True

    def test_sleep_genre(self):
        assert _is_blocked_genre("Sleep") is True

    def test_white_noise_genre(self):
        assert _is_blocked_genre("White Noise") is True

    def test_nature_recordings_genre(self):
        assert _is_blocked_genre("Nature Recordings") is True

    def test_asmr_genre(self):
        assert _is_blocked_genre("ASMR") is True

    def test_binaural_genre(self):
        assert _is_blocked_genre("Binaural") is True

    def test_healing_genre(self):
        assert _is_blocked_genre("Healing") is True

    def test_spa_genre(self):
        assert _is_blocked_genre("Spa") is True


class TestCoverDetection:
    def test_cover_artist_filtered(self):
        """Cover version with same title but different artist is removed."""
        candidates = [
            TrackProfile(
                title="Save A Horse Ride A Cowboy",
                artist="Big",
                source="tidal",
            ),
        ]
        requests = [
            MagicMock(
                song_title="Save A Horse Ride A Cowboy",
                artist="Big & Rich",
            ),
        ]
        result = deduplicate_against_requests(candidates, requests)
        assert len(result) == 0

    def test_same_artist_not_filtered(self):
        """Same title and artist should be filtered as dupe, not cover."""
        candidates = [
            TrackProfile(title="Some Song", artist="Real Artist", source="tidal"),
        ]
        requests = [MagicMock(song_title="Some Song", artist="Real Artist")]
        result = deduplicate_against_requests(candidates, requests)
        assert len(result) == 0

    def test_different_title_and_artist_passes(self):
        """Completely different track should pass through."""
        candidates = [
            TrackProfile(title="New Song", artist="New Artist", source="tidal"),
        ]
        requests = [MagicMock(song_title="Old Song", artist="Old Artist")]
        result = deduplicate_against_requests(candidates, requests)
        assert len(result) == 1


class TestArtistDiversity:
    def test_source_artist_penalized(self):
        """Candidate matching a source artist scores lower than equal-score new artist."""
        scored = [
            _make_scored("Song A", "Luke Bryan", 0.90),
            _make_scored("Song B", "New Artist", 0.90),
        ]
        result = _apply_artist_diversity(scored, {"luke bryan"})

        # New Artist should rank first (no penalty)
        assert result[0].profile.artist == "New Artist"
        assert result[0].score == 0.90
        # Luke Bryan gets SOURCE_ARTIST_PENALTY (0.50×)
        assert result[1].profile.artist == "Luke Bryan"
        assert abs(result[1].score - 0.90 * 0.50) < 1e-9

    def test_repeat_artist_penalized(self):
        """3rd occurrence of same artist ranks below 1st."""
        scored = [
            _make_scored("Hit 1", "Luke Bryan", 0.95),
            _make_scored("Hit 2", "Luke Bryan", 0.93),
            _make_scored("Hit 3", "Luke Bryan", 0.91),
        ]
        result = _apply_artist_diversity(scored, set())

        # All three are Luke Bryan; 1st keeps score, 2nd/3rd get repetition penalty
        assert result[0].profile.title == "Hit 1"
        assert result[0].score == 0.95  # No penalty for first occurrence
        # 2nd occurrence: 0.93 * 0.75 = 0.6975
        assert result[1].profile.title == "Hit 2"
        assert abs(result[1].score - 0.93 * 0.75) < 1e-9
        # 3rd occurrence: 0.91 * 0.65 = 0.5915
        assert result[2].profile.title == "Hit 3"
        assert abs(result[2].score - 0.91 * 0.65) < 1e-9

    def test_no_penalty_for_unique_artists(self):
        """Candidates with unique artists keep original scores."""
        scored = [
            _make_scored("Song A", "Luke Bryan", 0.90),
            _make_scored("Song B", "Morgan Wallen", 0.85),
            _make_scored("Song C", "Zach Bryan", 0.80),
        ]
        result = _apply_artist_diversity(scored, set())

        assert result[0].score == 0.90
        assert result[1].score == 0.85
        assert result[2].score == 0.80

    def test_empty_source_artists(self):
        """Empty source artists set — only repetition penalty applies, no crash."""
        scored = [
            _make_scored("Song A", "Same Artist", 0.90),
            _make_scored("Song B", "Same Artist", 0.85),
        ]
        result = _apply_artist_diversity(scored, set())

        assert result[0].profile.title == "Song A"
        assert result[0].score == 0.90
        # 2nd occurrence gets repetition penalty only (0.75×)
        assert result[1].profile.title == "Song B"
        assert abs(result[1].score - 0.85 * 0.75) < 1e-9

    def test_diversity_reranks_candidates(self):
        """A lower-scoring new artist can outrank a penalized source artist."""
        scored = [
            _make_scored("Known Hit", "Luke Bryan", 0.95),
            _make_scored("Fresh Track", "New Artist", 0.80),
        ]
        # Luke Bryan is in source AND will get source penalty
        result = _apply_artist_diversity(scored, {"luke bryan"})

        # Luke Bryan: 0.95 * 0.50 = 0.475
        # New Artist: 0.80 (no penalty)
        # New Artist now ranks higher since 0.80 > 0.475
        assert result[0].profile.artist == "New Artist"
        # With a second Luke Bryan, it's even more penalized
        scored_with_repeat = [
            _make_scored("Known Hit", "Luke Bryan", 0.95),
            _make_scored("Known Hit 2", "Luke Bryan", 0.90),
            _make_scored("Fresh Track", "New Artist", 0.80),
        ]
        result2 = _apply_artist_diversity(scored_with_repeat, {"luke bryan"})
        # 1st Luke Bryan: 0.95 * 0.50 = 0.475
        # 2nd Luke Bryan: 0.90 * 0.50 (source) * 0.75 (repeat) = 0.3375
        # New Artist: 0.80 → ranks first
        assert result2[0].profile.artist == "New Artist"
        assert result2[2].profile.artist == "Luke Bryan"


class TestIsJunkCandidate:
    """Tests for _is_junk_candidate utility."""

    def test_backing_track_in_title(self):
        assert _is_junk_candidate("Save A Horse (Backing Track)", "Big & Rich") is True

    def test_drumless_in_title(self):
        assert _is_junk_candidate("Strobe - Drumless", "deadmau5") is True

    def test_jam_track_in_title(self):
        assert _is_junk_candidate("Blues Jam Track in A", "Guitar Backing") is True

    def test_click_track_in_title(self):
        assert _is_junk_candidate("Song - Click Track", "Artist") is True

    def test_practice_track_in_title(self):
        assert _is_junk_candidate("Practice Track - Tempo 120", "Music Coach") is True

    def test_minus_one_in_title(self):
        assert _is_junk_candidate("Bohemian Rhapsody Minus One", "Cover Band") is True

    def test_keyword_in_artist(self):
        assert _is_junk_candidate("Some Song", "Backing Track Masters") is True

    def test_normal_track_passes(self):
        assert _is_junk_candidate("Strobe", "deadmau5") is False

    def test_case_insensitive(self):
        assert _is_junk_candidate("BACKING TRACK version", "Artist") is True

    def test_drum_track_in_title(self):
        assert _is_junk_candidate("Funk Drum Track 120 BPM", "Drummer") is True

    def test_music_bed_in_title(self):
        assert _is_junk_candidate("Upbeat Music Bed - Corporate", "Stock Audio") is True

    def test_cinematic_music_in_title(self):
        assert _is_junk_candidate("Epic Cinematic Music", "Production Co") is True

    def test_royalty_free_in_title(self):
        assert _is_junk_candidate("Royalty Free Background", "Library") is True

    def test_meditation_music_in_title(self):
        assert _is_junk_candidate("Deep Meditation Music", "Zen") is True

    def test_stock_music_for_trailer(self):
        assert _is_junk_candidate("Trance Music for a Trailer", "Bobby Cole") is True

    def test_stock_music_for_yoga(self):
        assert _is_junk_candidate("Ambient Music for Yoga", "Relaxation Studio") is True

    def test_real_song_not_caught(self):
        assert _is_junk_candidate("Bad Guy", "Billie Eilish") is False

    # Functional/wellness music
    def test_relaxation_music(self):
        assert _is_junk_candidate("Deep Relaxation Music", "Spa") is True

    def test_healing_music(self):
        assert _is_junk_candidate("Chakra Healing Music", "Wellness") is True

    def test_yoga_music(self):
        assert _is_junk_candidate("Morning Yoga Music Flow", "Zen") is True

    def test_spa_music(self):
        assert _is_junk_candidate("Spa Music Collection", "Relax") is True

    def test_reiki_music(self):
        assert _is_junk_candidate("Reiki Music Session", "Healer") is True

    # Non-music audio content
    def test_binaural_beats(self):
        assert _is_junk_candidate("Alpha Binaural Beats 10Hz", "BrainWave") is True

    def test_white_noise(self):
        assert _is_junk_candidate("White Noise for Sleep", "Noise Co") is True

    def test_pink_noise(self):
        assert _is_junk_candidate("Pink Noise Generator", "Sleep Lab") is True

    def test_rain_sounds(self):
        assert _is_junk_candidate("Rain Sounds Thunderstorm", "Nature") is True

    def test_ocean_waves(self):
        assert _is_junk_candidate("Ocean Waves at Night", "Relaxation") is True

    def test_nature_sounds(self):
        assert _is_junk_candidate("Forest Nature Sounds", "Ambient") is True

    def test_asmr(self):
        assert _is_junk_candidate("ASMR Tapping Triggers", "WhisperASMR") is True

    def test_solfeggio(self):
        assert _is_junk_candidate("528Hz Solfeggio Frequency", "Healing") is True

    def test_isochronic(self):
        assert _is_junk_candidate("Isochronic Tones Theta", "BrainSync") is True

    # Production format terms
    def test_underscore(self):
        assert _is_junk_candidate("Corporate Underscore", "Production") is True

    def test_stinger(self):
        assert _is_junk_candidate("News Stinger Dramatic", "Stock Audio") is True

    def test_bumper(self):
        assert _is_junk_candidate("Radio Bumper Jingle", "Station ID") is True

    def test_audio_logo(self):
        assert _is_junk_candidate("Tech Audio Logo", "Branding") is True

    def test_seamless_loop(self):
        assert _is_junk_candidate("Ambient Seamless Loop", "Loop Co") is True

    # Practice/stripped track variants
    def test_play_along(self):
        assert _is_junk_candidate("Blues Play Along in E", "Guitar Lab") is True

    def test_bassless(self):
        assert _is_junk_candidate("Funk Groove Bassless", "Practice") is True

    def test_guitarless(self):
        assert _is_junk_candidate("Rock Guitarless Version", "Jam") is True

    def test_no_vocals(self):
        assert _is_junk_candidate("Pop Hit No Vocals", "Karaoke") is True

    def test_no_drums(self):
        assert _is_junk_candidate("Jazz No Drums Practice", "Band") is True


class TestEnforceArtistCap:
    """Tests for _enforce_artist_cap hard limit on tracks per artist."""

    def test_caps_at_max_per_artist(self):
        """5 tracks by the same artist → only 2 survive (MAX_PER_ARTIST=2)."""
        scored = [_make_scored(f"Hit {i}", "Luke Bryan", 0.90 - i * 0.01) for i in range(5)]
        result = _enforce_artist_cap(scored, max_per_artist=2)
        assert len(result) == 2
        assert result[0].profile.title == "Hit 0"
        assert result[1].profile.title == "Hit 1"

    def test_fuzzy_artist_matching(self):
        """Slight name variations are treated as the same artist."""
        scored = [
            _make_scored("Song A", "deadmau5", 0.90),
            _make_scored("Song B", "Deadmau5", 0.85),
            _make_scored("Song C", "deadmau5", 0.80),
        ]
        result = _enforce_artist_cap(scored, max_per_artist=2)
        assert len(result) == 2

    def test_preserves_score_ordering(self):
        """Higher-scoring tracks from the same artist are kept."""
        scored = [
            _make_scored("Best", "Artist X", 0.95),
            _make_scored("Good", "Artist X", 0.80),
            _make_scored("Okay", "Artist X", 0.70),
        ]
        result = _enforce_artist_cap(scored, max_per_artist=2)
        assert result[0].profile.title == "Best"
        assert result[1].profile.title == "Good"

    def test_empty_input(self):
        result = _enforce_artist_cap([], max_per_artist=2)
        assert result == []

    def test_all_unique_artists_pass(self):
        """When all artists are unique, nothing is filtered."""
        scored = [
            _make_scored("Song A", "deadmau5", 0.90),
            _make_scored("Song B", "Zedd", 0.85),
            _make_scored("Song C", "Tiësto", 0.80),
        ]
        result = _enforce_artist_cap(scored, max_per_artist=2)
        assert len(result) == 3

    def test_none_artist_not_capped(self):
        """Tracks with no artist are always allowed through."""
        scored = [_make_scored(f"Track {i}", None, 0.90 - i * 0.01) for i in range(5)]
        result = _enforce_artist_cap(scored, max_per_artist=2)
        assert len(result) == 5

    def test_mixed_artists_with_cap(self):
        """Multiple artists, some exceeding cap, some not."""
        scored = [
            _make_scored("LB 1", "Luke Bryan", 0.95),
            _make_scored("MW 1", "Morgan Wallen", 0.93),
            _make_scored("LB 2", "Luke Bryan", 0.91),
            _make_scored("MW 2", "Morgan Wallen", 0.89),
            _make_scored("LB 3", "Luke Bryan", 0.87),  # Should be capped
            _make_scored("MW 3", "Morgan Wallen", 0.85),  # Should be capped
            _make_scored("New 1", "New Artist", 0.83),
        ]
        result = _enforce_artist_cap(scored, max_per_artist=2)
        artists = [r.profile.artist for r in result]
        assert artists.count("Luke Bryan") == 2
        assert artists.count("Morgan Wallen") == 2
        assert artists.count("New Artist") == 1
        assert len(result) == 5


class TestIsStockMusicArtist:
    """Tests for _is_stock_music_artist filter."""

    def test_catches_music_zone_suffix(self):
        assert _is_stock_music_artist("Ibiza Chill Out Music Zone") is True

    def test_catches_music_bed_suffix(self):
        assert _is_stock_music_artist("Ambient Music Bed") is True

    def test_catches_music_group_suffix(self):
        assert _is_stock_music_artist("Relaxation Music Group") is True

    def test_catches_brainrot_keyword(self):
        assert _is_stock_music_artist("Brainrot Italiano Music") is True
        assert _is_stock_music_artist("bombombini gusini brainrot") is True

    def test_catches_royalty_free_keyword(self):
        assert _is_stock_music_artist("Royalty Free Music Co") is True
        assert _is_stock_music_artist("Royalty-Free Beats") is True

    def test_passes_real_artists(self):
        assert _is_stock_music_artist("deadmau5") is False
        assert _is_stock_music_artist("Field Music") is False
        assert _is_stock_music_artist("Florence and the Machine") is False

    def test_catches_beats_suffix(self):
        assert _is_stock_music_artist("Chill Lo-Fi Beats") is True

    def test_catches_sounds_suffix(self):
        assert _is_stock_music_artist("Relaxing Nature Sounds") is True

    def test_catches_music_ensemble_suffix(self):
        assert _is_stock_music_artist("Calm Piano Music Ensemble") is True

    def test_catches_relax_club_suffix(self):
        assert _is_stock_music_artist("Deep Sleep Relax Club") is True

    def test_catches_music_therapy_suffix(self):
        assert _is_stock_music_artist("Healing Waves Music Therapy") is True

    def test_catches_sound_effects_suffix(self):
        assert _is_stock_music_artist("Nature Sound Effects") is True

    def test_catches_noise_machine_suffix(self):
        assert _is_stock_music_artist("White Noise Machine") is True

    def test_catches_relaxation_suffix(self):
        assert _is_stock_music_artist("Deep Relaxation") is True

    def test_catches_meditation_suffix(self):
        assert _is_stock_music_artist("Guided Meditation") is True

    def test_catches_sleep_music_suffix(self):
        assert _is_stock_music_artist("Baby Sleep Music") is True

    def test_catches_white_noise_for_keyword(self):
        assert _is_stock_music_artist("White Noise for Babies") is True

    def test_catches_sleep_sound_keyword(self):
        assert _is_stock_music_artist("Sleep Sound Lab") is True

    def test_catches_rain_sounds_keyword(self):
        assert _is_stock_music_artist("Rain Sounds Studio") is True

    def test_catches_nature_sounds_keyword(self):
        assert _is_stock_music_artist("Nature Sounds Orchestra") is True

    def test_catches_lofi_sleep_keyword(self):
        assert _is_stock_music_artist("Lofi Sleep Chill") is True

    def test_catches_study_music_keyword(self):
        assert _is_stock_music_artist("Study Music Project") is True

    def test_catches_audio_suffix(self):
        assert _is_stock_music_artist("Corporate Background Audio") is True

    def test_catches_productions_suffix(self):
        assert _is_stock_music_artist("Ambient Sleep Productions") is True

    def test_real_artists_with_similar_names_pass(self):
        # These real artists should NOT be caught by the new suffixes
        assert _is_stock_music_artist("Roxy Music") is False
        assert _is_stock_music_artist("Field Music") is False
        assert _is_stock_music_artist("The Crystal Method") is False

    def test_case_insensitive(self):
        assert _is_stock_music_artist("BRAINROT BEATS") is True
        assert _is_stock_music_artist("ibiza chill out music zone") is True


class TestFilterUnverifiedArtists:
    """Tests for _filter_unverified_artists."""

    def test_removes_unverified_keeps_verified(self):
        scored = [
            _make_scored("Real Song", "deadmau5", 0.90),
            _make_scored("Fake Song", "Electrofab Music", 0.85),
        ]
        db = MagicMock()

        with patch(
            "app.services.recommendation.mb_verify.verify_artists_batch",
            return_value={"deadmau5": True, "Electrofab Music": False},
        ) as mock_verify:
            filtered, mb_verified = _filter_unverified_artists(db, scored)

        assert len(filtered) == 1
        assert filtered[0].profile.artist == "deadmau5"
        assert mb_verified["deadmau5"] is True
        assert mb_verified["Electrofab Music"] is False
        mock_verify.assert_called_once()

    def test_keeps_tracks_with_no_artist(self):
        scored = [
            _make_scored("Instrumental", None, 0.80),
            _make_scored("Fake Song", "Stock Music", 0.75),
        ]
        db = MagicMock()

        with patch(
            "app.services.recommendation.mb_verify.verify_artists_batch",
            return_value={"Stock Music": False},
        ):
            filtered, mb_verified = _filter_unverified_artists(db, scored)

        assert len(filtered) == 1
        assert filtered[0].profile.title == "Instrumental"

    def test_empty_list(self):
        db = MagicMock()
        filtered, mb_verified = _filter_unverified_artists(db, [])
        assert filtered == []
        assert mb_verified == {}

    def test_all_verified(self):
        scored = [
            _make_scored("Song A", "Artist A", 0.90),
            _make_scored("Song B", "Artist B", 0.85),
        ]
        db = MagicMock()

        with patch(
            "app.services.recommendation.mb_verify.verify_artists_batch",
            return_value={"Artist A": True, "Artist B": True},
        ):
            filtered, mb_verified = _filter_unverified_artists(db, scored)

        assert len(filtered) == 2

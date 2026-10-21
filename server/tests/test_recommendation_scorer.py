"""Tests for BPM/key/genre scoring algorithm."""

import pytest

from app.services.music_matching import (
    FAMILY_AFFINITY,
    GENRE_FAMILIES,
    score_bpm,
    score_genre,
)
from app.services.recommendation.scorer import (
    EventProfile,
    ScoredTrack,
    build_event_profile,
    rank_candidates,
    score_candidate,
)
from app.services.tracks.profile import TrackProfile


class TestBuildEventProfile:
    def test_empty_tracks(self):
        profile = build_event_profile([])
        assert profile.track_count == 0
        assert profile.avg_bpm is None
        assert profile.bpm_range is None
        assert list(profile.dominant_keys) == []
        assert list(profile.dominant_genres) == []

    def test_single_track(self):
        tracks = [TrackProfile(title="Track", artist="Artist", bpm=128.0, key="8A", genre="House")]
        profile = build_event_profile(tracks)
        assert profile.track_count == 1
        assert profile.avg_bpm == 128.0
        assert profile.bpm_range == (128.0, 128.0)
        assert list(profile.dominant_keys) == ["8A"]
        assert list(profile.dominant_genres) == ["House"]

    def test_multiple_tracks_avg_bpm(self):
        tracks = [
            TrackProfile(title="T1", artist="A", bpm=120.0),
            TrackProfile(title="T2", artist="A", bpm=130.0),
            TrackProfile(title="T3", artist="A", bpm=140.0),
        ]
        profile = build_event_profile(tracks)
        assert profile.avg_bpm == pytest.approx(130.0)
        assert profile.bpm_range == (120.0, 140.0)

    def test_bpm_range(self):
        tracks = [
            TrackProfile(title="T1", artist="A", bpm=100.0),
            TrackProfile(title="T2", artist="A", bpm=150.0),
        ]
        profile = build_event_profile(tracks)
        assert profile.bpm_range == (100.0, 150.0)

    def test_all_none_bpms(self):
        tracks = [
            TrackProfile(title="T1", artist="A"),
            TrackProfile(title="T2", artist="A"),
        ]
        profile = build_event_profile(tracks)
        assert profile.avg_bpm is None
        assert profile.bpm_range is None
        assert profile.track_count == 2

    def test_dominant_keys(self):
        tracks = [
            TrackProfile(title="T1", artist="A", key="8A"),
            TrackProfile(title="T2", artist="A", key="8A"),
            TrackProfile(title="T3", artist="A", key="9A"),
            TrackProfile(title="T4", artist="A", key="7A"),
            TrackProfile(title="T5", artist="A", key="8A"),
        ]
        profile = build_event_profile(tracks)
        # 8A appears 3 times, should be first
        assert profile.dominant_keys[0] == "8A"
        assert len(profile.dominant_keys) <= 3

    def test_dominant_genres(self):
        tracks = [
            TrackProfile(title="T1", artist="A", genre="Tech House"),
            TrackProfile(title="T2", artist="A", genre="Tech House"),
            TrackProfile(title="T3", artist="A", genre="Progressive House"),
            TrackProfile(title="T4", artist="A", genre="Tech House"),
        ]
        profile = build_event_profile(tracks)
        assert profile.dominant_genres[0] == "Tech House"

    def test_max_three_dominant(self):
        tracks = [
            TrackProfile(title="T1", artist="A", genre="A"),
            TrackProfile(title="T2", artist="A", genre="B"),
            TrackProfile(title="T3", artist="A", genre="C"),
            TrackProfile(title="T4", artist="A", genre="D"),
        ]
        profile = build_event_profile(tracks)
        assert len(profile.dominant_genres) == 3


class TestScoreCandidate:
    def _make_profile(self, **kwargs):
        defaults = {
            "avg_bpm": 128.0,
            "bpm_range": (120.0, 136.0),
            "dominant_keys": ["8A"],
            "dominant_genres": ["Tech House"],
            "track_count": 5,
        }
        defaults.update(kwargs)
        return EventProfile(**defaults)

    def test_perfect_match(self):
        """Candidate matching all criteria should score high."""
        profile = self._make_profile()
        candidate = TrackProfile(
            title="Track", artist="Artist", bpm=128.0, key="8A", genre="Tech House"
        )
        scored = score_candidate(candidate, profile)
        assert scored.bpm_score == 1.0
        assert scored.key_score == 1.0
        assert scored.genre_score == 1.0
        assert scored.score == pytest.approx(1.0)

    def test_bpm_in_range(self):
        profile = self._make_profile()
        candidate = TrackProfile(title="T", artist="A", bpm=129.0)
        scored = score_candidate(candidate, profile)
        assert scored.bpm_score == 1.0  # Within +/-2

    def test_bpm_out_of_range(self):
        profile = self._make_profile()
        candidate = TrackProfile(title="T", artist="A", bpm=160.0)
        scored = score_candidate(candidate, profile)
        assert scored.bpm_score == 0.0  # More than 20 away

    def test_bpm_moderate_falloff(self):
        profile = self._make_profile()
        candidate = TrackProfile(title="T", artist="A", bpm=138.0)
        scored = score_candidate(candidate, profile)
        # diff=10, falloff = 1.0 - (10-2)/18 = 1.0 - 8/18 ≈ 0.5556
        assert 0.5 < scored.bpm_score < 0.6

    def test_bpm_missing_candidate(self):
        profile = self._make_profile()
        candidate = TrackProfile(title="T", artist="A", bpm=None)
        scored = score_candidate(candidate, profile)
        assert scored.bpm_score == 0.5

    def test_bpm_half_time_compatible(self):
        """140 BPM DnB event + 70 BPM hip-hop candidate = half-time match."""
        profile = self._make_profile(avg_bpm=140.0)
        candidate = TrackProfile(title="T", artist="A", bpm=70.0)
        scored = score_candidate(candidate, profile)
        # Half-time exact match: base=1.0 * 0.7 = 0.7
        assert scored.bpm_score == 0.7

    def test_bpm_double_time_compatible(self):
        """70 BPM hip-hop event + 140 BPM DnB candidate = double-time match."""
        profile = self._make_profile(avg_bpm=70.0)
        candidate = TrackProfile(title="T", artist="A", bpm=140.0)
        scored = score_candidate(candidate, profile)
        assert scored.bpm_score == 0.7

    def test_bpm_half_time_near_match(self):
        """Half-time within +/-2 BPM should still score well."""
        profile = self._make_profile(avg_bpm=140.0)
        candidate = TrackProfile(title="T", artist="A", bpm=71.0)
        scored = score_candidate(candidate, profile)
        # diff from half = |71 - 70| = 1.0 (within 2), base=1.0 * 0.7 = 0.7
        assert scored.bpm_score == 0.7

    def test_bpm_direct_match_preferred_over_half(self):
        """Direct BPM match should score higher than half-time match."""
        profile = self._make_profile(avg_bpm=128.0)
        direct = TrackProfile(title="T", artist="A", bpm=128.0)
        half = TrackProfile(title="T", artist="A", bpm=64.0)
        direct_scored = score_candidate(direct, profile)
        half_scored = score_candidate(half, profile)
        assert direct_scored.bpm_score > half_scored.bpm_score

    def test_key_compatible(self):
        profile = self._make_profile(dominant_keys=["8A"])
        candidate = TrackProfile(title="T", artist="A", key="9A")  # Adjacent
        scored = score_candidate(candidate, profile)
        assert scored.key_score == 0.8

    def test_key_incompatible(self):
        profile = self._make_profile(dominant_keys=["8A"])
        candidate = TrackProfile(title="T", artist="A", key="3B")
        scored = score_candidate(candidate, profile)
        assert scored.key_score == 0.0

    def test_key_missing(self):
        profile = self._make_profile(dominant_keys=["8A"])
        candidate = TrackProfile(title="T", artist="A", key=None)
        scored = score_candidate(candidate, profile)
        assert scored.key_score == 0.5

    def test_genre_exact_match(self):
        profile = self._make_profile(dominant_genres=["Tech House"])
        candidate = TrackProfile(title="T", artist="A", genre="Tech House")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 1.0

    def test_genre_partial_match(self):
        profile = self._make_profile(dominant_genres=["Progressive House"])
        candidate = TrackProfile(title="T", artist="A", genre="House")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.5

    def test_genre_mismatch_unrelated(self):
        """Completely unrelated genres with no family mapping should score 0.0."""
        profile = self._make_profile(dominant_genres=["Country"])
        candidate = TrackProfile(title="T", artist="A", genre="Techno")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.0

    def test_genre_missing(self):
        profile = self._make_profile(dominant_genres=["House"])
        candidate = TrackProfile(title="T", artist="A", genre=None)
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.25

    def test_genre_same_family(self):
        """Deep House vs Tech House should score 0.4 (same house family)."""
        profile = self._make_profile(dominant_genres=["Deep House"])
        candidate = TrackProfile(title="T", artist="A", genre="Tech House")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.4

    def test_genre_family_affinity(self):
        """House vs Techno should score 0.4 (cross-family affinity)."""
        profile = self._make_profile(dominant_genres=["House"])
        candidate = TrackProfile(title="T", artist="A", genre="Techno")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.4

    def test_genre_hip_hop_pop_affinity(self):
        """Hip Hop vs Pop should score 0.3 (cross-family affinity)."""
        profile = self._make_profile(dominant_genres=["Hip Hop"])
        candidate = TrackProfile(title="T", artist="A", genre="Pop")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.3

    def test_genre_progressive_house_vs_techno(self):
        """Progressive House vs Techno: different families but house-techno affinity."""
        profile = self._make_profile(dominant_genres=["Progressive House"])
        candidate = TrackProfile(title="T", artist="A", genre="Melodic Techno")
        scored = score_candidate(candidate, profile)
        # Both are in known families (house, techno), affinity = 0.4
        assert scored.genre_score == 0.4

    def test_genre_substring_takes_priority_over_family(self):
        """Substring match (0.5) should beat family match (0.4)."""
        profile = self._make_profile(dominant_genres=["Progressive House"])
        candidate = TrackProfile(title="T", artist="A", genre="House")
        scored = score_candidate(candidate, profile)
        assert scored.genre_score == 0.5  # substring, not family

    def test_no_genre_data_weights_redistribute(self):
        """When event has no genre data, weights should be BPM 0.5, key 0.5."""
        profile = self._make_profile(dominant_genres=[])
        candidate = TrackProfile(title="T", artist="A", bpm=128.0, key="8A")
        scored = score_candidate(candidate, profile)
        # BPM=1.0 * 0.5 + Key=1.0 * 0.5 + Genre=0.25*0.0 = 1.0
        assert scored.score == pytest.approx(1.0)


class TestRankCandidates:
    def _make_profile(self):
        return EventProfile(
            avg_bpm=128.0,
            bpm_range=(120.0, 136.0),
            dominant_keys=["8A"],
            dominant_genres=["Tech House"],
            track_count=5,
        )

    def test_correct_ordering(self):
        profile = self._make_profile()
        candidates = [
            TrackProfile(title="Bad", artist="A", bpm=200.0, key="3B", genre="Hip Hop"),
            TrackProfile(title="Perfect", artist="A", bpm=128.0, key="8A", genre="Tech House"),
            TrackProfile(title="OK", artist="A", bpm=130.0, key="9A", genre="House"),
        ]
        ranked = rank_candidates(candidates, profile)
        assert ranked[0].profile.title == "Perfect"
        assert ranked[-1].profile.title == "Bad"

    def test_max_results_cap(self):
        profile = self._make_profile()
        candidates = [TrackProfile(title=f"T{i}", artist="A", bpm=128.0) for i in range(50)]
        ranked = rank_candidates(candidates, profile, max_results=10)
        assert len(ranked) == 10

    def test_empty_candidates(self):
        profile = self._make_profile()
        ranked = rank_candidates([], profile)
        assert ranked == []

    def test_returns_scored_tracks(self):
        profile = self._make_profile()
        candidates = [TrackProfile(title="T", artist="A", bpm=128.0)]
        ranked = rank_candidates(candidates, profile)
        assert len(ranked) == 1
        assert isinstance(ranked[0], ScoredTrack)
        assert ranked[0].profile.title == "T"


class TestScoreBpmFunction:
    """Direct tests for score_bpm half/double-time behavior."""

    def test_exact_match(self):
        assert score_bpm(128.0, 128.0) == 1.0

    def test_none_candidate(self):
        assert score_bpm(None, 128.0) == 0.5

    def test_none_avg(self):
        assert score_bpm(128.0, None) == 0.5

    def test_half_time_exact(self):
        # 64 is exactly half of 128
        assert score_bpm(64.0, 128.0) == 0.7

    def test_double_time_exact(self):
        # 256 is exactly double of 128
        assert score_bpm(256.0, 128.0) == 0.7

    def test_half_time_near(self):
        # 65 is 1 away from half (64), within tolerance
        result = score_bpm(65.0, 128.0)
        assert result == 0.7

    def test_half_time_far(self):
        # 50 is 14 away from half (64), should get reduced score
        result = score_bpm(50.0, 128.0)
        # effective_diff = 14, base = 1 - (14-2)/18 = 0.333, * 0.7 = 0.233
        assert 0.2 < result < 0.3

    def test_neither_half_nor_double_nor_direct(self):
        # 100 vs avg 128: diff=28, half_diff=|100-64|=36, double_diff=|100-256|=156
        # Direct diff is best but >20, so score = 0.0
        assert score_bpm(100.0, 128.0) == 0.0


class TestScoreGenreFunction:
    """Direct tests for score_genre with family hierarchy."""

    def test_exact_match(self):
        assert score_genre("House", ["House"]) == 1.0

    def test_case_insensitive_exact(self):
        assert score_genre("house", ["House"]) == 1.0

    def test_substring_match(self):
        assert score_genre("House", ["Deep House"]) == 0.5

    def test_same_family(self):
        assert score_genre("Deep House", ["Tech House"]) == 0.4

    def test_cross_family_affinity(self):
        assert score_genre("Techno", ["House"]) == 0.4

    def test_no_relation(self):
        assert score_genre("Country", ["Techno"]) == 0.0

    def test_missing_candidate(self):
        assert score_genre(None, ["House"]) == 0.25

    def test_missing_dominant(self):
        assert score_genre("House", []) == 0.25

    def test_unknown_genre_not_in_families(self):
        assert score_genre("Polka", ["Jazz"]) == 0.0

    def test_genre_families_dict_has_expected_families(self):
        families = set(GENRE_FAMILIES.values())
        assert "house" in families
        assert "techno" in families
        assert "hip-hop" in families
        assert "country" in families

    def test_family_affinity_symmetric(self):
        """Affinity pairs should be sorted tuples, so lookup works both ways."""
        for pair in FAMILY_AFFINITY:
            assert pair == tuple(sorted(pair)), f"Pair {pair} is not sorted"

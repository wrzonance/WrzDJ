"""Tests for recommendation engine orchestrator."""

from unittest.mock import MagicMock, patch

from app.services.recommendation.deduplication import (
    deduplicate_against_requests,
    deduplicate_against_template,
    deduplicate_candidates,
)
from app.services.recommendation.llm_hooks import LLMSuggestionQuery
from app.services.recommendation.query_builder import build_beatport_queries, build_tidal_queries
from app.services.recommendation.scorer import EventProfile, TrackProfile
from app.services.recommendation.service import (
    RecommendationResult,
    _apply_artist_diversity,
    _build_llm_scoring_profile,
    _enforce_artist_cap,
    _filter_unverified_artists,
    _is_blocked_genre,
    _is_junk_candidate,
    _is_stock_music_artist,
    _search_candidates,
    generate_recommendations,
)


def _make_user(tidal=True, beatport=True):
    user = MagicMock()
    user.tidal_access_token = "tok" if tidal else None
    user.beatport_access_token = "tok" if beatport else None
    return user


def _make_event(code="TEST1"):
    event = MagicMock()
    event.id = 1
    event.code = code
    return event


class TestBuildBeatportQueries:
    def test_genre_based_queries(self):
        profile = EventProfile(
            dominant_genres=["Tech House", "Progressive House", "Minimal"],
            track_count=10,
        )
        queries = build_beatport_queries(profile)
        assert "Tech House" in queries
        assert "Progressive House" in queries
        assert "Minimal" in queries

    def test_bpm_query_added(self):
        profile = EventProfile(
            avg_bpm=128.0,
            dominant_genres=["House"],
            track_count=5,
        )
        queries = build_beatport_queries(profile)
        assert any("128" in q for q in queries)

    def test_empty_profile(self):
        profile = EventProfile(track_count=0)
        queries = build_beatport_queries(profile)
        assert queries == []

    def test_max_three_queries(self):
        profile = EventProfile(
            avg_bpm=128.0,
            dominant_genres=["A", "B", "C"],
            track_count=10,
        )
        queries = build_beatport_queries(profile)
        assert len(queries) <= 3

    def test_artist_fallback_when_no_genres(self):
        """When no genres available, use top artists from template tracks."""
        profile = EventProfile(avg_bpm=128.0, track_count=5)
        template_tracks = [
            TrackProfile(title="Song 1", artist="deadmau5", bpm=128.0),
            TrackProfile(title="Song 2", artist="deadmau5", bpm=130.0),
            TrackProfile(title="Song 3", artist="Boris Brejcha", bpm=126.0),
            TrackProfile(title="Song 4", artist="Stephan Bodzin", bpm=125.0),
            TrackProfile(title="Song 5", artist="deadmau5", bpm=132.0),
        ]
        queries = build_beatport_queries(profile, template_tracks=template_tracks)
        assert len(queries) >= 1
        # deadmau5 appears most, should be first
        assert queries[0] == "deadmau5"
        assert "Boris Brejcha" in queries or "Stephan Bodzin" in queries

    def test_artist_fallback_skips_unknown(self):
        """Unknown and Various Artists should not be used as queries."""
        profile = EventProfile(avg_bpm=120.0, track_count=3)
        template_tracks = [
            TrackProfile(title="Song 1", artist="Unknown"),
            TrackProfile(title="Song 2", artist="Various Artists"),
            TrackProfile(title="Song 3", artist="Real Artist", bpm=120.0),
        ]
        queries = build_beatport_queries(profile, template_tracks=template_tracks)
        assert "Unknown" not in queries
        assert "Various Artists" not in queries
        assert "Real Artist" in queries

    def test_genres_preferred_over_artists(self):
        """When genres exist, use them instead of artist fallback."""
        profile = EventProfile(dominant_genres=["Tech House"], avg_bpm=128.0, track_count=5)
        template_tracks = [
            TrackProfile(title="Song", artist="deadmau5", genre="Tech House"),
        ]
        queries = build_beatport_queries(profile, template_tracks=template_tracks)
        assert "Tech House" in queries
        # Artist shouldn't be in queries when genres are available
        assert "deadmau5" not in queries

    def test_no_bpm_only_fallback_without_genres(self):
        """BPM-only query should NOT be generated when there are no genres."""
        profile = EventProfile(avg_bpm=128.0, track_count=5)
        queries = build_beatport_queries(profile)
        # Without genres or template tracks, should return empty
        assert queries == []


class TestBuildTidalQueries:
    def test_artist_from_requests(self):
        """Top artist gets 1 slot; remaining slots use genre discovery."""
        profile = EventProfile(
            dominant_genres=["Country", "Pop"],
            track_count=5,
        )
        requests = [
            MagicMock(artist="Luke Bryan"),
            MagicMock(artist="Luke Bryan"),
            MagicMock(artist="Morgan Wallen"),
        ]
        queries = build_tidal_queries(profile, requests=requests)
        # Top artist gets slot 1
        assert queries[0] == "Luke Bryan"
        # Remaining slots filled with genre discovery, not more queue artists
        assert any("Country" in q for q in queries[1:])
        assert len(queries) <= 3

    def test_artist_from_template_tracks(self):
        """Top template artist gets slot 1; genre fills remaining slots."""
        profile = EventProfile(dominant_genres=["House"], track_count=3)
        template_tracks = [
            TrackProfile(title="Song 1", artist="deadmau5", bpm=128.0),
            TrackProfile(title="Song 2", artist="deadmau5", bpm=130.0),
            TrackProfile(title="Song 3", artist="Zedd", bpm=126.0),
        ]
        queries = build_tidal_queries(profile, template_tracks=template_tracks)
        assert queries[0] == "deadmau5"  # Most frequent first
        # Slot 2 should be genre discovery, not another queue artist
        assert any("House" in q for q in queries[1:])

    def test_skips_unknown_artists(self):
        profile = EventProfile(track_count=2)
        requests = [
            MagicMock(artist="Unknown"),
            MagicMock(artist="Various Artists"),
            MagicMock(artist="Real Artist"),
        ]
        queries = build_tidal_queries(profile, requests=requests)
        assert "Unknown" not in queries
        assert "Various Artists" not in queries
        assert "Real Artist" in queries

    def test_empty_sources(self):
        profile = EventProfile(track_count=0)
        queries = build_tidal_queries(profile)
        assert queries == []

    def test_max_three_queries(self):
        profile = EventProfile(track_count=5)
        requests = [MagicMock(artist=f"Artist {i}") for i in range(10)]
        queries = build_tidal_queries(profile, requests=requests)
        assert len(queries) <= 3

    def test_combines_requests_and_template(self):
        """Artists from both requests and templates contribute to artist pool."""
        profile = EventProfile(track_count=3)
        requests = [MagicMock(artist="Artist A")]
        template_tracks = [
            TrackProfile(title="Song", artist="Artist B", bpm=128.0),
        ]
        queries = build_tidal_queries(profile, requests=requests, template_tracks=template_tracks)
        # Top artist gets slot 1; remaining artist fills fallback slot (no genres)
        assert "Artist A" in queries or "Artist B" in queries
        assert len(queries) <= 3


class TestDeduplicateAgainstTemplate:
    def test_removes_template_tracks(self):
        candidates = [
            TrackProfile(title="Strobe", artist="deadmau5", source="beatport"),
            TrackProfile(title="New Track", artist="New Artist", source="beatport"),
        ]
        template = [
            TrackProfile(title="Strobe", artist="deadmau5", source="tidal"),
        ]
        result = deduplicate_against_template(candidates, template)
        assert len(result) == 1
        assert result[0].title == "New Track"

    def test_empty_template(self):
        candidates = [TrackProfile(title="Track", artist="Artist")]
        result = deduplicate_against_template(candidates, [])
        assert len(result) == 1


class TestDeduplicateAgainstRequests:
    def test_removes_existing_tracks(self):
        candidates = [
            TrackProfile(title="Already Requested", artist="Same Artist"),
            TrackProfile(title="New Track", artist="Different Artist"),
        ]
        requests = [MagicMock(song_title="Already Requested", artist="Same Artist")]
        result = deduplicate_against_requests(candidates, requests)
        assert len(result) == 1
        assert result[0].title == "New Track"

    def test_empty_requests(self):
        candidates = [TrackProfile(title="Track", artist="Artist")]
        result = deduplicate_against_requests(candidates, [])
        assert len(result) == 1


class TestDeduplicateCandidates:
    def test_removes_duplicate_candidates(self):
        candidates = [
            TrackProfile(title="Same Track", artist="Same Artist", source="beatport"),
            TrackProfile(title="Same Track", artist="Same Artist", source="tidal"),
            TrackProfile(title="Different Track", artist="Other Artist"),
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 2

    def test_no_duplicates(self):
        candidates = [
            TrackProfile(title="Strobe", artist="deadmau5"),
            TrackProfile(title="Clarity", artist="Zedd"),
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 2


class TestGenerateRecommendations:
    @patch(
        "app.services.recommendation.mb_verify.verify_artists_batch",
        return_value={"DJ": True},
    )
    @patch("app.services.recommendation.service._search_candidates")
    @patch("app.services.recommendation.service.enrich_event_tracks")
    @patch("app.services.recommendation.service._get_accepted_played_requests")
    def test_full_pipeline(self, mock_requests, mock_enrich, mock_search, mock_mb):
        mock_requests.return_value = [
            MagicMock(song_title="Song", artist="Artist", status="accepted"),
        ]
        mock_enrich.return_value = [
            TrackProfile(title="Song", artist="Artist", bpm=128.0, key="8A", genre="House"),
        ]
        mock_search.return_value = (
            [
                TrackProfile(
                    title="Suggestion",
                    artist="DJ",
                    bpm=127.0,
                    key="8A",
                    genre="House",
                    source="beatport",
                ),
            ],
            ["beatport"],
            1,
        )

        db = MagicMock()
        # Mock the dedup query to return no existing requests for the candidate
        db.query.return_value.filter.return_value.all.return_value = [
            MagicMock(song_title="Song", artist="Artist"),
        ]

        user = _make_user(tidal=False)
        event = _make_event()

        result = generate_recommendations(db, user, event)
        assert isinstance(result, RecommendationResult)
        assert len(result.suggestions) > 0
        assert result.enriched_count == 1
        assert "beatport" in result.services_used

    def test_no_services_connected(self):
        db = MagicMock()
        user = _make_user(tidal=False, beatport=False)
        event = _make_event()

        result = generate_recommendations(db, user, event)
        assert result.suggestions == []
        assert result.services_used == []
        assert result.event_profile.track_count == 0

    @patch(
        "app.services.recommendation.mb_verify.verify_artists_batch",
        return_value={"Related Artist": True},
    )
    @patch(
        "app.services.recommendation.soundcharts_candidates.related_candidates_from_seeds",
    )
    @patch("app.services.recommendation.service.enrich_event_tracks")
    @patch("app.services.recommendation.service._get_accepted_played_requests")
    def test_soundcharts_related_with_no_connected_service(
        self, mock_requests, mock_enrich, mock_related, mock_mb
    ):
        """Issue #556: a DJ with no Tidal/Beatport still gets suggestions when the
        Soundcharts related-tracks source is enabled."""
        mock_requests.return_value = [
            MagicMock(song_title="Seed", artist="Seed Artist", status="accepted"),
        ]
        mock_enrich.return_value = [
            TrackProfile(title="Seed", artist="Seed Artist", bpm=120.0, key="8A", genre="House"),
        ]
        mock_related.return_value = (
            [TrackProfile(title="Related Hit", artist="Related Artist", source="soundcharts")],
            1,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = _make_user(tidal=False, beatport=False)
        event = _make_event()

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.soundcharts_related_tracks_enabled = True
            mock_settings.return_value.soundcharts_app_id = "id"
            mock_settings.return_value.soundcharts_api_key = "key"
            result = generate_recommendations(db, user, event)

        assert len(result.suggestions) > 0
        assert "soundcharts" in result.services_used
        assert result.suggestions[0].profile.source == "soundcharts"

    @patch("app.services.recommendation.soundcharts_candidates.related_candidates_from_seeds")
    def test_soundcharts_related_disabled_behaves_as_today(self, mock_related):
        """Dark by default: disabled flag → no related lookup, empty result for an
        unconnected DJ exactly as before."""
        db = MagicMock()
        user = _make_user(tidal=False, beatport=False)
        event = _make_event()

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.soundcharts_related_tracks_enabled = False
            mock_settings.return_value.soundcharts_app_id = "id"
            mock_settings.return_value.soundcharts_api_key = "key"
            result = generate_recommendations(db, user, event)

        assert result.suggestions == []
        assert result.services_used == []
        mock_related.assert_not_called()

    @patch("app.services.recommendation.service._search_candidates")
    @patch("app.services.recommendation.service.enrich_event_tracks")
    @patch("app.services.recommendation.service._get_accepted_played_requests")
    def test_no_accepted_requests(self, mock_requests, mock_enrich, mock_search):
        mock_requests.return_value = []
        mock_search.return_value = ([], [], 0)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = _make_user()
        event = _make_event()

        result = generate_recommendations(db, user, event)
        assert result.suggestions == []
        assert result.event_profile.track_count == 0
        mock_enrich.assert_not_called()

    @patch("app.services.recommendation.service._search_candidates")
    @patch("app.services.recommendation.service.enrich_event_tracks")
    @patch("app.services.recommendation.service._get_accepted_played_requests")
    def test_dedup_excludes_existing(self, mock_requests, mock_enrich, mock_search):
        mock_requests.return_value = [
            MagicMock(song_title="Existing Song", artist="Existing Artist"),
        ]
        mock_enrich.return_value = [
            TrackProfile(title="Existing Song", artist="Existing Artist", bpm=128.0),
        ]
        # Search returns the same track that already exists
        mock_search.return_value = (
            [
                TrackProfile(
                    title="Existing Song", artist="Existing Artist", bpm=128.0, source="beatport"
                ),
            ],
            ["beatport"],
            1,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            MagicMock(song_title="Existing Song", artist="Existing Artist"),
        ]
        user = _make_user()
        event = _make_event()

        result = generate_recommendations(db, user, event)
        # The existing song should be deduped out
        assert len(result.suggestions) == 0


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


def _make_scored(title, artist, score, bpm_score=0.5, key_score=0.5, genre_score=0.5):
    """Helper to create a ScoredTrack for diversity tests."""
    from app.services.recommendation.scorer import ScoredTrack

    return ScoredTrack(
        profile=TrackProfile(title=title, artist=artist),
        score=score,
        bpm_score=bpm_score,
        key_score=key_score,
        genre_score=genre_score,
    )


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


def _make_query(
    search_query="test",
    target_bpm=None,
    target_key=None,
    target_genre=None,
):
    return LLMSuggestionQuery(
        search_query=search_query,
        target_bpm=target_bpm,
        target_key=target_key,
        target_genre=target_genre,
        reasoning="test",
    )


class TestLLMScoringProfile:
    """Tests for _build_llm_scoring_profile vibe shift detection."""

    def test_vibe_shift_bpm(self):
        """BPM targets averaging 128 vs original 95 → synthetic profile."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=10)
        queries = [
            _make_query(target_bpm=126.0, target_genre="House"),
            _make_query(target_bpm=128.0, target_genre="House"),
            _make_query(target_bpm=130.0, target_genre="House"),
        ]
        result = _build_llm_scoring_profile(queries, original)

        # Should return synthetic profile, not original
        assert result is not original
        assert abs(result.avg_bpm - 128.0) < 0.1
        assert "House" in result.dominant_genres

    def test_vibe_shift_genre(self):
        """Target genres don't overlap with original → synthetic profile."""
        original = EventProfile(
            avg_bpm=95.0, dominant_genres=["Country", "Americana"], track_count=10
        )
        queries = [
            _make_query(target_bpm=128.0, target_genre="House"),
            _make_query(target_bpm=126.0, target_genre="Tech House"),
        ]
        result = _build_llm_scoring_profile(queries, original)

        assert result is not original
        assert "House" in result.dominant_genres
        assert "Tech House" in result.dominant_genres

    def test_no_shift_similar_bpm(self):
        """Targets similar to original (BPM delta <15) → original profile kept."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=10)
        queries = [
            _make_query(target_bpm=97.0, target_genre="Country"),
            _make_query(target_bpm=93.0, target_genre="Country"),
        ]
        result = _build_llm_scoring_profile(queries, original)

        assert result is original

    def test_no_targets(self):
        """All queries have None targets → original profile (backward compat)."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=10)
        queries = [
            _make_query(),
            _make_query(),
        ]
        result = _build_llm_scoring_profile(queries, original)

        assert result is original

    def test_partial_targets_below_threshold(self):
        """Only minority of queries have targets → original profile kept."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=10)
        queries = [
            _make_query(target_bpm=128.0, target_genre="House"),
            _make_query(),
            _make_query(),
            _make_query(),
        ]
        result = _build_llm_scoring_profile(queries, original)

        # Only 1/4 queries have targets — below 50% threshold
        assert result is original

    def test_partial_targets_above_threshold(self):
        """Majority of queries have targets with shift → synthetic profile."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=10)
        queries = [
            _make_query(target_bpm=128.0, target_genre="House"),
            _make_query(target_bpm=126.0, target_genre="House"),
            _make_query(),
        ]
        result = _build_llm_scoring_profile(queries, original)

        # 2/3 queries have targets (above 50%) with significant BPM shift
        assert result is not original
        assert abs(result.avg_bpm - 127.0) < 0.1

    def test_empty_queries(self):
        """Empty query list → original profile."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=10)
        result = _build_llm_scoring_profile([], original)

        assert result is original

    def test_synthetic_preserves_track_count(self):
        """Synthetic profile preserves original track count."""
        original = EventProfile(avg_bpm=95.0, dominant_genres=["Country"], track_count=15)
        queries = [
            _make_query(target_bpm=128.0, target_genre="House"),
            _make_query(target_bpm=130.0, target_genre="House"),
        ]
        result = _build_llm_scoring_profile(queries, original)

        assert result.track_count == 15

    def test_synthetic_falls_back_to_original_keys(self):
        """When LLM provides no target keys, original keys are preserved."""
        original = EventProfile(
            avg_bpm=95.0,
            dominant_keys=["8A", "11B"],
            dominant_genres=["Country"],
            track_count=10,
        )
        queries = [
            _make_query(target_bpm=128.0, target_genre="House"),
            _make_query(target_bpm=130.0, target_genre="House"),
        ]
        result = _build_llm_scoring_profile(queries, original)

        assert list(result.dominant_keys) == ["8A", "11B"]

    def test_genre_shift_with_overlapping_bpm(self):
        """Genre shift detected even when BPM is similar."""
        original = EventProfile(avg_bpm=128.0, dominant_genres=["Pop", "Top 40"], track_count=10)
        queries = [
            _make_query(target_bpm=128.0, target_genre="Techno"),
            _make_query(target_bpm=130.0, target_genre="Tech House"),
        ]
        result = _build_llm_scoring_profile(queries, original)

        # BPM is similar but genres are completely different
        assert result is not original
        assert "Techno" in result.dominant_genres


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


class TestSearchCandidates:
    """Tests for _search_candidates including cascade behavior."""

    def test_beatport_structured_browse(self):
        """Beatport connected with profile → uses structured browse."""
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        mock_result = BeatportSearchResult(
            track_id="1",
            title="Strobe",
            artist="deadmau5",
            bpm=128,
            key="A min",
            genre="Progressive House",
            beatport_url="https://beatport.com/track/strobe/1",
        )

        with patch("app.services.beatport.browse_beatport_tracks", return_value=[mock_result]):
            profile = EventProfile(
                dominant_genres=["Progressive House"], avg_bpm=128, track_count=5
            )
            candidates, services, total = _search_candidates(
                db, user, ["Progressive House"], profile=profile
            )

        assert len(candidates) == 1
        assert candidates[0].source == "beatport"
        assert "beatport" in services
        assert "tidal" not in services

    def test_beatport_text_fallback_no_profile(self):
        """Beatport connected, no profile → falls back to text search."""
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        mock_result = BeatportSearchResult(
            track_id="1",
            title="Strobe",
            artist="deadmau5",
            bpm=128,
            key="A min",
            genre="Progressive House",
            beatport_url="https://beatport.com/track/strobe/1",
        )

        with patch("app.services.beatport.search_beatport_tracks", return_value=[mock_result]):
            candidates, services, total = _search_candidates(db, user, ["Progressive House"])

        assert len(candidates) == 1
        assert candidates[0].source == "beatport"

    @patch("app.services.tidal.search_tidal_tracks")
    def test_tidal_text_fallback_when_no_lb_radio(self, mock_tidal_search):
        """Tidal connected, LB Radio returns empty → falls back to text search."""
        user = _make_user(tidal=True, beatport=False)
        db = MagicMock()

        mock_tidal_result = MagicMock()
        mock_tidal_result.title = "Strobe"
        mock_tidal_result.artist = "deadmau5"
        mock_tidal_result.bpm = 128.0
        mock_tidal_result.key = "A min"
        mock_tidal_result.track_id = "t1"
        mock_tidal_result.tidal_url = "https://tidal.com/track/t1"
        mock_tidal_result.cover_url = None
        mock_tidal_result.duration_seconds = 600
        mock_tidal_search.return_value = [mock_tidal_result]

        profile = EventProfile(dominant_genres=["House"], track_count=5)

        with (
            patch("app.services.listenbrainz.lb_radio_discover", return_value=[]),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = ""
            mock_settings.return_value.soundcharts_api_key = ""
            mock_settings.return_value.listenbrainz_user_token = ""
            candidates, services, total = _search_candidates(
                db, user, ["House"], profile=profile, tidal_queries=["deadmau5"]
            )

        assert len(candidates) == 1
        assert candidates[0].source == "tidal"
        assert "tidal" in services

    @patch("app.services.recommendation.soundcharts_candidates.related_candidates_from_seeds")
    def test_soundcharts_related_source_no_connected_service(self, mock_related):
        """Related-tracks source contributes candidates + 'soundcharts' service
        even when no Tidal/Beatport is connected."""
        user = _make_user(tidal=False, beatport=False)
        db = MagicMock()
        mock_related.return_value = (
            [TrackProfile(title="Related", artist="Artist", source="soundcharts")],
            1,
        )
        requests = [MagicMock(song_title="Seed", artist="Seed Artist", isrc="USAAA0000001")]

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.soundcharts_related_tracks_enabled = True
            mock_settings.return_value.soundcharts_app_id = "id"
            mock_settings.return_value.soundcharts_api_key = "key"
            candidates, services, total = _search_candidates(db, user, ["House"], requests=requests)

        assert any(c.source == "soundcharts" for c in candidates)
        assert "soundcharts" in services
        mock_related.assert_called_once()

    @patch("app.services.recommendation.soundcharts_candidates.related_candidates_from_seeds")
    def test_soundcharts_related_source_disabled(self, mock_related):
        """Disabled flag → related source is never invoked."""
        user = _make_user(tidal=False, beatport=False)
        db = MagicMock()
        requests = [MagicMock(song_title="Seed", artist="Seed Artist", isrc="USAAA0000001")]

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.soundcharts_related_tracks_enabled = False
            mock_settings.return_value.soundcharts_app_id = "id"
            mock_settings.return_value.soundcharts_api_key = "key"
            candidates, services, total = _search_candidates(db, user, ["House"], requests=requests)

        assert candidates == []
        assert services == []
        mock_related.assert_not_called()

    def test_beatport_text_failures_trigger_early_exit(self):
        """2+ Beatport text search failures → stops trying remaining queries."""
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        call_count = 0

        def failing_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return []

        with patch("app.services.beatport.search_beatport_tracks", side_effect=failing_search):
            candidates, services, total = _search_candidates(
                db, user, ["Query A", "Query B", "Query C"]
            )

        # Should stop after 2 failures, not try all 3
        assert call_count == 2
        assert candidates == []

    def test_filters_unwanted_versions(self):
        """Karaoke/unwanted versions are filtered out."""
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Song (Karaoke Version)",
                artist="Artist",
                beatport_url="https://beatport.com/track/song/1",
            ),
            BeatportSearchResult(
                track_id="2",
                title="Song (Original Mix)",
                artist="Artist",
                genre="House",
                beatport_url="https://beatport.com/track/song/2",
            ),
        ]

        with patch("app.services.beatport.search_beatport_tracks", return_value=results):
            candidates, services, total = _search_candidates(db, user, ["House"])

        assert len(candidates) == 1
        assert candidates[0].title == "Song (Original Mix)"

    def test_filters_blocked_genres(self):
        """DJ Tools and other blocked genres are filtered."""
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Some Track",
                artist="Artist",
                genre="DJ Tools",
                beatport_url="https://beatport.com/track/some/1",
            ),
            BeatportSearchResult(
                track_id="2",
                title="Real Track",
                artist="Artist",
                genre="Tech House",
                beatport_url="https://beatport.com/track/real/2",
            ),
        ]

        with patch("app.services.beatport.search_beatport_tracks", return_value=results):
            candidates, services, total = _search_candidates(db, user, ["Tech House"])

        assert len(candidates) == 1
        assert candidates[0].genre == "Tech House"

    def test_filters_junk_candidates(self):
        """Backing tracks and other junk are filtered."""
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        results = [
            BeatportSearchResult(
                track_id="1",
                title="Song (Backing Track)",
                artist="Cover Band",
                genre="House",
                beatport_url="https://beatport.com/track/song/1",
            ),
            BeatportSearchResult(
                track_id="2",
                title="Actual Song",
                artist="Real Artist",
                genre="House",
                beatport_url="https://beatport.com/track/actual/2",
            ),
        ]

        with patch("app.services.beatport.search_beatport_tracks", return_value=results):
            candidates, services, total = _search_candidates(db, user, ["House"])

        assert len(candidates) == 1
        assert candidates[0].title == "Actual Song"

    def test_no_services_connected(self):
        """No services → empty result."""
        user = _make_user(tidal=False, beatport=False)
        db = MagicMock()

        candidates, services, total = _search_candidates(db, user, ["House"])

        assert candidates == []
        assert services == []
        assert total == 0

    def test_all_services_fail_returns_empty(self):
        """Beatport fails + Tidal returns empty → empty candidates, no crash."""
        user = _make_user(tidal=True, beatport=True)
        db = MagicMock()

        with (
            patch("app.services.beatport.browse_beatport_tracks", return_value=[]),
            patch("app.services.beatport.search_beatport_tracks", return_value=[]),
            patch("app.services.listenbrainz.lb_radio_discover", return_value=[]),
            patch("app.services.tidal.search_tidal_tracks", return_value=[]),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = ""
            mock_settings.return_value.soundcharts_api_key = ""
            mock_settings.return_value.listenbrainz_user_token = ""
            candidates, services, total = _search_candidates(
                db,
                user,
                ["House"],
                profile=EventProfile(dominant_genres=["House"], track_count=5),
                tidal_queries=["deadmau5"],
            )

        assert candidates == []

    @patch("app.services.recommendation.soundcharts_candidates.search_candidates_via_soundcharts")
    @patch("app.services.tidal.search_tidal_tracks")
    def test_soundcharts_empty_falls_back_to_tidal_text(self, mock_tidal_search, mock_soundcharts):
        """Soundcharts returns empty → falls back to Tidal text search."""
        user = _make_user(tidal=True, beatport=False)
        db = MagicMock()

        mock_soundcharts.return_value = ([], 0)

        mock_tidal_result = MagicMock()
        mock_tidal_result.title = "Strobe"
        mock_tidal_result.artist = "deadmau5"
        mock_tidal_result.bpm = 128.0
        mock_tidal_result.key = "A min"
        mock_tidal_result.track_id = "t1"
        mock_tidal_result.tidal_url = "https://tidal.com/track/t1"
        mock_tidal_result.cover_url = None
        mock_tidal_result.duration_seconds = 600
        mock_tidal_search.return_value = [mock_tidal_result]

        profile = EventProfile(dominant_genres=["House"], track_count=5)

        with (
            patch("app.services.listenbrainz.lb_radio_discover", return_value=[]),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = "app_id"
            mock_settings.return_value.soundcharts_api_key = "api_key"
            mock_settings.return_value.listenbrainz_user_token = ""
            candidates, services, total = _search_candidates(
                db, user, ["House"], profile=profile, tidal_queries=["deadmau5"]
            )

        # Soundcharts returned empty, so it should fall back to text search
        assert len(candidates) == 1
        assert candidates[0].source == "tidal"
        mock_tidal_search.assert_called_once()


class TestCascadeGenerateRecommendations:
    """Cascade tests for generate_recommendations end-to-end."""

    @patch("app.services.recommendation.service._search_candidates")
    @patch("app.services.recommendation.service.enrich_event_tracks")
    @patch("app.services.recommendation.service._get_accepted_played_requests")
    def test_all_search_services_fail_returns_empty(self, mock_requests, mock_enrich, mock_search):
        """All search services fail → suggestions=[] with no crash."""
        mock_requests.return_value = [
            MagicMock(song_title="Song", artist="Artist", status="accepted"),
        ]
        mock_enrich.return_value = [
            TrackProfile(title="Song", artist="Artist", bpm=128.0),
        ]
        mock_search.return_value = ([], [], 0)

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = _make_user()
        event = _make_event()

        result = generate_recommendations(db, user, event)
        assert result.suggestions == []
        assert result.total_candidates_searched == 0


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


class TestDiversifiedTidalQueries:
    """Tests for the diversified Tidal query builder."""

    def test_genre_discovery_fills_remaining_slots(self):
        """With genres available, only 1 artist + genre discovery queries."""
        profile = EventProfile(
            dominant_genres=["House", "Tech House"],
            track_count=5,
        )
        requests = [
            MagicMock(artist="deadmau5"),
            MagicMock(artist="deadmau5"),
            MagicMock(artist="Zedd"),
        ]
        queries = build_tidal_queries(profile, requests=requests)
        assert queries[0] == "deadmau5"
        assert "House music" in queries
        assert len(queries) == 3

    def test_no_genres_falls_back_to_artists(self):
        """Without genres, all slots use queue artists."""
        profile = EventProfile(track_count=5)
        requests = [
            MagicMock(artist="Artist A"),
            MagicMock(artist="Artist B"),
            MagicMock(artist="Artist C"),
        ]
        queries = build_tidal_queries(profile, requests=requests)
        assert queries[0] == "Artist A"
        assert "Artist B" in queries
        assert "Artist C" in queries

    def test_one_genre_one_fallback_artist(self):
        """1 genre available → 1 artist + 1 genre + 1 fallback artist."""
        profile = EventProfile(
            dominant_genres=["Progressive House"],
            track_count=5,
        )
        requests = [
            MagicMock(artist="deadmau5"),
            MagicMock(artist="Zedd"),
            MagicMock(artist="Avicii"),
        ]
        queries = build_tidal_queries(profile, requests=requests)
        assert queries[0] == "deadmau5"
        assert "Progressive House music" in queries
        # Third slot falls back to next artist
        assert "Zedd" in queries


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

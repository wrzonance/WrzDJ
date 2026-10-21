"""Recommendation query and generation tests."""

from unittest.mock import MagicMock, patch

from app.schemas.tidal import TidalSearchResult
from app.services.recommendation.deduplication import (
    deduplicate_against_requests,
    deduplicate_against_template,
    deduplicate_candidates,
)
from app.services.recommendation.query_builder import build_beatport_queries, build_tidal_queries
from app.services.recommendation.scorer import EventProfile
from app.services.recommendation.service import (
    RecommendationResult,
    _build_llm_scoring_profile,
    generate_recommendations,
)
from app.services.tracks.profile import TrackProfile
from app.services.tracks.profile_mappers import tidal_result_to_profile
from tests.recommendation_service_test_helpers import _make_query
from tests.recommendation_test_helpers import (  # noqa: F401
    _make_event,
    _make_user,
    _recommendation_context,
)


def test_tidal_result_mapping_preserves_metadata_and_optional_inferred_genre():
    result = TidalSearchResult(
        track_id="tidal-123",
        title="Night Drive",
        artist="DJ Example",
        bpm=124.5,
        key="8A",
        duration_seconds=301,
        cover_url="https://example.test/cover.jpg",
        tidal_url="https://tidal.com/track/123",
    )

    profile = tidal_result_to_profile(result)
    inferred = tidal_result_to_profile(result, inferred_genre="Deep House")

    assert profile == TrackProfile(
        title="Night Drive",
        artist="DJ Example",
        bpm=124.5,
        key="8A",
        genre=None,
        source="tidal",
        track_id="tidal-123",
        url="https://tidal.com/track/123",
        cover_url="https://example.test/cover.jpg",
        duration_seconds=301,
    )
    assert inferred.genre == "Deep House"


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

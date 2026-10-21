"""Recommendation candidate search and cascade tests."""

from unittest.mock import MagicMock, patch

from app.services.recommendation.query_builder import build_tidal_queries
from app.services.recommendation.scorer import EventProfile
from app.services.recommendation.service import (
    _search_candidates,
    generate_recommendations,
)
from app.services.tracks.profile import TrackProfile
from tests.recommendation_test_helpers import (  # noqa: F401
    _make_event,
    _make_user,
    _recommendation_context,
)


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

        with patch(
            "app.services.providers.beatport_catalog.browse_beatport_tracks",
            return_value=[mock_result],
        ):
            profile = EventProfile(
                dominant_genres=["Progressive House"], avg_bpm=128, track_count=5
            )
            candidates, services, total = _search_candidates(
                db, user, ["Progressive House"], _recommendation_context(profile)
            )

        assert len(candidates) == 1
        assert candidates[0].source == "beatport"
        assert "beatport" in services
        assert "tidal" not in services

    def test_beatport_browse_prefers_specific_genre_match(self):
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        result = BeatportSearchResult(
            track_id="1",
            title="Track",
            artist="Artist",
            genre="Tech House",
            beatport_url="https://beatport.com/track/track/1",
        )
        profile = EventProfile(
            dominant_genres=["Tech House (Peak Time)"], avg_bpm=128, track_count=5
        )

        with patch(
            "app.services.providers.beatport_catalog.browse_beatport_tracks", return_value=[result]
        ) as browse:
            candidates, _, _ = _search_candidates(
                db, user, ["Tech House"], _recommendation_context(profile)
            )

        assert candidates
        assert browse.call_args.kwargs["genre_id"] == 11

    def test_beatport_fallback_counts_filtered_structured_results(self):
        user = _make_user(tidal=False, beatport=True)
        db = MagicMock()

        from app.schemas.beatport import BeatportSearchResult

        filtered = BeatportSearchResult(
            track_id="1",
            title="Track No Vocals",
            artist="Artist",
            genre="House",
            beatport_url="https://beatport.com/track/track/1",
        )
        accepted = BeatportSearchResult(
            track_id="2",
            title="Track",
            artist="Artist",
            genre="House",
            beatport_url="https://beatport.com/track/track/2",
        )
        profile = EventProfile(dominant_genres=["House"], avg_bpm=128, track_count=5)

        with (
            patch(
                "app.services.providers.beatport_catalog.browse_beatport_tracks",
                return_value=[filtered],
            ),
            patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks",
                return_value=[accepted],
            ),
        ):
            candidates, _, total = _search_candidates(
                db, user, ["House"], _recommendation_context(profile)
            )

        assert len(candidates) == 1
        assert total == 2

    def test_tidal_fallback_counts_results_from_each_strategy(self):
        user = _make_user(tidal=True, beatport=False)
        db = MagicMock()
        lb_track = MagicMock(artist="Artist", title="LB pick")
        filtered_tidal = MagicMock(
            title="No Vocals track",
            artist="Artist",
            bpm=128,
            key="8A",
            track_id="t-filtered",
            tidal_url="https://tidal.com/track/t-filtered",
            cover_url=None,
            duration_seconds=180,
        )
        accepted_tidal = MagicMock(
            title="Playable track",
            artist="Artist",
            bpm=128,
            key="8A",
            track_id="t-accepted",
            tidal_url="https://tidal.com/track/t-accepted",
            cover_url=None,
            duration_seconds=180,
        )
        filtered_soundcharts = TrackProfile(title="No Vocals track", artist="Artist")
        profile = EventProfile(dominant_genres=["House"], track_count=5)

        with (
            patch(
                "app.services.providers.listenbrainz.lb_radio_discover",
                return_value=[lb_track],
            ) as mock_lb_radio,
            patch(
                "app.services.providers.tidal_search.search_tidal_tracks",
                side_effect=[[filtered_tidal], [accepted_tidal]],
            ),
            patch(
                "app.services.recommendation.soundcharts_candidates.search_candidates_via_soundcharts",
                return_value=([filtered_soundcharts], 1),
            ),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = "app_id"
            mock_settings.return_value.soundcharts_api_key = "api_key"
            candidates, _, total = _search_candidates(
                db,
                user,
                ["House"],
                _recommendation_context(
                    profile,
                    requests=[MagicMock(artist="DJ Seed")],
                ),
                tidal_queries=["Artist"],
            )

        assert len(candidates) == 1
        assert total == 3
        assert mock_lb_radio.call_args_list[0].args == ("artist:(DJ Seed)",)

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

        with patch(
            "app.services.providers.beatport_catalog.search_beatport_tracks",
            return_value=[mock_result],
        ):
            candidates, services, total = _search_candidates(
                db, user, ["Progressive House"], _recommendation_context()
            )

        assert len(candidates) == 1
        assert candidates[0].source == "beatport"

    @patch("app.services.providers.tidal_search.search_tidal_tracks")
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
            patch("app.services.providers.listenbrainz.lb_radio_discover", return_value=[]),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = ""
            mock_settings.return_value.soundcharts_api_key = ""
            mock_settings.return_value.listenbrainz_user_token = ""
            candidates, services, total = _search_candidates(
                db, user, ["House"], _recommendation_context(profile), tidal_queries=["deadmau5"]
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
            candidates, services, total = _search_candidates(
                db, user, ["House"], _recommendation_context(requests=requests)
            )

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
            candidates, services, total = _search_candidates(
                db, user, ["House"], _recommendation_context(requests=requests)
            )

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

        with patch(
            "app.services.providers.beatport_catalog.search_beatport_tracks",
            side_effect=failing_search,
        ):
            candidates, services, total = _search_candidates(
                db, user, ["Query A", "Query B", "Query C"], _recommendation_context()
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

        with patch(
            "app.services.providers.beatport_catalog.search_beatport_tracks", return_value=results
        ):
            candidates, services, total = _search_candidates(
                db, user, ["House"], _recommendation_context()
            )

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

        with patch(
            "app.services.providers.beatport_catalog.search_beatport_tracks", return_value=results
        ):
            candidates, services, total = _search_candidates(
                db, user, ["Tech House"], _recommendation_context()
            )

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

        with patch(
            "app.services.providers.beatport_catalog.search_beatport_tracks", return_value=results
        ):
            candidates, services, total = _search_candidates(
                db, user, ["House"], _recommendation_context()
            )

        assert len(candidates) == 1
        assert candidates[0].title == "Actual Song"

    def test_no_services_connected(self):
        """No services → empty result."""
        user = _make_user(tidal=False, beatport=False)
        db = MagicMock()

        candidates, services, total = _search_candidates(
            db, user, ["House"], _recommendation_context()
        )

        assert candidates == []
        assert services == []
        assert total == 0

    def test_all_services_fail_returns_empty(self):
        """Beatport fails + Tidal returns empty → empty candidates, no crash."""
        user = _make_user(tidal=True, beatport=True)
        db = MagicMock()

        with (
            patch(
                "app.services.providers.beatport_catalog.browse_beatport_tracks", return_value=[]
            ),
            patch(
                "app.services.providers.beatport_catalog.search_beatport_tracks", return_value=[]
            ),
            patch("app.services.providers.listenbrainz.lb_radio_discover", return_value=[]),
            patch("app.services.providers.tidal_search.search_tidal_tracks", return_value=[]),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = ""
            mock_settings.return_value.soundcharts_api_key = ""
            mock_settings.return_value.listenbrainz_user_token = ""
            candidates, services, total = _search_candidates(
                db,
                user,
                ["House"],
                _recommendation_context(EventProfile(dominant_genres=["House"], track_count=5)),
                tidal_queries=["deadmau5"],
            )

        assert candidates == []

    @patch("app.services.recommendation.soundcharts_candidates.search_candidates_via_soundcharts")
    @patch("app.services.providers.tidal_search.search_tidal_tracks")
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
            patch("app.services.providers.listenbrainz.lb_radio_discover", return_value=[]),
            patch("app.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.soundcharts_app_id = "app_id"
            mock_settings.return_value.soundcharts_api_key = "api_key"
            mock_settings.return_value.listenbrainz_user_token = ""
            candidates, services, total = _search_candidates(
                db, user, ["House"], _recommendation_context(profile), tidal_queries=["deadmau5"]
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

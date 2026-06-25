"""Tests for Soundcharts → Tidal candidate resolution pipeline."""

from unittest.mock import MagicMock, patch

from app.schemas.tidal import TidalSearchResult
from app.services.recommendation.scorer import EventProfile
from app.services.recommendation.soundcharts_candidates import (
    BPM_RANGE_OFFSET,
    related_candidates_from_seeds,
    search_candidates_via_soundcharts,
)
from app.services.soundcharts import SoundchartsTrack


def _make_user():
    user = MagicMock()
    user.tidal_access_token = "tok"
    return user


def _make_tidal_result(title="Song", artist="Artist", track_id="123"):
    return TidalSearchResult(
        track_id=track_id,
        title=title,
        artist=artist,
        bpm=128.0,
        key="D Minor",
        duration_seconds=240,
        cover_url="https://example.com/cover.jpg",
        tidal_url=f"https://tidal.com/browse/track/{track_id}",
    )


class TestSearchCandidatesViaSoundcharts:
    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_full_pipeline(self, mock_discover, mock_tidal_search):
        mock_discover.return_value = [
            SoundchartsTrack(title="Country Roads", artist="John Denver", soundcharts_uuid="a"),
            SoundchartsTrack(title="Jolene", artist="Dolly Parton", soundcharts_uuid="b"),
        ]
        mock_tidal_search.side_effect = [
            [_make_tidal_result("Country Roads", "John Denver", "111")],
            [_make_tidal_result("Jolene", "Dolly Parton", "222")],
        ]

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            avg_bpm=120.0,
            dominant_genres=["Country"],
            dominant_keys=["G Major"],
            track_count=5,
        )

        candidates, total_searched = search_candidates_via_soundcharts(db, user, profile)

        assert len(candidates) == 2
        assert total_searched == 2
        assert candidates[0].title == "Country Roads"
        assert candidates[0].source == "tidal"
        assert candidates[0].track_id == "111"
        assert candidates[0].genre == "Country"
        assert candidates[1].title == "Jolene"
        assert candidates[1].genre == "Country"

        # Verify discover_songs was called with correct args
        mock_discover.assert_called_once_with(
            genres=["Country"],
            bpm_min=120.0 - BPM_RANGE_OFFSET,
            bpm_max=120.0 + BPM_RANGE_OFFSET,
            keys=["G Major"],
            limit=25,
        )

    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_tidal_not_found_skipped(self, mock_discover, mock_tidal_search):
        mock_discover.return_value = [
            SoundchartsTrack(title="Rare Song", artist="Unknown Artist", soundcharts_uuid="x"),
            SoundchartsTrack(title="Found Song", artist="Known Artist", soundcharts_uuid="y"),
        ]
        mock_tidal_search.side_effect = [
            [],  # Not found on Tidal
            [_make_tidal_result("Found Song", "Known Artist", "333")],
        ]

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            dominant_genres=["Pop"],
            track_count=3,
        )

        candidates, total_searched = search_candidates_via_soundcharts(db, user, profile)

        assert len(candidates) == 1
        assert total_searched == 2
        assert candidates[0].title == "Found Song"

    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_soundcharts_empty_returns_empty(self, mock_discover):
        mock_discover.return_value = []

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            dominant_genres=["Country"],
            track_count=5,
        )

        candidates, total_searched = search_candidates_via_soundcharts(db, user, profile)
        assert candidates == []
        assert total_searched == 0

    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_bpm_range_calculation(self, mock_discover, mock_tidal_search):
        mock_discover.return_value = []

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            avg_bpm=100.0,
            dominant_genres=["Rock"],
            track_count=5,
        )

        search_candidates_via_soundcharts(db, user, profile)

        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["bpm_min"] == 100.0 - BPM_RANGE_OFFSET
        assert call_kwargs.kwargs["bpm_max"] == 100.0 + BPM_RANGE_OFFSET

    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_no_bpm_sends_none(self, mock_discover, mock_tidal_search):
        mock_discover.return_value = []

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            dominant_genres=["Pop"],
            track_count=3,
        )

        search_candidates_via_soundcharts(db, user, profile)

        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["bpm_min"] is None
        assert call_kwargs.kwargs["bpm_max"] is None

    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_key_filter_passed(self, mock_discover, mock_tidal_search):
        mock_discover.return_value = []

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            dominant_genres=["House"],
            dominant_keys=["D Minor", "G Major"],
            track_count=5,
        )

        search_candidates_via_soundcharts(db, user, profile)

        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["keys"] == ["D Minor", "G Major"]

    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_genre_propagated_from_profile(self, mock_discover, mock_tidal_search):
        """Candidates get genre inferred from the profile's dominant genre."""
        mock_discover.return_value = [
            SoundchartsTrack(title="Song A", artist="Artist A", soundcharts_uuid="a"),
        ]
        mock_tidal_search.return_value = [
            _make_tidal_result("Song A", "Artist A", "111"),
        ]

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            dominant_genres=["House", "Tech House"],
            track_count=5,
        )

        candidates, _ = search_candidates_via_soundcharts(db, user, profile)
        assert len(candidates) == 1
        assert candidates[0].genre == "House"

    @patch("app.services.tidal.search_tidal_tracks")
    @patch("app.services.recommendation.soundcharts_candidates.discover_songs")
    def test_no_keys_sends_none(self, mock_discover, mock_tidal_search):
        mock_discover.return_value = []

        db = MagicMock()
        user = _make_user()
        profile = EventProfile(
            dominant_genres=["Pop"],
            track_count=3,
        )

        search_candidates_via_soundcharts(db, user, profile)

        call_kwargs = mock_discover.call_args
        assert call_kwargs.kwargs["keys"] is None


def _make_request(artist="Artist", title="Song", isrc=None):
    req = MagicMock()
    req.artist = artist
    req.song_title = title
    req.isrc = isrc
    return req


class TestRelatedCandidatesFromSeeds:
    """ISRC-seeded related-tracks candidate generator for #556.

    Resolves each seed request's ISRC (request.isrc first, then the master
    tracks store by signature), calls the dark-by-default related-tracks
    adapter, and converts the results to soundcharts-source TrackProfiles.
    """

    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_seed_isrc_yields_candidates(self, mock_related):
        mock_related.return_value = [
            SoundchartsTrack(title="Rel One", artist="Artist A", soundcharts_uuid="u1"),
            SoundchartsTrack(title="Rel Two", artist="Artist B", soundcharts_uuid="u2"),
        ]
        db = MagicMock()
        requests = [_make_request("Seed Artist", "Seed Song", isrc="USABC1234567")]

        candidates, seeds_used = related_candidates_from_seeds(db, requests)

        assert seeds_used == 1
        assert len(candidates) == 2
        assert candidates[0].title == "Rel One"
        assert candidates[0].artist == "Artist A"
        assert candidates[0].source == "soundcharts"
        mock_related.assert_called_once_with("USABC1234567", limit=20)

    @patch("app.services.recommendation.soundcharts_candidates.get_track")
    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_falls_back_to_master_store_isrc(self, mock_related, mock_get_track):
        """A request with no ISRC resolves its ISRC from the master tracks store."""
        mock_related.return_value = [
            SoundchartsTrack(title="Rel", artist="A", soundcharts_uuid="u1"),
        ]
        stored = MagicMock()
        stored.isrc = "USSTORE00001"
        mock_get_track.return_value = stored
        db = MagicMock()
        requests = [_make_request("Seed Artist", "Seed Song", isrc=None)]

        candidates, seeds_used = related_candidates_from_seeds(db, requests)

        assert seeds_used == 1
        assert len(candidates) == 1
        mock_related.assert_called_once_with("USSTORE00001", limit=20)

    @patch("app.services.recommendation.soundcharts_candidates.get_track")
    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_seed_without_resolvable_isrc_skipped(self, mock_related, mock_get_track):
        mock_get_track.return_value = None  # not in the master store either
        db = MagicMock()
        requests = [_make_request("Unknown", "Track", isrc=None)]

        candidates, seeds_used = related_candidates_from_seeds(db, requests)

        assert candidates == []
        assert seeds_used == 0
        mock_related.assert_not_called()

    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_cross_seed_dedup_by_uuid_and_name(self, mock_related):
        """The same related track returned for two seeds appears once."""
        mock_related.side_effect = [
            [SoundchartsTrack(title="Shared", artist="A", soundcharts_uuid="dup")],
            [
                SoundchartsTrack(title="Shared", artist="A", soundcharts_uuid="dup"),
                SoundchartsTrack(title="Fresh", artist="B", soundcharts_uuid="new"),
            ],
        ]
        db = MagicMock()
        requests = [
            _make_request("S1", "T1", isrc="USAAA0000001"),
            _make_request("S2", "T2", isrc="USBBB0000002"),
        ]

        candidates, seeds_used = related_candidates_from_seeds(db, requests)

        assert seeds_used == 2
        titles = sorted(c.title for c in candidates)
        assert titles == ["Fresh", "Shared"]

    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_empty_requests_returns_empty(self, mock_related):
        db = MagicMock()
        candidates, seeds_used = related_candidates_from_seeds(db, [])
        assert candidates == []
        assert seeds_used == 0
        mock_related.assert_not_called()

    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_max_seeds_caps_api_calls(self, mock_related):
        mock_related.return_value = []
        db = MagicMock()
        requests = [_make_request(f"A{i}", f"T{i}", isrc=f"USAAA000000{i}") for i in range(5)]

        _, seeds_used = related_candidates_from_seeds(db, requests, max_seeds=2)

        assert seeds_used == 2
        assert mock_related.call_count == 2

    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_per_seed_limit_forwarded(self, mock_related):
        mock_related.return_value = []
        db = MagicMock()
        requests = [_make_request("A", "T", isrc="USAAA0000001")]

        related_candidates_from_seeds(db, requests, per_seed_limit=7)

        mock_related.assert_called_once_with("USAAA0000001", limit=7)

    @patch("app.services.recommendation.soundcharts_candidates.get_related_songs_by_isrc")
    def test_early_exit_once_enough_candidates(self, mock_related):
        """Stops seeding once max_candidates is reached so a slow upstream can't
        serialize every seed's blocking calls into the request latency."""
        mock_related.return_value = [
            SoundchartsTrack(title="A", artist="X", soundcharts_uuid="ua"),
            SoundchartsTrack(title="B", artist="Y", soundcharts_uuid="ub"),
        ]
        db = MagicMock()
        requests = [_make_request(f"A{i}", f"T{i}", isrc=f"USAAA000000{i}") for i in range(5)]

        candidates, seeds_used = related_candidates_from_seeds(db, requests, max_candidates=2)

        # First seed yields 2 candidates == cap; the loop must not fetch more seeds.
        assert len(candidates) == 2
        assert seeds_used == 1
        assert mock_related.call_count == 1

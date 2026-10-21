"""Tests for track metadata enrichment from Tidal and Beatport."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.recommendation.enrichment import enrich_event_tracks
from app.services.tracks.enrichment import (
    enrich_from_beatport,
    enrich_from_tidal,
    enrich_track,
)
from app.services.tracks.profile import TrackProfile


def _make_user(tidal=True, beatport=True):
    user = MagicMock()
    user.tidal_access_token = "tok" if tidal else None
    user.tidal_refresh_token = "ref" if tidal else None
    user.beatport_access_token = "tok" if beatport else None
    return user


def _make_tidal_track(name="Test Track", artist_name="Test Artist", bpm=128, key="C maj"):
    track = MagicMock()
    track.name = name
    track.id = 12345
    track.bpm = bpm
    track.key = key
    track.duration = 300
    track.artist = SimpleNamespace(name=artist_name)
    track.album = MagicMock()
    track.album.name = "Test Album"
    track.album.image.return_value = "https://tidal.com/cover.jpg"
    return track


class TestEnrichFromTidal:
    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_returns_profile_on_match(self, mock_session):
        session = MagicMock()
        track = _make_tidal_track()
        session.search.return_value = {"tracks": [track]}
        mock_session.return_value = session

        db = MagicMock()
        user = _make_user()

        result = enrich_from_tidal(db, user, "Test Track", "Test Artist")
        assert result is not None
        assert result.source == "tidal"
        assert result.bpm == 128.0
        assert result.track_id == "12345"

    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_returns_none_when_no_session(self, mock_session):
        mock_session.return_value = None
        db = MagicMock()
        user = _make_user()
        assert enrich_from_tidal(db, user, "T", "A") is None

    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_returns_none_on_no_results(self, mock_session):
        session = MagicMock()
        session.search.return_value = {"tracks": []}
        mock_session.return_value = session
        db = MagicMock()
        user = _make_user()
        assert enrich_from_tidal(db, user, "Nonexistent", "Nobody") is None

    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_handles_missing_bpm(self, mock_session):
        session = MagicMock()
        track = _make_tidal_track(bpm=None)
        session.search.return_value = {"tracks": [track]}
        mock_session.return_value = session
        db = MagicMock()
        user = _make_user()

        result = enrich_from_tidal(db, user, "Test Track", "Test Artist")
        assert result is not None
        assert result.bpm is None

    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_handles_exception(self, mock_session):
        session = MagicMock()
        session.search.side_effect = Exception("API error")
        mock_session.return_value = session
        db = MagicMock()
        user = _make_user()
        assert enrich_from_tidal(db, user, "T", "A") is None


class TestEnrichFromBeatport:
    @patch("app.services.tracks.enrichment.search_beatport_tracks")
    def test_returns_profile_on_match(self, mock_search):
        from app.schemas.beatport import BeatportSearchResult

        mock_search.return_value = [
            BeatportSearchResult(
                track_id="999",
                title="Test Track",
                artist="Test Artist",
                genre="Tech House",
                bpm=126,
                key="8A",
                duration_seconds=360,
                cover_url="https://bp.com/cover.jpg",
                beatport_url="https://beatport.com/track/test/999",
            )
        ]
        db = MagicMock()
        user = _make_user()

        result = enrich_from_beatport(db, user, "Test Track", "Test Artist")
        assert result == TrackProfile(
            title="Test Track",
            artist="Test Artist",
            bpm=126.0,
            key="8A",
            genre="Tech House",
            source="beatport",
            track_id="999",
            url="https://beatport.com/track/test/999",
            cover_url="https://bp.com/cover.jpg",
            duration_seconds=360,
        )

    @patch("app.services.tracks.enrichment.search_beatport_tracks")
    def test_returns_none_on_no_results(self, mock_search):
        mock_search.return_value = []
        db = MagicMock()
        user = _make_user()
        assert enrich_from_beatport(db, user, "T", "A") is None

    @patch("app.services.tracks.enrichment.search_beatport_tracks")
    def test_returns_none_on_low_match(self, mock_search):
        from app.schemas.beatport import BeatportSearchResult

        mock_search.return_value = [
            BeatportSearchResult(
                track_id="1",
                title="Completely Different",
                artist="Unknown DJ",
            )
        ]
        db = MagicMock()
        user = _make_user()
        assert enrich_from_beatport(db, user, "My Song", "My Artist") is None


class TestEnrichTrack:
    @patch("app.services.tracks.enrichment.enrich_from_beatport")
    @patch("app.services.tracks.enrichment.enrich_from_tidal")
    def test_merges_both_sources(self, mock_tidal, mock_bp):
        mock_bp.return_value = TrackProfile(
            title="Track", artist="Artist", bpm=128.0, key=None, genre="House", source="beatport"
        )
        mock_tidal.return_value = TrackProfile(
            title="Track",
            artist="Artist",
            bpm=127.0,
            key="8A",
            source="tidal",
            cover_url="https://tidal.com/cover.jpg",
        )
        db = MagicMock()
        user = _make_user()

        result = enrich_track(db, user, "Track", "Artist")
        assert result.bpm == 128.0  # Beatport preferred
        assert result.key == "8A"  # Filled from Tidal
        assert result.genre == "House"  # From Beatport

    @patch("app.services.tracks.enrichment.enrich_from_beatport")
    @patch("app.services.tracks.enrichment.enrich_from_tidal")
    def test_beatport_only(self, mock_tidal, mock_bp):
        mock_bp.return_value = TrackProfile(
            title="Track", artist="Artist", bpm=128.0, genre="Techno", source="beatport"
        )
        mock_tidal.return_value = None
        db = MagicMock()
        user = _make_user()

        result = enrich_track(db, user, "Track", "Artist")
        assert result.source == "beatport"
        assert result.bpm == 128.0

    @patch("app.services.tracks.enrichment.enrich_from_beatport")
    @patch("app.services.tracks.enrichment.enrich_from_tidal")
    def test_tidal_only(self, mock_tidal, mock_bp):
        mock_bp.return_value = None
        mock_tidal.return_value = TrackProfile(
            title="Track", artist="Artist", bpm=130.0, key="9A", source="tidal"
        )
        db = MagicMock()
        user = _make_user()

        result = enrich_track(db, user, "Track", "Artist")
        assert result.source == "tidal"
        assert result.bpm == 130.0

    @patch("app.services.tracks.enrichment.enrich_from_beatport")
    @patch("app.services.tracks.enrichment.enrich_from_tidal")
    def test_neither_service(self, mock_tidal, mock_bp):
        mock_bp.return_value = None
        mock_tidal.return_value = None
        db = MagicMock()
        user = _make_user()

        result = enrich_track(db, user, "Unknown", "Unknown")
        assert result.title == "Unknown"
        assert result.artist == "Unknown"
        assert result.bpm is None

    def test_skips_beatport_when_not_connected(self):
        db = MagicMock()
        user = _make_user(beatport=False, tidal=False)
        with (
            patch("app.services.tracks.enrichment.enrich_from_beatport") as mock_bp,
            patch("app.services.tracks.enrichment.enrich_from_tidal") as mock_tidal,
        ):
            mock_bp.return_value = None
            mock_tidal.return_value = None
            result = enrich_track(db, user, "T", "A")
            mock_bp.assert_not_called()
            mock_tidal.assert_not_called()
            assert result.title == "T"


class TestEnrichEventTracks:
    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_enriches_list_no_stored_metadata(self, mock_enrich):
        mock_enrich.return_value = TrackProfile(title="T", artist="A", bpm=128.0)
        db = MagicMock()
        user = _make_user()

        requests = [
            SimpleNamespace(
                song_title="Song 1", artist="Artist 1", genre=None, bpm=None, musical_key=None
            ),
            SimpleNamespace(
                song_title="Song 2", artist="Artist 2", genre=None, bpm=None, musical_key=None
            ),
        ]
        result = enrich_event_tracks(db, user, requests)
        assert len(result) == 2
        assert mock_enrich.call_count == 2

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_skips_api_when_all_metadata_stored(self, mock_enrich):
        """Requests with genre + bpm + musical_key should skip API calls."""
        db = MagicMock()
        user = _make_user()

        requests = [
            SimpleNamespace(
                song_title="Country Road",
                artist="John Denver",
                genre="Country",
                bpm=110.0,
                musical_key="G Major",
            ),
        ]
        result = enrich_event_tracks(db, user, requests)
        assert len(result) == 1
        mock_enrich.assert_not_called()
        assert result[0].genre == "Country"
        assert result[0].bpm == 110.0
        assert result[0].key == "G Major"
        assert result[0].title == "Country Road"

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_partial_metadata_fills_from_api(self, mock_enrich):
        """Requests with partial metadata should only use API for missing fields."""
        mock_enrich.return_value = TrackProfile(
            title="Song",
            artist="Artist",
            bpm=125.0,
            key="8A",
            genre="House",
            source="beatport",
            track_id="123",
            url="https://beatport.com/track/123",
            cover_url="https://beatport.com/cover.jpg",
            duration_seconds=300,
        )
        db = MagicMock()
        user = _make_user()

        requests = [
            SimpleNamespace(
                song_title="Song",
                artist="Artist",
                genre="Hip Hop",  # has genre
                bpm=None,  # missing bpm
                musical_key=None,  # missing key
            ),
        ]
        result = enrich_event_tracks(db, user, requests)
        assert len(result) == 1
        assert mock_enrich.call_count == 1
        # Genre from stored metadata, BPM and key from API
        assert result[0].genre == "Hip Hop"
        assert result[0].bpm == 125.0
        assert result[0].key == "8A"
        assert result[0].source == "beatport"

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_partial_metadata_uses_stored_bpm(self, mock_enrich):
        """Stored BPM should be used even when genre/key come from API."""
        mock_enrich.return_value = TrackProfile(
            title="Song", artist="Artist", bpm=999.0, key="5B", genre="Techno", source="tidal"
        )
        db = MagicMock()
        user = _make_user()

        requests = [
            SimpleNamespace(
                song_title="Song",
                artist="Artist",
                genre=None,
                bpm=95.0,  # stored BPM
                musical_key=None,
            ),
        ]
        result = enrich_event_tracks(db, user, requests)
        assert result[0].bpm == 95.0  # Stored, not API's 999.0
        assert result[0].genre == "Techno"  # From API
        assert result[0].key == "5B"  # From API

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_mixed_requests(self, mock_enrich):
        """Mix of full, partial, and no metadata requests."""
        mock_enrich.return_value = TrackProfile(
            title="T", artist="A", bpm=128.0, key="8A", genre="House", source="beatport"
        )
        db = MagicMock()
        user = _make_user()

        requests = [
            # Full metadata — no API call
            SimpleNamespace(
                song_title="Full", artist="A", genre="Country", bpm=100.0, musical_key="C Major"
            ),
            # No metadata — full API call
            SimpleNamespace(song_title="Empty", artist="A", genre=None, bpm=None, musical_key=None),
            # Partial — API call for missing fields
            SimpleNamespace(
                song_title="Partial", artist="A", genre="Pop", bpm=None, musical_key=None
            ),
        ]
        result = enrich_event_tracks(db, user, requests)
        assert len(result) == 3
        assert mock_enrich.call_count == 2  # Called for Empty and Partial only
        assert result[0].genre == "Country"
        assert result[0].source == "unknown"  # No API call, default source

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_caps_at_30(self, mock_enrich):
        mock_enrich.return_value = TrackProfile(title="T", artist="A")
        db = MagicMock()
        user = _make_user()

        requests = [
            SimpleNamespace(
                song_title=f"S{i}", artist=f"A{i}", genre=None, bpm=None, musical_key=None
            )
            for i in range(50)
        ]
        result = enrich_event_tracks(db, user, requests)
        assert len(result) == 30
        assert mock_enrich.call_count == 30

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_empty_requests(self, mock_enrich):
        db = MagicMock()
        user = _make_user()
        result = enrich_event_tracks(db, user, [])
        assert result == []
        mock_enrich.assert_not_called()

    @patch("app.services.recommendation.enrichment.enrich_track")
    def test_legacy_requests_without_metadata_attrs(self, mock_enrich):
        """Requests without genre/bpm/musical_key attrs should fall through to API."""
        mock_enrich.return_value = TrackProfile(title="T", artist="A", bpm=128.0)
        db = MagicMock()
        user = _make_user()

        requests = [
            SimpleNamespace(song_title="Song 1", artist="Artist 1"),
        ]
        result = enrich_event_tracks(db, user, requests)
        assert len(result) == 1
        assert mock_enrich.call_count == 1


class TestEnrichVersionPreference:
    """Tests for original-preference scoring in enrichment functions."""

    @patch("app.services.tracks.enrichment.search_beatport_tracks")
    def test_beatport_prefers_original_over_remix(self, mock_search):
        """Beatport enrichment prefers Original Mix over remix for non-remix queries."""
        from app.schemas.beatport import BeatportSearchResult

        mock_search.return_value = [
            BeatportSearchResult(
                track_id="1",
                title="Surrender",
                artist="Darude",
                mix_name="Hardstyle Remix",
                bpm=165,
                key="A Minor",
            ),
            BeatportSearchResult(
                track_id="2",
                title="Surrender",
                artist="Darude",
                mix_name="Original Mix",
                bpm=132,
                key="B Minor",
            ),
        ]
        db = MagicMock()
        user = _make_user()

        result = enrich_from_beatport(db, user, "Surrender", "Darude")
        assert result is not None
        assert result.bpm == 132.0  # Original Mix, not Hardstyle Remix's 165

    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_tidal_penalizes_remix_for_original_query(self, mock_session):
        """Tidal enrichment penalizes remix results when searching for an original."""
        session = MagicMock()
        original = _make_tidal_track(name="Surrender", artist_name="Darude", bpm=132)
        remix = _make_tidal_track(name="Surrender (Hardstyle Remix)", artist_name="Darude", bpm=165)
        session.search.return_value = {"tracks": [remix, original]}
        mock_session.return_value = session

        db = MagicMock()
        user = _make_user()

        result = enrich_from_tidal(db, user, "Surrender", "Darude")
        assert result is not None
        assert result.bpm == 132.0  # Original, not remix's 165

    @patch("app.services.tracks.enrichment.get_tidal_session")
    def test_artwork_failure_keeps_metadata_and_logs_only_exception_class(
        self, mock_session, caplog
    ):
        # Regression: 57cfcdc6867f silently swallowed unexpected artwork failures.
        session = MagicMock()
        track = _make_tidal_track(name="Private Track", artist_name="Private Artist")
        track.album.image.side_effect = RuntimeError("https://private.example/artwork?token=secret")
        session.search.return_value = {"tracks": [track]}
        mock_session.return_value = session

        result = enrich_from_tidal(MagicMock(), _make_user(), "Private Track", "Private Artist")

        assert result is not None
        assert result.title == "Private Track"
        assert result.cover_url is None
        artwork_logs = [
            record for record in caplog.records if record.name == "app.services.tracks.enrichment"
        ]
        assert [record.getMessage() for record in artwork_logs] == [
            "Tidal artwork lookup failed: RuntimeError"
        ]

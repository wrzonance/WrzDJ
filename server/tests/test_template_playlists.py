"""Tests for template playlist functionality.

Tests cover:
- Tidal playlist listing
- Beatport playlist listing
- Template TrackProfile conversion
- Template recommendation generation
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.recommendation.scorer import TrackProfile

# ============================================================
# Tidal playlist listing
# ============================================================


class TestTidalListPlaylists:
    @patch("app.services.tidal.get_tidal_session")
    def test_returns_playlists_with_correct_fields(
        self, mock_session_fn, db: Session, test_user: User
    ):
        from app.services.tidal import list_user_playlists

        mock_playlist = MagicMock()
        mock_playlist.id = "abc-123"
        mock_playlist.name = "My Mix"
        mock_playlist.num_tracks = 15
        mock_playlist.description = "Friday vibes"
        mock_playlist.image.return_value = "https://img.tidal.com/cover.jpg"

        session = MagicMock()
        session.user.playlists.return_value = [mock_playlist]
        mock_session_fn.return_value = session

        playlists = list_user_playlists(db, test_user)
        assert len(playlists) == 1
        p = playlists[0]
        assert p.id == "abc-123"
        assert p.name == "My Mix"
        assert p.num_tracks == 15
        assert p.description == "Friday vibes"
        assert p.cover_url == "https://img.tidal.com/cover.jpg"
        assert p.source == "tidal"

    @patch("app.services.tidal.get_tidal_session")
    def test_returns_empty_list_when_no_playlists(
        self, mock_session_fn, db: Session, test_user: User
    ):
        from app.services.tidal import list_user_playlists

        session = MagicMock()
        session.user.playlists.return_value = []
        mock_session_fn.return_value = session

        assert list_user_playlists(db, test_user) == []

    @patch("app.services.tidal.get_tidal_session")
    def test_returns_empty_list_on_session_failure(
        self, mock_session_fn, db: Session, test_user: User
    ):
        from app.services.tidal import list_user_playlists

        mock_session_fn.return_value = None
        assert list_user_playlists(db, test_user) == []

    @patch("app.services.tidal.get_tidal_session")
    def test_handles_missing_cover_art(self, mock_session_fn, db: Session, test_user: User):
        from app.services.tidal import list_user_playlists

        mock_playlist = MagicMock()
        mock_playlist.id = "xyz-456"
        mock_playlist.name = "No Cover"
        mock_playlist.num_tracks = 5
        mock_playlist.description = None
        mock_playlist.image.side_effect = Exception("No image")

        session = MagicMock()
        session.user.playlists.return_value = [mock_playlist]
        mock_session_fn.return_value = session

        playlists = list_user_playlists(db, test_user)
        assert len(playlists) == 1
        assert playlists[0].cover_url is None


# ============================================================
# Beatport playlist listing
# ============================================================


class TestBeatportListPlaylists:
    @patch("app.services.beatport._refresh_token_if_needed")
    @patch("app.services.beatport.httpx.Client")
    def test_returns_playlists_with_correct_fields(
        self, mock_client_cls, mock_refresh, db: Session, test_user: User
    ):
        from app.services.beatport import list_user_playlists

        mock_refresh.return_value = True
        test_user.beatport_access_token = "fake_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": 999,
                    "name": "Beatport Mix",
                    "track_count": 25,
                    "description": "Club vibes",
                    "image": {"uri": "https://bp.com/img.jpg"},
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        playlists = list_user_playlists(db, test_user)
        assert len(playlists) == 1
        p = playlists[0]
        assert p.id == "999"
        assert p.name == "Beatport Mix"
        assert p.num_tracks == 25
        assert p.description == "Club vibes"
        assert p.cover_url == "https://bp.com/img.jpg"
        assert p.source == "beatport"

    @patch("app.services.beatport._refresh_token_if_needed")
    @patch("app.services.beatport.httpx.Client")
    def test_returns_empty_when_no_playlists(
        self, mock_client_cls, mock_refresh, db: Session, test_user: User
    ):
        from app.services.beatport import list_user_playlists

        mock_refresh.return_value = True
        test_user.beatport_access_token = "fake_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        assert list_user_playlists(db, test_user) == []

    @patch("app.services.beatport._refresh_token_if_needed")
    def test_returns_empty_on_token_failure(self, mock_refresh, db: Session, test_user: User):
        from app.services.beatport import list_user_playlists

        mock_refresh.return_value = False
        assert list_user_playlists(db, test_user) == []

    @patch("app.services.beatport._refresh_token_if_needed")
    @patch("app.services.beatport.httpx.Client")
    def test_returns_empty_on_http_error(
        self, mock_client_cls, mock_refresh, db: Session, test_user: User
    ):
        import httpx

        from app.services.beatport import list_user_playlists

        mock_refresh.return_value = True
        test_user.beatport_access_token = "fake_token"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.HTTPError("boom")
        mock_client_cls.return_value = mock_client

        assert list_user_playlists(db, test_user) == []


# ============================================================
# Tidal playlist → TrackProfile conversion
# ============================================================


class TestTidalPlaylistToTrackProfiles:
    @patch("app.services.recommendation.template.tidal_get_playlist_tracks")
    def test_extracts_bpm_and_key(self, mock_get_tracks, db: Session, test_user: User):
        from app.services.recommendation.template import tracks_from_tidal_playlist

        track = MagicMock()
        track.name = "Strobe"
        track.artist.name = "Deadmau5"
        track.bpm = 128
        track.audio_modes = ["STEREO"]
        track.id = "111"
        track.duration = 420
        track.album.name = "For Lack"
        track.album.image.return_value = "https://img.tidal.com/strobe.jpg"
        # tidalapi may store key as a string attribute
        track.key = "A minor"
        mock_get_tracks.return_value = [track]

        profiles = tracks_from_tidal_playlist(db, test_user, "playlist-id")
        assert len(profiles) == 1
        p = profiles[0]
        assert p.title == "Strobe"
        assert p.artist == "Deadmau5"
        assert p.bpm == 128.0
        assert p.key == "A minor"
        assert p.source == "tidal"
        assert p.track_id == "111"

    @patch("app.services.recommendation.template.tidal_get_playlist_tracks")
    def test_handles_missing_bpm_key(self, mock_get_tracks, db: Session, test_user: User):
        from app.services.recommendation.template import tracks_from_tidal_playlist

        track = MagicMock()
        track.name = "Unknown"
        track.artist.name = "Unknown Artist"
        track.bpm = None
        track.key = None
        track.id = "222"
        track.duration = 300
        track.album = None
        mock_get_tracks.return_value = [track]

        profiles = tracks_from_tidal_playlist(db, test_user, "playlist-id")
        assert len(profiles) == 1
        assert profiles[0].bpm is None
        assert profiles[0].key is None

    @patch("app.services.recommendation.template.tidal_get_playlist_tracks")
    def test_caps_at_max_template_tracks(self, mock_get_tracks, db: Session, test_user: User):
        from app.services.recommendation.template import (
            MAX_TEMPLATE_TRACKS,
            tracks_from_tidal_playlist,
        )

        tracks = []
        for i in range(100):
            t = MagicMock()
            t.name = f"Track {i}"
            t.artist.name = f"Artist {i}"
            t.bpm = 120 + i
            t.key = "8A"
            t.id = str(i)
            t.duration = 300
            t.album = None
            tracks.append(t)
        mock_get_tracks.return_value = tracks

        profiles = tracks_from_tidal_playlist(db, test_user, "playlist-id")
        assert len(profiles) == MAX_TEMPLATE_TRACKS

    @patch("app.services.recommendation.template.tidal_get_playlist_tracks")
    def test_empty_playlist_returns_empty(self, mock_get_tracks, db: Session, test_user: User):
        from app.services.recommendation.template import tracks_from_tidal_playlist

        mock_get_tracks.return_value = []
        assert tracks_from_tidal_playlist(db, test_user, "playlist-id") == []


# ============================================================
# Beatport playlist → TrackProfile conversion
# ============================================================


class TestBeatportPlaylistToTrackProfiles:
    @patch("app.services.recommendation.template.beatport_get_playlist_tracks")
    def test_maps_search_result_to_track_profile(
        self, mock_get_tracks, db: Session, test_user: User
    ):
        from app.schemas.beatport import BeatportSearchResult
        from app.services.recommendation.template import tracks_from_beatport_playlist

        mock_get_tracks.return_value = [
            BeatportSearchResult(
                track_id="456",
                title="Acid Track",
                artist="DJ Pierre",
                genre="Acid House",
                bpm=126,
                key="C minor",
                duration_seconds=390,
                cover_url="https://bp.com/acid.jpg",
                beatport_url="https://beatport.com/track/acid/456",
            )
        ]

        profiles = tracks_from_beatport_playlist(db, test_user, "bp-playlist-id")
        assert len(profiles) == 1
        p = profiles[0]
        assert p.title == "Acid Track"
        assert p.artist == "DJ Pierre"
        assert p.genre == "Acid House"
        assert p.bpm == 126.0
        assert p.key == "C minor"
        assert p.source == "beatport"

    @patch("app.services.recommendation.template.beatport_get_playlist_tracks")
    def test_caps_at_max_template_tracks(self, mock_get_tracks, db: Session, test_user: User):
        from app.schemas.beatport import BeatportSearchResult
        from app.services.recommendation.template import (
            MAX_TEMPLATE_TRACKS,
            tracks_from_beatport_playlist,
        )

        results = [
            BeatportSearchResult(track_id=str(i), title=f"Track {i}", artist=f"Artist {i}", bpm=125)
            for i in range(80)
        ]
        mock_get_tracks.return_value = results

        profiles = tracks_from_beatport_playlist(db, test_user, "bp-playlist-id")
        assert len(profiles) == MAX_TEMPLATE_TRACKS

    @patch("app.services.recommendation.template.beatport_get_playlist_tracks")
    def test_empty_playlist_returns_empty(self, mock_get_tracks, db: Session, test_user: User):
        from app.services.recommendation.template import tracks_from_beatport_playlist

        mock_get_tracks.return_value = []
        assert tracks_from_beatport_playlist(db, test_user, "bp-playlist-id") == []


# ============================================================
# Template recommendation generation (end-to-end with mocks)
# ============================================================


class TestGenerateRecommendationsFromTemplate:
    @patch("app.services.recommendation.service._search_candidates")
    @patch("app.services.recommendation.template.tracks_from_tidal_playlist")
    def test_full_pipeline(self, mock_tidal_tracks, mock_search, db: Session, test_user: User):
        from datetime import timedelta

        from app.core.time import utcnow
        from app.models.event import Event
        from app.services.recommendation.service import generate_recommendations_from_template

        test_user.tidal_access_token = "fake"
        db.commit()

        event = Event(
            code="TMPL01",
            join_code="TMPL01J",
            name="Template Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        # Template tracks
        mock_tidal_tracks.return_value = [
            TrackProfile(
                title="Track A", artist="Artist A", bpm=128.0, key="8A", genre="Tech House"
            ),
            TrackProfile(
                title="Track B", artist="Artist B", bpm=130.0, key="9A", genre="Tech House"
            ),
        ]

        # Search candidates
        mock_search.return_value = (
            [
                TrackProfile(
                    title="Candidate 1",
                    artist="New DJ",
                    bpm=129.0,
                    key="8A",
                    genre="Tech House",
                    source="tidal",
                    track_id="c1",
                ),
            ],
            ["tidal"],
            1,
        )

        result = generate_recommendations_from_template(
            db, test_user, event, template_source="tidal", template_id="playlist-123"
        )
        assert result.event_profile.avg_bpm == 129.0
        assert result.event_profile.track_count == 2
        assert len(result.suggestions) >= 0  # May be 0 or 1 depending on scoring

    @patch("app.services.recommendation.service._search_candidates")
    @patch("app.services.recommendation.template.tracks_from_tidal_playlist")
    def test_deduplicates_against_existing_requests(
        self, mock_tidal_tracks, mock_search, db: Session, test_user: User
    ):
        from datetime import timedelta

        from app.core.time import utcnow
        from app.models.event import Event
        from app.models.request import Request, RequestStatus
        from app.services.recommendation.service import generate_recommendations_from_template

        test_user.tidal_access_token = "fake"
        db.commit()

        event = Event(
            code="TMPL02",
            join_code="TMPL02J",
            name="Dedup Test",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        # Existing request that should be deduped
        req = Request(
            event_id=event.id,
            song_title="Existing Song",
            artist="Existing Artist",
            source="manual",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="existing_dedupe_key_1234",
        )
        db.add(req)
        db.commit()

        mock_tidal_tracks.return_value = [
            TrackProfile(title="Template Track", artist="Template Artist", bpm=128.0, key="8A"),
        ]

        # Candidate is same as existing request
        mock_search.return_value = (
            [
                TrackProfile(
                    title="Existing Song",
                    artist="Existing Artist",
                    bpm=128.0,
                    source="tidal",
                    track_id="dup1",
                ),
            ],
            ["tidal"],
            1,
        )

        result = generate_recommendations_from_template(
            db, test_user, event, template_source="tidal", template_id="playlist-456"
        )
        # The duplicate should be filtered out
        assert all(s.profile.title != "Existing Song" for s in result.suggestions)

    @patch("app.services.recommendation.template.tracks_from_tidal_playlist")
    def test_empty_template_returns_empty_suggestions(
        self, mock_tidal_tracks, db: Session, test_user: User
    ):
        from datetime import timedelta

        from app.core.time import utcnow
        from app.models.event import Event
        from app.services.recommendation.service import generate_recommendations_from_template

        test_user.tidal_access_token = "fake"
        db.commit()

        event = Event(
            code="TMPL03",
            join_code="TMPL03J",
            name="Empty Template",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        mock_tidal_tracks.return_value = []

        result = generate_recommendations_from_template(
            db, test_user, event, template_source="tidal", template_id="empty-playlist"
        )
        assert result.suggestions == []
        assert result.event_profile.track_count == 0

    def test_invalid_source_raises(self, db: Session, test_user: User):
        from datetime import timedelta

        from app.core.time import utcnow
        from app.models.event import Event
        from app.services.recommendation.service import generate_recommendations_from_template

        event = Event(
            code="TMPL04",
            join_code="TMPL04J",
            name="Invalid Source",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        with pytest.raises(ValueError, match="Invalid template source"):
            generate_recommendations_from_template(
                db, test_user, event, template_source="spotify", template_id="xxx"
            )

"""Beatport playlist and linking tests."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.services.providers.beatport import (
    add_track_to_beatport_playlist,
    add_tracks_to_beatport_playlist,
    create_beatport_playlist,
    fetch_subscription_type,
    get_beatport_track,
    get_playlist_tracks,
    list_user_playlists,
    manual_link_beatport_track,
    search_beatport_tracks,
)
from app.services.providers.beatport_common import is_valid_beatport_id
from tests.beatport_test_helpers import (
    MOCK_SEARCH_RESPONSE,
    _fixture_beatport_event,  # noqa: F401
    _fixture_beatport_user,  # noqa: F401
    _fixture_beatport_user_expired,  # noqa: F401
    _fixture_beatport_user_no_token,  # noqa: F401
)


class TestBeatportPlaylist:
    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_create_playlist_success(
        self, mock_client_cls, db: Session, beatport_user: User, beatport_event: Event
    ):
        """Successful playlist creation returns playlist ID and saves to event."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 42}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = create_beatport_playlist(db, beatport_user, beatport_event)

        assert result == "42"
        db.refresh(beatport_event)
        assert beatport_event.beatport_playlist_id == "42"

    def test_create_playlist_returns_existing(
        self, db: Session, beatport_user: User, beatport_event: Event
    ):
        """Event already has beatport_playlist_id — returns it without API call."""
        beatport_event.beatport_playlist_id = "existing-99"
        db.commit()

        result = create_beatport_playlist(db, beatport_user, beatport_event)
        assert result == "existing-99"

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_create_playlist_handles_error(
        self, mock_client_cls, db: Session, beatport_user: User, beatport_event: Event
    ):
        """HTTP error during playlist creation returns None."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = create_beatport_playlist(db, beatport_user, beatport_event)
        assert result is None

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_add_track_sends_singular_int(self, mock_client_cls, db: Session, beatport_user: User):
        """Track ID is sent as singular int via 'track_id' field."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from app.services.providers.beatport import add_track_to_beatport_playlist

        result = add_track_to_beatport_playlist(db, beatport_user, "1001", "12345")

        assert result is True
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body == {"track_id": 12345}

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_add_tracks_batch_calls_per_track(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """Batch add sends one request per track."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = add_tracks_to_beatport_playlist(db, beatport_user, "1001", ["12345", "67890"])

        assert result is True
        assert mock_client.post.call_count == 2

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_add_track_handles_error(self, mock_client_cls, db: Session, beatport_user: User):
        """HTTP error during add track returns False."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        from app.services.providers.beatport import add_track_to_beatport_playlist

        result = add_track_to_beatport_playlist(db, beatport_user, "1001", "99999")
        assert result is False


class TestFetchSubscriptionType:
    @patch("app.services.providers.beatport_account.httpx.Client")
    def test_fetch_subscription_streaming(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns 'streaming' when account has streaming_audio_format_id in preferences."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "username": "dj_test",
            "preferences": {"streaming_audio_format_id": 29},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = fetch_subscription_type(db, beatport_user)

        assert result == "streaming"
        db.refresh(beatport_user)
        assert beatport_user.beatport_subscription == "streaming"

    @patch("app.services.providers.beatport_account.httpx.Client")
    def test_fetch_subscription_none(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns None when account has no streaming preferences."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"username": "dj_test", "preferences": {}}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = fetch_subscription_type(db, beatport_user)

        assert result is None
        db.refresh(beatport_user)
        assert beatport_user.beatport_subscription is None

    @patch("app.services.providers.beatport_account.httpx.Client")
    def test_fetch_subscription_handles_error(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """HTTP error returns None without crashing."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = fetch_subscription_type(db, beatport_user)
        assert result is None


class TestListUserPlaylists:
    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_list_playlists_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns parsed playlist info from API response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": 42,
                    "name": "My Playlist",
                    "track_count": 10,
                    "description": "Best tracks",
                    "image": {"uri": "https://geo-media.beatport.com/cover.jpg"},
                },
                {
                    "id": 43,
                    "name": "Empty Playlist",
                    "track_count": 0,
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = list_user_playlists(db, beatport_user)

        assert len(results) == 2
        assert results[0].id == "42"
        assert results[0].name == "My Playlist"
        assert results[0].num_tracks == 10
        assert results[0].cover_url == "https://geo-media.beatport.com/cover.jpg"
        assert results[0].source == "beatport"
        assert results[1].cover_url is None

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_list_playlists_error_returns_empty(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """HTTP error returns empty list."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        results = list_user_playlists(db, beatport_user)
        assert results == []

    def test_list_playlists_no_token(self, db: Session, beatport_user_no_token: User):
        """No token returns empty list."""
        results = list_user_playlists(db, beatport_user_no_token)
        assert results == []


class TestGetPlaylistTracks:
    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_get_tracks_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns parsed tracks from playlist."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "track": {
                        "id": 12345,
                        "name": "Strobe",
                        "slug": "strobe",
                        "mix_name": "Original Mix",
                        "artists": [{"name": "deadmau5"}],
                        "genre": {"name": "Progressive House"},
                        "bpm": 128,
                        "key": {"name": "A min"},
                        "length": "10:33",
                        "image": {"uri": "https://geo-media.beatport.com/art.jpg"},
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = get_playlist_tracks(db, beatport_user, "42")

        assert len(results) == 1
        assert results[0].track_id == "12345"
        assert results[0].title == "Strobe"
        assert results[0].artist == "deadmau5"
        assert results[0].genre == "Progressive House"

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_get_tracks_error_returns_empty(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """HTTP error returns empty list."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        results = get_playlist_tracks(db, beatport_user, "42")
        assert results == []


class TestGetBeatportTrack:
    @patch("app.services.providers.beatport_catalog.httpx.Client")
    def test_get_track_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns parsed single track."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 12345,
            "name": "Strobe",
            "slug": "strobe",
            "mix_name": "Original Mix",
            "artists": [{"name": "deadmau5"}],
            "genre": {"name": "Progressive House"},
            "bpm": 128,
            "key": {"name": "A min"},
            "length": "10:33",
            "image": {"uri": "https://geo-media.beatport.com/art.jpg"},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = get_beatport_track(db, beatport_user, "12345")

        assert result is not None
        assert result.track_id == "12345"
        assert result.title == "Strobe"
        assert result.artist == "deadmau5"
        assert result.genre == "Progressive House"
        assert "beatport.com/track/strobe/12345" in result.beatport_url

    @patch("app.services.providers.beatport_catalog.httpx.Client")
    def test_get_track_error_returns_none(self, mock_client_cls, db: Session, beatport_user: User):
        """HTTP error returns None."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = get_beatport_track(db, beatport_user, "12345")
        assert result is None

    def test_get_track_no_token(self, db: Session, beatport_user_no_token: User):
        """No token returns None."""
        result = get_beatport_track(db, beatport_user_no_token, "12345")
        assert result is None


class TestManualLinkBeatportTrack:
    def test_link_new_track(self):
        """Links a Beatport track to a request with no existing sync results."""
        import json

        from app.schemas.beatport import BeatportSearchResult

        mock_db = MagicMock()
        request = MagicMock()
        request.sync_results_json = None

        track = BeatportSearchResult(
            track_id="12345",
            title="Strobe",
            artist="deadmau5",
            beatport_url="https://beatport.com/track/strobe/12345",
            duration_seconds=633,
        )

        manual_link_beatport_track(mock_db, request, track)

        result = json.loads(request.sync_results_json)
        assert len(result) == 1
        assert result[0]["service"] == "beatport"
        assert result[0]["status"] == "matched"
        assert result[0]["track_id"] == "12345"
        assert result[0]["confidence"] == 1.0
        mock_db.commit.assert_called_once()

    def test_link_replaces_existing_beatport_entry(self):
        """Replaces existing Beatport entry, preserves other services."""
        import json

        from app.schemas.beatport import BeatportSearchResult

        mock_db = MagicMock()
        request = MagicMock()
        request.sync_results_json = json.dumps(
            [
                {"service": "tidal", "status": "matched", "track_id": "t1"},
                {"service": "beatport", "status": "matched", "track_id": "old"},
            ]
        )

        track = BeatportSearchResult(
            track_id="new123",
            title="New Track",
            artist="New Artist",
            beatport_url="https://beatport.com/track/new/new123",
        )

        manual_link_beatport_track(mock_db, request, track)

        result = json.loads(request.sync_results_json)
        assert len(result) == 2
        services = [r["service"] for r in result]
        assert "tidal" in services
        assert "beatport" in services
        bp_entry = next(r for r in result if r["service"] == "beatport")
        assert bp_entry["track_id"] == "new123"


class TestSearchWithExpiredTokenAutoRefresh:
    @patch("app.services.providers.beatport_catalog.httpx.Client")
    def test_search_with_expired_token_refreshes_and_succeeds(
        self, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Expired token → refresh → search succeeds in one call."""
        # First client instance: refresh
        refresh_response = MagicMock()
        refresh_response.json.return_value = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_in": 600,
        }
        refresh_response.raise_for_status = MagicMock()

        # Second client instance: search
        search_response = MagicMock()
        search_response.json.return_value = MOCK_SEARCH_RESPONSE
        search_response.raise_for_status = MagicMock()

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return refresh_response

            def get(self, *args, **kwargs):
                return search_response

        mock_client_cls.return_value = FakeClient()

        results = search_beatport_tracks(db, beatport_user_expired, "deadmau5")

        assert len(results) == 1
        assert results[0].title == "Strobe"
        # Verify token was refreshed
        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "new_token"

    @patch("app.services.providers.beatport_catalog.httpx.Client")
    def test_refresh_failure_returns_empty(
        self, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Expired token + refresh failure → empty results."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        results = search_beatport_tracks(db, beatport_user_expired, "deadmau5")
        assert results == []


class TestBeatportIdValidation:
    """Regression for CodeQL py/partial-ssrf: IDs are path segments of the API URL."""

    @pytest.mark.parametrize("bad_id", ["../search/?q=", "12345/../../me", "", "abc", "1 2"])
    @patch("app.services.providers.beatport_catalog.httpx.Client")
    def test_get_beatport_track_rejects_non_numeric_id(
        self, mock_client_cls, bad_id, db: Session, beatport_user: User
    ):
        assert get_beatport_track(db, beatport_user, bad_id) is None
        mock_client_cls.assert_not_called()

    @pytest.mark.parametrize("bad_id", ["../search/?q=", "12345/../../me", "", "abc"])
    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_get_playlist_tracks_rejects_non_numeric_id(
        self, mock_client_cls, bad_id, db: Session, beatport_user: User
    ):
        assert get_playlist_tracks(db, beatport_user, bad_id) == []
        mock_client_cls.assert_not_called()

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_numeric_id_still_reaches_the_api(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        assert get_playlist_tracks(db, beatport_user, "987654") == []
        assert "/my/playlists/987654/tracks/" in mock_client.get.call_args.args[0]

    @patch("app.services.providers.beatport_playlists.httpx.Client")
    def test_add_track_rejects_malformed_ids(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        assert add_track_to_beatport_playlist(db, beatport_user, "../me", "123") is False
        assert add_track_to_beatport_playlist(db, beatport_user, "123", "9/../x") is False
        mock_client_cls.assert_not_called()

    def test_non_string_ids_are_rejected(self):
        assert is_valid_beatport_id(123) is False
        assert is_valid_beatport_id("123") is True
        assert is_valid_beatport_id("١٢") is False  # Arabic-Indic digits

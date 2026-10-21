"""Tidal catalog APIs bind their provider session and result converter."""

from unittest.mock import MagicMock, patch

import tidalapi

from app.schemas.tidal import TidalSearchResult
from app.services.providers import tidal_catalog


@patch("app.services.providers.tidal_catalog.track_to_result")
@patch("app.services.providers.tidal_catalog.get_tidal_session")
def test_catalog_search_binds_session_and_track_converter(get_session, convert, db, test_user):
    track = MagicMock()
    expected = TidalSearchResult(track_id="42", title="Track", artist="Artist")
    session = MagicMock()
    session.search.return_value = {"tracks": [track]}
    get_session.return_value = session
    convert.return_value = expected

    results = tidal_catalog.search_tidal_tracks(db, test_user, "query", limit=3)

    assert results == [expected]
    session.search.assert_called_once_with("query", models=[tidalapi.media.Track], limit=3)
    convert.assert_called_once_with(track)


@patch("app.services.providers.tidal_catalog.track_to_result")
@patch("app.services.providers.tidal_catalog.get_tidal_session")
def test_catalog_playlist_fetch_paginates_and_converts(get_session, convert, db, test_user):
    first_page = [MagicMock() for _ in range(100)]
    final_track = MagicMock()
    expected = TidalSearchResult(track_id="101", title="Last", artist="Artist")
    session = MagicMock()
    session.playlist.return_value.tracks.side_effect = [first_page, [final_track]]
    get_session.return_value = session
    convert.side_effect = [expected] * 101

    results = tidal_catalog.get_playlist_tracks(db, test_user, "playlist-1")

    assert results == [expected] * 101
    assert session.playlist.return_value.tracks.call_args_list == [
        ((), {"limit": 100, "offset": 0}),
        ((), {"limit": 100, "offset": 100}),
    ]
    assert convert.call_count == 101

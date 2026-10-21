"""Regression for baseline 57cfcdc6867f: Beatport workflows have clear boundaries."""

from importlib.util import find_spec


def test_beatport_workflow_modules_have_canonical_import_boundaries():
    module_names = (
        "app.services.providers.beatport_account",
        "app.services.providers.beatport_catalog",
        "app.services.providers.beatport_playlists",
        "app.services.providers.beatport_manual_link",
        "app.services.providers.beatport_common",
    )

    assert all(find_spec(name) is not None for name in module_names)


def test_beatport_facade_preserves_public_workflow_imports():
    from app.services.providers import (
        beatport,
        beatport_account,
        beatport_catalog,
        beatport_manual_link,
        beatport_playlists,
    )

    assert beatport.login_and_get_tokens is beatport_account.login_and_get_tokens
    assert beatport.disconnect_beatport is beatport_account.disconnect_beatport
    assert beatport.search_beatport_tracks is beatport_catalog.search_beatport_tracks
    assert beatport.get_beatport_track is beatport_catalog.get_beatport_track
    assert beatport.list_user_playlists is beatport_playlists.list_user_playlists
    assert beatport.get_playlist_tracks is beatport_playlists.get_playlist_tracks
    assert beatport.manual_link_beatport_track is beatport_manual_link.manual_link_beatport_track

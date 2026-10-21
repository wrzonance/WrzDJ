from __future__ import annotations

import pytest

from app.services.setbuilder.playlist_url import InvalidPlaylistUrl
from app.services.setbuilder.pool import PoolCandidate
from app.services.setbuilder.public_playlist_import import (
    UnsupportedPublicPlaylist,
    prepare_public_playlist_import,
)


def test_prepare_public_playlist_import_builds_shared_source_identity(db, test_user, monkeypatch):
    calls = []

    def fetch(database, user, provider, playlist_id, *, storefront=None):
        calls.append((database, user, provider, playlist_id, storefront))
        return "Apple Hits", [PoolCandidate(title="A Song", artist="A Singer")]

    monkeypatch.setattr("app.services.setbuilder.pool_sources.candidates_from_public_url", fetch)

    prepared = prepare_public_playlist_import(
        db,
        test_user,
        "https://music.apple.com/gb/playlist/hits/pl.abc123",
    )

    assert calls == [(db, test_user, "apple_music", "pl.abc123", "gb")]
    assert prepared.source.kind == "public_url"
    assert prepared.source.external_ref == "apple_music:pl.abc123"
    assert prepared.source.label == "Apple Hits"
    assert prepared.source.meta == "Public apple_music playlist"
    assert prepared.candidates == [PoolCandidate(title="A Song", artist="A Singer")]


def test_prepare_public_playlist_import_rejects_unsupported_provider():
    with pytest.raises(UnsupportedPublicPlaylist, match="YouTube playlists"):
        prepare_public_playlist_import(
            None,
            None,
            "https://www.youtube.com/playlist?list=PLabc123",
        )


def test_prepare_public_playlist_import_preserves_invalid_url_error():
    with pytest.raises(InvalidPlaylistUrl, match="https"):
        prepare_public_playlist_import(None, None, "ftp://example.com/playlist")

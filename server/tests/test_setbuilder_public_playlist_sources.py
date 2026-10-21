"""Public playlist helpers tested with provider clients mocked at their network boundary."""

from types import SimpleNamespace

import pytest

from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.services.setbuilder import pool
from app.services.setbuilder.pool_sources import (
    candidates_from_public_url,
    preview_public_playlist,
)
from app.services.setbuilder.pool_types import PoolImportError

SPOTIFY_PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"
TIDAL_PLAYLIST_ID = "12345678-90ab-cdef-1234-567890abcdef"


@pytest.fixture
def test_set(db, test_user) -> Set:
    set_obj = Set(owner_id=test_user.id, name="Public playlist test set")
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _spotify_item(
    track_id: str,
    title: str,
    artists: list[str],
    *,
    album: str | None = None,
    isrc: str | None = None,
    duration_ms: int | None = None,
    artwork_url: str | None = None,
) -> dict:
    return {
        "track": {
            "id": track_id,
            "name": title,
            "artists": [{"name": artist} for artist in artists],
            "album": {
                "name": album,
                "images": [{"url": artwork_url}] if artwork_url else [],
            },
            "external_ids": {"isrc": isrc} if isrc else {},
            "duration_ms": duration_ms,
        }
    }


def test_spotify_preview_maps_public_playlist_metadata(db, test_user, monkeypatch):
    class SpotifyClient:
        def playlist(self, playlist_id, *, fields):
            assert playlist_id == SPOTIFY_PLAYLIST_ID
            assert fields == "name,owner.display_name,tracks.total"
            return {
                "name": "Sunday Drive",
                "owner": {"display_name": "DJ Example"},
                "tracks": {"total": 42},
            }

    monkeypatch.setattr(
        "app.services.providers.spotify.get_spotify_client", lambda: SpotifyClient()
    )

    assert preview_public_playlist(db, test_user, "spotify", SPOTIFY_PLAYLIST_ID) == {
        "name": "Sunday Drive",
        "owner": "DJ Example",
        "track_count": 42,
    }


def test_spotify_preview_normalizes_malformed_provider_metadata(db, test_user, monkeypatch):
    # Regression: 57cfcdc6867f assumed provider metadata always contained nested objects.
    class SpotifyClient:
        def playlist(self, playlist_id, *, fields):
            return {"name": 12, "owner": "not-an-object", "tracks": []}

    monkeypatch.setattr(
        "app.services.providers.spotify.get_spotify_client", lambda: SpotifyClient()
    )

    assert preview_public_playlist(db, test_user, "spotify", SPOTIFY_PLAYLIST_ID) == {
        "name": None,
        "owner": None,
        "track_count": None,
    }


def test_spotify_candidates_paginate_map_tracks_and_dedupe_on_import(
    db, test_user, test_set: Set, monkeypatch
):
    pages = [
        [
            _spotify_item(
                "one",
                "First Song",
                ["Artist A", "Artist B"],
                album="First Album",
                isrc="USAAA2600001",
                duration_ms=210_999,
                artwork_url="https://img.example/cover.jpg",
            ),
            *[
                _spotify_item(f"filler-{index}", f"Song {index}", [f"Artist {index}"])
                for index in range(98)
            ],
            {"track": None},
        ],
        [
            _spotify_item("one-copy", "First Song", ["Artist A", "Artist B"]),
            _spotify_item("two", "Second Song", ["Artist C"]),
        ],
    ]
    calls: list[tuple[int, int, tuple[str, ...]]] = []

    class SpotifyClient:
        def playlist(self, playlist_id, *, fields):
            assert playlist_id == SPOTIFY_PLAYLIST_ID
            return {"name": "Sunday Drive", "owner": {}, "tracks": {"total": 101}}

        def playlist_items(self, playlist_id, *, limit, offset, fields, additional_types):
            assert playlist_id == SPOTIFY_PLAYLIST_ID
            calls.append((limit, offset, additional_types))
            assert "external_ids.isrc" in fields
            return {"items": pages[offset // 100], "next": "next" if offset == 0 else None}

    monkeypatch.setattr(
        "app.services.providers.spotify.get_spotify_client", lambda: SpotifyClient()
    )

    name, candidates = candidates_from_public_url(db, test_user, "spotify", SPOTIFY_PLAYLIST_ID)

    assert name == "Sunday Drive"
    assert len(candidates) == 101  # the deleted/null track entry was skipped
    first = candidates[0]
    assert first.track_id == "spotify:one"
    assert first.title == "First Song"
    assert first.artist == "Artist A, Artist B"
    assert first.album == "First Album"
    assert first.isrc == "USAAA2600001"
    assert first.duration_sec == 210
    assert first.artwork_url == "https://img.example/cover.jpg"
    assert calls == [(100, 0, ("track",)), (100, 100, ("track",))]

    source = pool.get_or_create_source(
        db,
        test_set,
        kind="public_url",
        external_ref=f"spotify:{SPOTIFY_PLAYLIST_ID}",
        label=name,
    )
    assert pool.import_candidates(db, test_set, source, candidates) == (100, 1)
    assert db.query(SetPoolTrack).filter_by(set_id=test_set.id).count() == 100


def test_spotify_empty_and_malformed_playlist_entries_return_no_candidates(
    db, test_user, monkeypatch
):
    class SpotifyClient:
        def playlist(self, playlist_id, *, fields):
            return {"owner": None, "tracks": None}

        def playlist_items(self, playlist_id, **_kwargs):
            return {
                "items": [
                    {"track": None},
                    {"track": {"name": "No artist", "artists": []}},
                    {"track": {"name": None, "artists": [{"name": "Artist"}]}},
                ],
                "next": None,
            }

    monkeypatch.setattr(
        "app.services.providers.spotify.get_spotify_client", lambda: SpotifyClient()
    )

    assert candidates_from_public_url(db, test_user, "spotify", SPOTIFY_PLAYLIST_ID) == (
        "Spotify playlist",
        [],
    )


def test_spotify_playlist_fetch_failure_is_reported_as_pool_import_error(
    db, test_user, monkeypatch
):
    class SpotifyClient:
        def playlist(self, playlist_id, *, fields):
            return {"name": "Sunday Drive"}

        def playlist_items(self, playlist_id, **_kwargs):
            raise RuntimeError("provider network detail")

    monkeypatch.setattr(
        "app.services.providers.spotify.get_spotify_client", lambda: SpotifyClient()
    )

    with pytest.raises(PoolImportError, match="Couldn't fetch that Spotify playlist"):
        candidates_from_public_url(db, test_user, "spotify", SPOTIFY_PLAYLIST_ID)


def test_spotify_preview_failure_is_reported_as_pool_import_error(db, test_user, monkeypatch):
    class SpotifyClient:
        def playlist(self, playlist_id, *, fields):
            raise RuntimeError("provider network detail")

    monkeypatch.setattr(
        "app.services.providers.spotify.get_spotify_client", lambda: SpotifyClient()
    )

    with pytest.raises(PoolImportError, match="Couldn't fetch that Spotify playlist"):
        preview_public_playlist(db, test_user, "spotify", SPOTIFY_PLAYLIST_ID)


def test_tidal_preview_and_candidates_use_session_playlist_metadata(db, test_user, monkeypatch):
    from app.services.providers import tidal_account, tidal_catalog

    track = SimpleNamespace(
        id=123,
        name="The Track",
        artists=[SimpleNamespace(name="Artist One"), SimpleNamespace(name="Artist Two")],
        artist=SimpleNamespace(name="Fallback Artist"),
        album=SimpleNamespace(name="Album", image=lambda size: f"cover-{size}"),
        bpm=126,
        key="8A",
        duration=195,
        isrc="USAAA2600002",
        version="Club Mix",
        popularity=77,
        explicit=True,
    )
    offsets: list[tuple[int, int]] = []

    class Playlist:
        name = "Tidal Favourites"
        num_tracks = 1

        def tracks(self, *, limit, offset):
            offsets.append((limit, offset))
            return [track] if offset == 0 else []

    class TidalSession:
        def playlist(self, playlist_id):
            assert playlist_id == TIDAL_PLAYLIST_ID
            return Playlist()

    def tidal_session(_db, _user):
        return TidalSession()

    monkeypatch.setattr(tidal_account, "get_tidal_session", tidal_session)
    monkeypatch.setattr(tidal_catalog, "get_tidal_session", tidal_session)

    assert preview_public_playlist(db, test_user, "tidal", TIDAL_PLAYLIST_ID) == {
        "name": "Tidal Favourites",
        "owner": None,
        "track_count": 1,
    }
    name, candidates = candidates_from_public_url(db, test_user, "tidal", TIDAL_PLAYLIST_ID)

    assert name == "Tidal Favourites"
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.track_id == "tidal:123"
    assert candidate.title == "The Track (Club Mix)"
    assert candidate.artist == "Artist One, Artist Two"
    assert candidate.album == "Album"
    assert candidate.bpm == 126
    assert candidate.key == "8A"
    assert candidate.duration_sec == 195
    assert candidate.isrc == "USAAA2600002"
    assert candidate.artwork_url == "cover-640"
    assert offsets == [(100, 0)]


def test_tidal_public_playlist_missing_session_is_a_user_safe_error(db, test_user, monkeypatch):
    from app.services.providers import tidal_account

    monkeypatch.setattr(tidal_account, "get_tidal_session", lambda _db, _user: None)

    with pytest.raises(PoolImportError, match="Connect your Tidal account"):
        preview_public_playlist(db, test_user, "tidal", TIDAL_PLAYLIST_ID)


def test_tidal_playlist_preview_failure_is_reported_as_pool_import_error(
    db, test_user, monkeypatch
):
    from app.services.providers import tidal_account

    class TidalSession:
        def playlist(self, playlist_id):
            raise RuntimeError("provider network detail")

    monkeypatch.setattr(tidal_account, "get_tidal_session", lambda _db, _user: TidalSession())

    with pytest.raises(PoolImportError, match="Couldn't fetch that Tidal playlist"):
        preview_public_playlist(db, test_user, "tidal", TIDAL_PLAYLIST_ID)


def test_tidal_public_playlist_track_failure_is_mapped_to_pool_import_error(
    db, test_user, monkeypatch
):
    from app.services.providers import tidal_account, tidal_catalog

    class Playlist:
        name = "Tidal Favourites"
        num_tracks = 1

        def tracks(self, *, limit, offset):
            raise RuntimeError("provider network detail")

    class TidalSession:
        def playlist(self, playlist_id):
            return Playlist()

    def tidal_session(_db, _user):
        return TidalSession()

    monkeypatch.setattr(tidal_account, "get_tidal_session", tidal_session)
    monkeypatch.setattr(tidal_catalog, "get_tidal_session", tidal_session)

    with pytest.raises(PoolImportError, match="Couldn't fetch that Tidal playlist"):
        candidates_from_public_url(db, test_user, "tidal", TIDAL_PLAYLIST_ID)

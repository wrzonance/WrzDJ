"""Apple Music catalog lookup and DJ storefront resolution tests."""

import json

import pytest

from app.models.provider_connection import UserProviderConnection
from app.services import apple_music_catalog, apple_music_tokens
from app.services.setbuilder.export_common import ExportTrack

VALID_TOKEN = "music-user-token-1234567890"


def _track(*, isrc: str | None = None) -> ExportTrack:
    return ExportTrack(
        position=2,
        title="Night Drive",
        artist="The Example",
        album=None,
        isrc=isrc,
        duration_sec=None,
    )


def _connect_dj(db, user):
    db.add(
        UserProviderConnection(
            user_id=user.id,
            provider_id="apple_music",
            connection_state="connected",
            credential_type="music_user_token",
            credential_payload=json.dumps({"version": 1, "music_user_token": VALID_TOKEN}),
            metadata_json='{"storefront":"gb"}',
        )
    )
    db.commit()


def test_resolution_tries_exact_isrc_then_fuzzy_title_artist(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    queries = []

    def search(_db, storefront, term, *, isrc=None):
        queries.append((storefront, term, isrc))
        if isrc:
            return []
        return [
            apple_music_catalog.AppleCatalogSong(
                id="song-17", title="Night Drive", artist="The Example", isrc=None
            )
        ]

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)

    resolved, unresolved = apple_music_catalog.resolve_tracks(
        db, test_user, [_track(isrc="USRC17607839")]
    )

    assert [(track.position, song_id) for track, song_id in resolved] == [(2, "song-17")]
    assert unresolved == []
    assert queries == [
        ("gb", "", "USRC17607839"),
        ("gb", "The Example Night Drive", None),
    ]


def test_resolution_accepts_only_exact_isrc_before_fuzzy_fallback(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    queries = []

    def search(_db, storefront, term, *, isrc=None):
        queries.append((storefront, term, isrc))
        if isrc:
            return [
                apple_music_catalog.AppleCatalogSong(
                    id="wrong-song", title="Other Track", artist="Different Artist", isrc="other"
                ),
                apple_music_catalog.AppleCatalogSong(
                    id="exact-song",
                    title="Other Track",
                    artist="Different Artist",
                    isrc="usrc17607839",
                ),
            ]
        return []

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)

    resolved, unresolved = apple_music_catalog.resolve_tracks(
        db, test_user, [_track(isrc="USRC17607839")]
    )

    assert [(track.position, song_id) for track, song_id in resolved] == [(2, "exact-song")]
    assert unresolved == []
    assert queries == [("gb", "", "USRC17607839")]


def test_resolution_rejects_unwanted_versions_and_preserves_unresolved_tracks(
    db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    monkeypatch.setattr(
        apple_music_catalog,
        "search_catalog",
        lambda *_args, **_kwargs: [
            apple_music_catalog.AppleCatalogSong(
                id="live-song", title="Night Drive (Live)", artist="The Example", isrc=None
            )
        ],
    )

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, [_track()])

    assert resolved == []
    assert [track.position for track in unresolved] == [2]


def test_search_uses_developer_token_and_exact_storefront_filters(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))
    requests = []

    def apple_get(path, developer_token, *, params=None, **_kwargs):
        requests.append((path, developer_token, params))
        return {
            "data": [
                {
                    "id": "song-17",
                    "attributes": {
                        "name": "Night Drive",
                        "artistName": "The Example",
                        "isrc": "USRC17607839",
                    },
                }
            ]
        }

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)

    songs = apple_music_catalog.search_catalog(None, "gb", "", isrc="USRC17607839")

    assert songs == [
        apple_music_catalog.AppleCatalogSong(
            id="song-17", title="Night Drive", artist="The Example", isrc="USRC17607839"
        )
    ]
    assert requests == [
        ("/catalog/gb/songs", "dev-token", {"filter[isrc]": "USRC17607839", "limit": "25"})
    ]


def test_title_search_sends_title_artist_term_to_the_dj_storefront(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))
    requests = []

    def apple_get(path, developer_token, *, params=None, **_kwargs):
        requests.append((path, developer_token, params))
        return {"results": {"songs": {"data": []}}}

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)

    assert apple_music_catalog.search_catalog(None, "gb", "The Example Night Drive") == []

    assert requests == [
        (
            "/catalog/gb/search",
            "dev-token",
            {"term": "The Example Night Drive", "types": "songs", "limit": "25"},
        )
    ]


def test_public_playlist_reads_catalog_metadata_and_all_track_pages(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))
    requests = []

    def apple_get(path, developer_token, *, params=None, **_kwargs):
        requests.append((path, developer_token, params))
        if path.endswith("/tracks") and len(requests) == 2:
            return {
                "data": [
                    {
                        "id": "song-1",
                        "type": "songs",
                        "attributes": {
                            "name": "Night Drive",
                            "artistName": "The Example",
                            "albumName": "After Hours",
                            "isrc": "USRC17607839",
                            "durationInMillis": 201000,
                        },
                    }
                ],
                "next": "/v1/catalog/us/playlists/pl.abc123/tracks?offset=100",
            }
        if path.endswith("/tracks"):
            return {
                "data": [
                    {
                        "id": "song-2",
                        "type": "songs",
                        "attributes": {
                            "name": "Blue Hour",
                            "artistName": "The Example",
                        },
                    },
                ]
            }
        return {
            "data": [
                {
                    "id": "pl.abc123",
                    "attributes": {
                        "name": "Night Drive Mix",
                        "curatorName": "The Example",
                    },
                }
            ]
        }

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)

    metadata, songs = apple_music_catalog.fetch_public_playlist("us", "pl.abc123")

    assert metadata == {"name": "Night Drive Mix", "owner": "The Example", "track_count": 2}
    assert songs == [
        apple_music_catalog.AppleCatalogSong(
            id="song-1",
            title="Night Drive",
            artist="The Example",
            isrc="USRC17607839",
            album="After Hours",
            duration_ms=201000,
        ),
        apple_music_catalog.AppleCatalogSong(
            id="song-2", title="Blue Hour", artist="The Example", isrc=None
        ),
    ]
    assert requests == [
        ("/catalog/us/playlists/pl.abc123", "dev-token", None),
        ("/catalog/us/playlists/pl.abc123/tracks", "dev-token", None),
        (
            "/catalog/us/playlists/pl.abc123/tracks",
            "dev-token",
            {"offset": "100"},
        ),
    ]


def _mock_public_playlist(monkeypatch, tracks_payload):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))

    def apple_get(path, _developer_token, *, params=None, **_kwargs):
        if path.endswith("/tracks"):
            return tracks_payload
        return {"data": [{"id": "pl.abc123", "attributes": {"name": "Mix"}}]}

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)


@pytest.mark.parametrize("tracks_payload", [{}, {"data": None}, {"data": "not-a-list"}])
def test_public_playlist_rejects_missing_or_non_list_track_data(monkeypatch, tracks_payload):
    _mock_public_playlist(monkeypatch, tracks_payload)

    with pytest.raises(apple_music_tokens.AppleMusicError, match="playlist tracks"):
        apple_music_catalog.fetch_public_playlist("us", "pl.abc123")


def test_public_playlist_rejects_malformed_song_instead_of_dropping_it(monkeypatch):
    _mock_public_playlist(
        monkeypatch,
        {
            "data": [
                {
                    "id": "song-1",
                    "type": "songs",
                    "attributes": {"name": "Night Drive"},
                }
            ],
            "meta": {"total": 1},
        },
    )

    with pytest.raises(apple_music_tokens.AppleMusicError, match="playlist track"):
        apple_music_catalog.fetch_public_playlist("us", "pl.abc123")


def test_public_playlist_rejects_unsupported_video_instead_of_dropping_it(monkeypatch):
    _mock_public_playlist(
        monkeypatch,
        {
            "data": [
                {
                    "id": "video-1",
                    "type": "music-videos",
                    "attributes": {"name": "Music video", "artistName": "The Example"},
                }
            ],
            "meta": {"total": 1},
        },
    )

    with pytest.raises(apple_music_tokens.AppleMusicError, match="unsupported track type"):
        apple_music_catalog.fetch_public_playlist("us", "pl.abc123")


def test_public_playlist_rejects_incomplete_pagination_count(monkeypatch):
    _mock_public_playlist(
        monkeypatch,
        {
            "data": [
                {
                    "id": "song-1",
                    "type": "songs",
                    "attributes": {"name": "Night Drive", "artistName": "The Example"},
                }
            ],
            "meta": {"total": 2},
        },
    )

    with pytest.raises(apple_music_tokens.AppleMusicError, match="incomplete"):
        apple_music_catalog.fetch_public_playlist("us", "pl.abc123")


def test_preview_uses_apple_playlist_track_count(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))
    requests = []

    def apple_get(path, _developer_token, *, params=None, **_kwargs):
        requests.append((path, params))
        if path.endswith("/tracks"):
            return {"data": [], "meta": {"total": 12}}
        return {"data": [{"id": "pl.abc123", "attributes": {"name": "Mix"}}]}

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)

    preview = apple_music_catalog.preview_public_playlist("us", "pl.abc123")

    assert preview["track_count"] == 12
    assert requests == [
        ("/catalog/us/playlists/pl.abc123", None),
        ("/catalog/us/playlists/pl.abc123/tracks", {"limit": "1"}),
    ]


def test_public_playlist_rejects_non_catalog_pagination_links(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))

    def apple_get(path, developer_token, **_kwargs):
        if path.endswith("/tracks"):
            return {"data": [], "next": "https://attacker.example/steal-token"}
        return {"data": [{"id": "pl.abc123", "attributes": {"name": "Mix"}}]}

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)

    try:
        apple_music_catalog.fetch_public_playlist("us", "pl.abc123")
    except apple_music_tokens.AppleMusicError as exc:
        assert "pagination" in str(exc).lower()
    else:
        raise AssertionError("malicious pagination URL was accepted")


def test_search_rejects_invalid_storefront(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))

    with pytest.raises(apple_music_tokens.AppleMusicError):
        apple_music_catalog.search_catalog(None, "GB", "The Example Night Drive")


def test_title_search_ignores_malformed_songs_response(monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))
    monkeypatch.setattr(
        apple_music_tokens, "apple_get", lambda *_args, **_kwargs: {"results": {"songs": []}}
    )

    assert apple_music_catalog.search_catalog(None, "gb", "The Example Night Drive") == []


def test_resolution_preserves_tracks_resolved_before_apple_failure(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    calls = 0

    def search(_db, _storefront, _term, *, isrc=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [
                apple_music_catalog.AppleCatalogSong(
                    id="song-17", title="Night Drive", artist="The Example", isrc=None
                )
            ]
        raise apple_music_tokens.AppleMusicError("Apple Music request failed")

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    tracks = [_track(), _track()]
    tracks[1] = ExportTrack(
        position=3,
        title=tracks[1].title,
        artist=tracks[1].artist,
        album=tracks[1].album,
        isrc=tracks[1].isrc,
        duration_sec=tracks[1].duration_sec,
    )

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, tracks)

    assert [(track.position, song_id) for track, song_id in resolved] == [(2, "song-17")]
    assert unresolved == [tracks[1]]

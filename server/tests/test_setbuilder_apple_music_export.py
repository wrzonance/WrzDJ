"""Apple Music set exports resolve conservatively and create ordered playlists once."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app.core.time import utcnow
from app.models.provider_connection import UserProviderConnection
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services import apple_music_catalog
from app.services.setbuilder import export_apple_music
from app.services.setbuilder.export_common import ExportTrack

VALID_TOKEN = "music-user-token-1234567890"


def _track(position: int, title: str, artist: str, track_id: str | None = None) -> ExportTrack:
    return ExportTrack(position=position, title=title, artist=artist, track_id=track_id)


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


def test_apple_music_ids_resolve_without_catalog_search(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    queries = []

    def search(_db, storefront, term, *, isrc=None, song_id=None):
        queries.append((storefront, term, isrc, song_id))
        return [SimpleNamespace(id="12345")] if song_id == "12345" else []

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    resolved, unresolved = apple_music_catalog.resolve_tracks(
        db, test_user, [_track(0, "Song", "Artist", "apple_music:12345")]
    )

    assert [(track.position, song_id) for track, song_id in resolved] == [(0, "12345")]
    assert unresolved == []
    assert queries == [("gb", "", None, "12345")]


def test_apple_music_id_unavailable_in_linked_storefront_falls_back_to_isrc(
    db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    queries = []

    def search(_db, storefront, term, *, isrc=None, song_id=None):
        queries.append((storefront, term, isrc, song_id))
        if isrc:
            return [SimpleNamespace(id="local-song", isrc="isrc-1")]
        return []

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(
        position=1,
        title="Song",
        artist="Artist",
        isrc="ISRC-1",
        track_id="apple_music:12345",
    )

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert [(item.position, song_id) for item, song_id in resolved] == [(1, "local-song")]
    assert unresolved == []
    assert queries == [("gb", "", None, "12345"), ("gb", "", "ISRC-1", None)]


def test_apple_music_export_creates_playlist_with_order_and_duplicates(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Night / Dance")
    db.add(set_obj)
    db.commit()
    requests = []

    def fake_request(method, path, developer_token, *, music_user_token, json_body=None):
        requests.append((method, path, developer_token, music_user_token, json_body))
        return {"data": [{"id": "p.playlist123", "type": "library-playlists"}]}

    monkeypatch.setattr(
        export_apple_music.apple_music_tokens, "create_developer_token", lambda: ("dev", 100)
    )
    monkeypatch.setattr(export_apple_music.apple_music_tokens, "apple_request", fake_request)
    resolved = [
        (_track(0, "First", "Artist"), "song-1"),
        (_track(1, "Second", "Artist"), "song-2"),
        (_track(2, "First", "Artist"), "song-1"),
    ]

    outcome = export_apple_music.export_to_apple_music(db, test_user, set_obj, resolved)

    assert len(requests) == 1
    method, path, developer_token, user_token, body = requests[0]
    assert (method, path, developer_token, user_token) == (
        "POST",
        "/me/library/playlists",
        "dev",
        VALID_TOKEN,
    )
    assert body["attributes"]["name"] == "WrzDJ Set: Night / Dance"
    assert body["relationships"]["tracks"]["data"] == [
        {"id": "song-1", "type": "songs"},
        {"id": "song-2", "type": "songs"},
        {"id": "song-1", "type": "songs"},
    ]
    assert outcome.added == 3
    assert outcome.playlist_url == "https://music.apple.com/gb/library/playlist/p.playlist123"
    db.refresh(set_obj)
    assert (set_obj.status, set_obj.apple_music_playlist_id) == ("exported", "p.playlist123")


def test_apple_music_export_does_not_mark_set_exported_after_uncertain_create(
    db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Night")
    db.add(set_obj)
    db.commit()
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens, "create_developer_token", lambda: ("dev", 100)
    )

    def uncertain(*args, **kwargs):
        raise export_apple_music.apple_music_tokens.AppleMusicRequestUncertain

    monkeypatch.setattr(export_apple_music.apple_music_tokens, "apple_request", uncertain)
    with pytest.raises(export_apple_music.AppleMusicWriteUncertain):
        export_apple_music.export_to_apple_music(
            db, test_user, set_obj, [(_track(0, "Song", "Artist"), "song-1")]
        )

    db.refresh(set_obj)
    assert set_obj.status == "draft"
    assert set_obj.apple_music_playlist_id is None


def test_apple_music_export_rejects_unusable_creation_response(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Night")
    db.add(set_obj)
    db.commit()
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "create_developer_token",
        lambda: ("dev", 100),
    )
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "apple_request",
        lambda *args, **kwargs: {"data": [{"id": "bad id", "type": "library-playlists"}]},
    )

    with pytest.raises(export_apple_music.AppleMusicWriteUncertain):
        export_apple_music.export_to_apple_music(
            db, test_user, set_obj, [(_track(0, "Song", "Artist"), "song-1")]
        )

    db.refresh(set_obj)
    assert set_obj.status == "draft"
    assert set_obj.apple_music_playlist_id is None


def test_apple_music_export_reports_uncertainty_if_local_success_cannot_commit(
    db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Night")
    db.add(set_obj)
    db.commit()
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "create_developer_token",
        lambda: ("dev", 100),
    )
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "apple_request",
        lambda *args, **kwargs: {"data": [{"id": "p.playlist123", "type": "library-playlists"}]},
    )

    def fail_commit():
        raise OperationalError("commit", {}, Exception("database unavailable"))

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(export_apple_music.AppleMusicWriteUncertain):
        export_apple_music.export_to_apple_music(
            db, test_user, set_obj, [(_track(0, "Song", "Artist"), "song-1")]
        )

    db.refresh(set_obj)
    assert set_obj.status == "draft"
    assert set_obj.apple_music_playlist_id is None


def test_apple_music_export_marks_only_rejected_grant_for_reauthorization(
    db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Night")
    db.add(set_obj)
    db.commit()
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens, "create_developer_token", lambda: ("dev", 100)
    )
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "apple_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            export_apple_music.apple_music_tokens.AppleMusicUserAuthorizationError
        ),
    )

    with pytest.raises(export_apple_music.apple_music_tokens.AppleMusicUserAuthorizationError):
        export_apple_music.export_to_apple_music(
            db, test_user, set_obj, [(_track(0, "Song", "Artist"), "song-1")]
        )

    connection = (
        db.query(UserProviderConnection)
        .filter_by(user_id=test_user.id, provider_id="apple_music")
        .one()
    )
    assert connection.connection_state == "reauthorize"


def test_stale_rejected_write_does_not_invalidate_a_newer_grant(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Night")
    db.add(set_obj)
    db.commit()
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "create_developer_token",
        lambda: ("dev", 100),
    )

    def reconnect_then_reject(*args, **kwargs):
        connection = (
            db.query(UserProviderConnection)
            .filter_by(user_id=test_user.id, provider_id="apple_music")
            .one()
        )
        connection.authorization_generation += 1
        connection.credential_payload = json.dumps(
            {"version": 1, "music_user_token": "new-music-user-token-1234567890"}
        )
        db.commit()
        raise export_apple_music.apple_music_tokens.AppleMusicUserAuthorizationError

    monkeypatch.setattr(
        export_apple_music.apple_music_tokens, "apple_request", reconnect_then_reject
    )
    with pytest.raises(export_apple_music.apple_music_tokens.AppleMusicUserAuthorizationError):
        export_apple_music.export_to_apple_music(
            db, test_user, set_obj, [(_track(0, "Song", "Artist"), "song-1")]
        )

    connection = (
        db.query(UserProviderConnection)
        .filter_by(user_id=test_user.id, provider_id="apple_music")
        .one()
    )
    assert connection.connection_state == "connected"
    assert json.loads(connection.credential_payload)["music_user_token"] == (
        "new-music-user-token-1234567890"
    )


def test_apple_music_preflight_and_export_require_explicit_skip_for_unresolved_tracks(
    client, auth_headers, db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = Set(owner_id=test_user.id, name="Apple Set")
    db.add(set_obj)
    db.commit()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.commit()
    db.add_all(
        [
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                title="Found",
                artist="Artist",
                track_id="apple_music:known",
                dedupe_sig="found",
            ),
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                title="Missing",
                artist="Artist",
                dedupe_sig="missing",
            ),
        ]
    )
    db.commit()
    monkeypatch.setattr(
        "app.services.apple_music_tokens.is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.apple_music_catalog.resolve_tracks",
        lambda *_args: (
            [(ExportTrack(position=0, title="Found", artist="Artist"), "known")],
            [ExportTrack(position=1, title="Missing", artist="Artist")],
        ),
    )

    preflight = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/preflight",
        json={"target": "apple_music"},
        headers=auth_headers,
    )
    assert preflight.status_code == 200
    assert preflight.json()["resolved_count"] == 1
    assert preflight.json()["apple_music_connected"] is True
    assert preflight.json()["unresolved"][0]["title"] == "Missing"

    blocked = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music",
        json={"skip_unresolved": False},
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["unresolved"][0]["title"] == "Missing"

    def fake_export(_db, _user, exported_set, resolved):
        exported_set.apple_music_playlist_id = "p.playlist123"
        exported_set.exported_at = utcnow()
        exported_set.status = "exported"
        return export_apple_music.AppleMusicExportOutcome(
            playlist_id="p.playlist123",
            playlist_url="https://music.apple.com/gb/library/playlist/p.playlist123",
            added=len(resolved),
        )

    monkeypatch.setattr(export_apple_music, "export_to_apple_music", fake_export)
    accepted = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music",
        json={"skip_unresolved": True},
        headers=auth_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["playlist_id"] == "p.playlist123"
    assert accepted.json()["skipped"] == 1
    assert accepted.json()["status"] == "exported"

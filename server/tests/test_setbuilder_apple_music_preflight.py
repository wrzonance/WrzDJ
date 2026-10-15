"""Apple Music preflight validates identity and separates link/configuration failures."""

import json
from types import SimpleNamespace

import pytest

from app.models.provider_connection import UserProviderConnection
from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services import apple_music_catalog, apple_music_tokens
from app.services.setbuilder import export_apple_music
from app.services.setbuilder.export_common import ExportTrack

MUSIC_USER_TOKEN = "music-user-token-1234567890"


def _connect_dj(db, user):
    db.add(
        UserProviderConnection(
            user_id=user.id,
            provider_id="apple_music",
            connection_state="connected",
            credential_type="music_user_token",
            credential_payload=json.dumps({"version": 1, "music_user_token": MUSIC_USER_TOKEN}),
            metadata_json='{"storefront":"gb"}',
        )
    )
    db.commit()


def _set_with_tracks(db, user):
    set_obj = Set(owner_id=user.id, name="Apple Set")
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
                track_id="apple_music:12345",
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
    return set_obj


def test_catalog_id_is_checked_in_the_dj_storefront(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    queries = []

    def search(_db, storefront, term, *, isrc=None, song_id=None):
        queries.append((storefront, term, isrc, song_id))
        return [SimpleNamespace(id="12345")] if song_id == "12345" else []

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(position=0, title="Song", artist="Artist", track_id="apple_music:12345")

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert resolved == [(track, "12345")]
    assert unresolved == []
    assert queries == [("gb", "", None, "12345")]


def test_missing_catalog_id_falls_back_to_isrc(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    calls = []

    def search(_db, _storefront, _term, *, isrc=None, song_id=None):
        calls.append((isrc, song_id))
        if song_id:
            raise apple_music_tokens.AppleMusicNotFound
        if isrc:
            return [SimpleNamespace(id="local-song", isrc=isrc)]
        raise AssertionError("title lookup should not follow an exact ISRC match")

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(
        position=0, title="Song", artist="Artist", isrc="ISRC-1", track_id="apple_music:12345"
    )

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert resolved == [(track, "local-song")]
    assert unresolved == []
    assert calls == [(None, "12345"), ("ISRC-1", None)]


def test_catalog_provider_error_does_not_turn_into_a_missing_match(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    calls = []

    def search(_db, _storefront, _term, *, isrc=None, song_id=None):
        calls.append((isrc, song_id))
        raise apple_music_tokens.AppleMusicError("catalog unavailable")

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(
        position=0, title="Song", artist="Artist", isrc="ISRC-1", track_id="apple_music:12345"
    )

    with pytest.raises(apple_music_tokens.AppleMusicError):
        apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert calls == [(None, "12345")]


def test_preflight_returns_unlinked_state_without_creating_a_playlist(
    client, auth_headers, db, test_user, monkeypatch
):
    set_obj = _set_with_tracks(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)

    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/preflight",
        json={"target": "apple_music"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["apple_music_connected"] is False
    assert response.json()["resolved_count"] == 0


def test_preflight_reports_deployment_configuration_separately(
    client, auth_headers, db, test_user, monkeypatch
):
    set_obj = _set_with_tracks(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: False)

    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/preflight",
        json={"target": "apple_music"},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Apple Music is not configured"


def test_preflight_maps_catalog_provider_errors_to_a_controlled_response(
    client, auth_headers, db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = _set_with_tracks(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)

    def unavailable(*_args):
        raise apple_music_tokens.AppleMusicError("provider details must not escape")

    monkeypatch.setattr(apple_music_catalog, "resolve_tracks", unavailable)
    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/preflight",
        json={"target": "apple_music"},
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Apple Music catalog lookup failed"


def test_preflight_returns_weak_matches_as_explicit_unresolved_tracks(
    client, auth_headers, db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = _set_with_tracks(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(
        apple_music_catalog,
        "resolve_tracks",
        lambda *_args: (
            [(ExportTrack(position=0, title="Found", artist="Artist"), "12345")],
            [ExportTrack(position=1, title="Missing", artist="Artist")],
        ),
    )

    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/preflight",
        json={"target": "apple_music"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["resolved_count"] == 1
    assert response.json()["unresolved"][0]["reason"] == "no_apple_music_match"


def test_export_requires_explicit_skip_for_unresolved_tracks(
    client, auth_headers, db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = _set_with_tracks(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(
        apple_music_catalog,
        "resolve_tracks",
        lambda *_args: (
            [(ExportTrack(position=0, title="Found", artist="Artist"), "matched-id")],
            [ExportTrack(position=1, title="Missing", artist="Artist")],
        ),
    )
    create_calls = []
    monkeypatch.setattr(
        export_apple_music,
        "export_to_apple_music",
        lambda *_args: create_calls.append("created"),
    )

    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music",
        json={"skip_unresolved": False},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["unresolved"][0]["reason"] == "no_apple_music_match"
    assert create_calls == []


def test_uncertain_export_response_includes_recovery_id_and_never_claims_success(
    client, auth_headers, db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    set_obj = _set_with_tracks(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(
        apple_music_catalog,
        "resolve_tracks",
        lambda *_args: ([(ExportTrack(position=0, title="Found", artist="Artist"), "id")], []),
    )

    def uncertain(*_args):
        raise export_apple_music.AppleMusicWriteUncertain("p.created123")

    monkeypatch.setattr(export_apple_music, "export_to_apple_music", uncertain)
    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music",
        json={},
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert "p.created123" in response.json()["detail"]
    assert "could not be confirmed" in response.json()["detail"]

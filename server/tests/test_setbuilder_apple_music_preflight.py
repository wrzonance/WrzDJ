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

    def search(_db, storefront, term, *, isrc=None, song_id=None, song_ids=None):
        queries.append((storefront, term, isrc, song_id, song_ids))
        return (
            [
                apple_music_catalog.AppleCatalogSong(
                    id="12345", title="Song", artist="Artist", isrc=None
                )
            ]
            if song_ids == ["12345"]
            else []
        )

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(position=0, title="Song", artist="Artist", track_id="apple_music:12345")

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert resolved == [(track, "12345")]
    assert unresolved == []
    assert queries == [("gb", "", None, None, ["12345"])]


def test_catalog_id_with_different_track_metadata_falls_back_to_exact_isrc(
    db, test_user, monkeypatch
):
    _connect_dj(db, test_user)
    queries = []

    def search(_db, storefront, term, *, isrc=None, song_id=None, song_ids=None):
        queries.append((storefront, term, isrc, song_id, song_ids))
        if song_ids:
            return [
                apple_music_catalog.AppleCatalogSong(
                    id="12345", title="Different Song", artist="Another Artist", isrc="OTHER"
                )
            ]
        if isrc:
            return [
                apple_music_catalog.AppleCatalogSong(
                    id="confirmed-song",
                    title="Night Drive",
                    artist="The Example",
                    isrc="ISRC-1",
                )
            ]
        raise AssertionError("an exact ISRC match should avoid title search")

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(
        position=0,
        title="Night Drive",
        artist="The Example",
        isrc="ISRC-1",
        track_id="apple_music:12345",
    )

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert resolved == [(track, "confirmed-song")]
    assert unresolved == []
    assert queries == [
        ("gb", "", None, None, ["12345"]),
        ("gb", "", "ISRC-1", None, None),
    ]


def test_catalog_id_resolution_batches_requests_at_apple_limit(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev-token", 100))
    requests = []

    def apple_get(path, developer_token, *, params=None, **_kwargs):
        requests.append((path, developer_token, params))
        return {
            "data": [
                {
                    "id": song_id,
                    "attributes": {"name": f"Song {song_id}", "artistName": "Artist"},
                }
                for song_id in params["ids"].split(",")
            ]
        }

    monkeypatch.setattr(apple_music_tokens, "apple_get", apple_get)
    tracks = [
        ExportTrack(
            position=position,
            title=f"Song {position}",
            artist="Artist",
            track_id=f"apple_music:{position}",
        )
        for position in range(301)
    ]

    resolved, unresolved = apple_music_catalog.resolve_tracks(db, test_user, tracks)

    assert resolved == [(track, str(position)) for position, track in enumerate(tracks)]
    assert unresolved == []
    assert [len(params["ids"].split(",")) for _, _, params in requests] == [300, 1]
    assert all(path == "/catalog/gb/songs" for path, _, _ in requests)


def test_missing_catalog_id_falls_back_to_isrc(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    calls = []

    def search(_db, _storefront, _term, *, isrc=None, song_id=None, song_ids=None):
        calls.append((isrc, song_id, song_ids))
        if song_ids:
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
    assert calls == [(None, None, ["12345"]), ("ISRC-1", None, None)]


def test_catalog_provider_error_does_not_turn_into_a_missing_match(db, test_user, monkeypatch):
    _connect_dj(db, test_user)
    calls = []

    def search(_db, _storefront, _term, *, isrc=None, song_id=None, song_ids=None):
        calls.append((isrc, song_id, song_ids))
        raise apple_music_tokens.AppleMusicError("catalog unavailable")

    monkeypatch.setattr(apple_music_catalog, "search_catalog", search)
    track = ExportTrack(
        position=0, title="Song", artist="Artist", isrc="ISRC-1", track_id="apple_music:12345"
    )

    with pytest.raises(apple_music_tokens.AppleMusicError):
        apple_music_catalog.resolve_tracks(db, test_user, [track])

    assert calls == [(None, None, ["12345"])]


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
    assert response.json()["detail"] == {
        "code": "apple_music_write_uncertain",
        "message": (
            "Apple Music export could not be confirmed. Check your library before trying again."
        ),
        "playlist_id": "p.created123",
    }


def test_concurrent_export_returns_conflict_without_claiming_an_uncertain_write(
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

    def in_progress(*_args):
        raise export_apple_music.AppleMusicExportInProgress

    monkeypatch.setattr(export_apple_music, "export_to_apple_music", in_progress)
    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music",
        json={},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "apple_music_export_in_progress"


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_playlist_id"),
    [
        ({"action": "playlist_absent"}, "ready_to_retry", None),
        ({"action": "playlist_found", "playlist_id": "p.found123"}, "exported", "p.found123"),
    ],
)
def test_recovery_requires_uncertain_claim_and_applies_explicit_user_choice(
    client,
    auth_headers,
    db,
    test_user,
    payload,
    expected_status,
    expected_playlist_id,
):
    set_obj = _set_with_tracks(db, test_user)
    set_obj.apple_music_export_pending = True
    set_obj.apple_music_export_uncertain = True
    set_obj.apple_music_export_attempt_id = "uncertain-attempt"
    set_obj.apple_music_export_recovery_playlist_id = "p.created123"
    db.commit()

    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music/recovery",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    db.refresh(set_obj)
    assert set_obj.apple_music_export_pending is False
    assert set_obj.apple_music_export_uncertain is False
    assert set_obj.apple_music_playlist_id == expected_playlist_id


def test_recovery_does_not_clear_an_active_export_claim(client, auth_headers, db, test_user):
    set_obj = _set_with_tracks(db, test_user)
    set_obj.apple_music_export_pending = True
    set_obj.apple_music_export_uncertain = False
    set_obj.apple_music_export_attempt_id = "active-attempt"
    db.commit()

    response = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/apple-music/recovery",
        json={"action": "playlist_absent"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    db.refresh(set_obj)
    assert set_obj.apple_music_export_pending is True

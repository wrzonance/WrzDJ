"""Spotify set export boundaries preserve ordering and never silently omit tracks."""

from types import SimpleNamespace

from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services.setbuilder import export_spotify
from app.services.setbuilder.export_common import ExportTrack


def _track(position: int, title: str, artist: str, track_id: str | None = None) -> ExportTrack:
    return ExportTrack(position=position, title=title, artist=artist, track_id=track_id)


def test_spotify_ids_resolve_without_search(db, test_user, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("known Spotify IDs must not trigger search")

    monkeypatch.setattr(export_spotify.spotify, "search_songs", fail)
    resolved, unresolved = export_spotify.resolve_for_spotify(
        db, test_user, [_track(0, "Song", "Artist", "spotify:abc123")]
    )

    assert [(track.position, uri) for track, uri in resolved] == [(0, "spotify:track:abc123")]
    assert unresolved == []


def test_unmatched_spotify_track_is_returned_as_unresolved(db, test_user, monkeypatch):
    monkeypatch.setattr(export_spotify.spotify, "search_songs", lambda *args: [])

    resolved, unresolved = export_spotify.resolve_for_spotify(
        db, test_user, [_track(2, "Unknown", "Unknown Artist")]
    )

    assert resolved == []
    assert [(track.position, track.title) for track in unresolved] == [(2, "Unknown")]


def test_export_batches_in_order_and_marks_set_exported(db, test_user, monkeypatch):
    set_obj = Set(owner_id=test_user.id, name="Night")
    db.add(set_obj)
    db.commit()
    test_user.spotify_access_token = "access-token"
    test_user.spotify_refresh_token = "refresh-token"
    db.commit()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        export_spotify,
        "_spotify_request",
        lambda db_, user, method, path, *, json_body=None: (
            {
                "id": "playlist1",
                "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist1"},
            }
            if path == "/me/playlists"
            else calls.append(json_body["uris"]) or {"snapshot_id": "snapshot"}
        ),
    )
    resolved = [(_track(i, f"Track {i}", "Artist"), f"spotify:track:id{i}") for i in range(205)]

    outcome = export_spotify.export_to_spotify(db, test_user, set_obj, resolved)

    assert [len(batch) for batch in calls] == [100, 100, 5]
    assert [uri for batch in calls for uri in batch] == [uri for _, uri in resolved]
    assert outcome.added == 205
    db.refresh(set_obj)
    assert (set_obj.status, set_obj.spotify_playlist_id) == ("exported", "playlist1")


def test_spotify_preflight_preserves_unresolved_and_requires_explicit_skip(
    client, auth_headers, db, test_user, monkeypatch
):
    set_obj = Set(owner_id=test_user.id, name="Spotify Set")
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
                track_id="spotify:known",
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
    test_user.spotify_access_token = "access-token"
    db.commit()
    monkeypatch.setattr(
        "app.services.setbuilder.export_spotify.spotify.search_songs",
        lambda *args: [],
    )

    def fake_export(db_, user, exported_set, resolved):
        from app.core.time import utcnow

        exported_set.spotify_playlist_id = "pl-1"
        exported_set.exported_at = utcnow()
        exported_set.status = "exported"
        return SimpleNamespace(
            playlist_id="pl-1", playlist_url="https://open.spotify.com/playlist/pl-1", added=1
        )

    monkeypatch.setattr(
        "app.services.setbuilder.export_spotify.export_to_spotify",
        fake_export,
    )

    preflight = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/preflight",
        json={"target": "spotify"},
        headers=auth_headers,
    )
    assert preflight.status_code == 200
    assert preflight.json()["resolved_count"] == 1
    assert preflight.json()["unresolved"][0]["title"] == "Missing"

    blocked = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/spotify",
        json={"skip_unresolved": False},
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["unresolved"][0]["title"] == "Missing"

    accepted = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/export/spotify",
        json={"skip_unresolved": True},
        headers=auth_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["added"] == 1
    assert accepted.json()["skipped"] == 1

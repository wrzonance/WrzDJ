"""API-boundary tests for WrzDJSet pool endpoints (issue #388)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus
from app.models.user import User


@pytest.fixture
def set_id(client: TestClient, auth_headers: dict) -> int:
    resp = client.post("/api/setbuilder/sets", json={"name": "Pool Set"}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def other_dj_headers(client: TestClient, db: Session) -> dict:
    from app.services.auth import get_password_hash

    user = User(username="otherdj", password_hash=get_password_hash("otherpassword1"), role="dj")
    db.add(user)
    db.commit()
    resp = client.post(
        "/api/auth/login", data={"username": "otherdj", "password": "otherpassword1"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_requests(db: Session, event: Event) -> None:
    db.add_all(
        [
            SongRequest(
                event_id=event.id,
                song_title="Pool Track A",
                artist="Artist A",
                dedupe_key="pk1",
                genre="House",
                bpm=126.0,
                musical_key="Am",
            ),
            SongRequest(
                event_id=event.id,
                song_title="Pool Track B",
                artist="Artist B",
                dedupe_key="pk2",
            ),
            SongRequest(
                event_id=event.id,
                song_title="Rejected Track",
                artist="Artist C",
                dedupe_key="pk3",
                status=RequestStatus.REJECTED.value,
            ),
        ]
    )
    db.commit()


class TestPoolOwnership:
    def test_pool_404_for_other_users_set(self, client, set_id, other_dj_headers):
        assert (
            client.get(f"/api/setbuilder/sets/{set_id}/pool", headers=other_dj_headers).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/setbuilder/sets/{set_id}/pool/import/event",
                json={"event_id": 1},
                headers=other_dj_headers,
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/setbuilder/sets/{set_id}/pool/tracks/remove",
                json={"track_ids": [1]},
                headers=other_dj_headers,
            ).status_code
            == 404
        )

    def test_pool_requires_auth(self, client, set_id):
        assert client.get(f"/api/setbuilder/sets/{set_id}/pool").status_code == 401


class TestEventImport:
    def test_import_event_end_to_end(self, client, db, auth_headers, set_id, test_event):
        _seed_requests(db, test_event)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/event",
            json={"event_id": test_event.id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added"] == 2  # rejected excluded
        assert body["deduped"] == 0
        assert body["source"]["kind"] == "event"
        assert body["source"]["label"] == test_event.name
        tracks = body["pool"]["tracks"]
        assert len(tracks) == 2
        assert all(t["source_id"] == body["source"]["id"] for t in tracks)
        by_title = {t["title"]: t for t in tracks}
        assert by_title["Pool Track A"]["camelot"] == "8A"
        assert by_title["Pool Track A"]["bpm"] == 126.0

    def test_import_unowned_event_404(
        self, client, db, set_id, auth_headers, other_dj_headers, test_event
    ):
        # other DJ creates a set, then tries to import OUR event
        resp = client.post(
            "/api/setbuilder/sets", json={"name": "Other Set"}, headers=other_dj_headers
        )
        other_set = resp.json()["id"]
        resp = client.post(
            f"/api/setbuilder/sets/{other_set}/pool/import/event",
            json={"event_id": test_event.id},
            headers=other_dj_headers,
        )
        assert resp.status_code == 404

    def test_import_already_enriched_pool_calls_zero_providers(
        self, client, db, auth_headers, set_id, test_event, monkeypatch
    ):
        """#542 acceptance criterion: importing an already-enriched pool performs
        ZERO provider enrichment calls (served from the candidate/store), and the
        master store is populated from the carried fields for later reuse."""
        from app.models.track import Track
        from app.services.setbuilder import pool as pool_mod
        from app.services.setbuilder.pool import dedupe_signature

        _seed_requests(db, test_event)  # "Pool Track A" arrives complete

        def _boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("enrich_track must not run for already-enriched candidates")

        monkeypatch.setattr(pool_mod, "enrich_track", _boom)

        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/event",
            json={"event_id": test_event.id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # The complete request populated the store from its carried fields.
        sig = dedupe_signature("Artist A", "Pool Track A")
        row = db.query(Track).filter(Track.signature == sig).one()
        assert row.bpm == 126.0
        assert row.genre == "House"
        assert row.musical_key == "8A"

    def test_reimport_event_dedupes_and_reuses_source(
        self, client, db, auth_headers, set_id, test_event
    ):
        _seed_requests(db, test_event)
        first = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/event",
            json={"event_id": test_event.id},
            headers=auth_headers,
        ).json()
        second = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/event",
            json={"event_id": test_event.id},
            headers=auth_headers,
        ).json()
        assert second["added"] == 0
        assert second["deduped"] == 2
        assert second["source"]["id"] == first["source"]["id"]
        assert len(second["pool"]["sources"]) == 1


class TestPlaylistImports:
    def test_import_tidal_playlist(self, client, auth_headers, set_id, monkeypatch):
        from app.services.setbuilder.pool import PoolCandidate

        monkeypatch.setattr(
            "app.services.setbuilder.pool.candidates_from_tidal",
            lambda db, user, pid: [
                PoolCandidate(
                    track_id="tidal:1",
                    title="Tidal Song",
                    artist="Tidal Artist",
                    bpm=128.0,
                    key="8A",
                    isrc="QZABC1234567",
                )
            ],
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/tidal",
            json={"playlist_id": "abc-123", "label": "Friday Warmup"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert (body["added"], body["deduped"]) == (1, 0)
        assert body["source"]["kind"] == "tidal"
        assert body["source"]["label"] == "Friday Warmup"

    def test_hydration_failure_on_first_candidate_keeps_source_and_imports_rest(
        self, client, auth_headers, set_id, db, monkeypatch
    ):
        """#554 FIX 1: a candidate whose hydration raises must not roll back the
        freshly-created (uncommitted) source row, or import_candidates would then
        insert pool tracks against a stale source.id (orphan/FK break). The source
        must survive and the remaining candidates must still import against it."""
        from app.models.set_pool import SetPoolSource, SetPoolTrack
        from app.services.setbuilder import pool as pool_mod
        from app.services.setbuilder.pool import PoolCandidate

        monkeypatch.setattr(
            "app.services.setbuilder.pool.candidates_from_tidal",
            lambda db, user, pid: [
                PoolCandidate(track_id="tidal:1", title="Boom Song", artist="Boom Artist"),
                PoolCandidate(
                    track_id="tidal:2", title="Good Song", artist="Good Artist", bpm=128.0, key="8A"
                ),
            ],
        )

        # Make ONLY the first candidate's hydration blow up mid-flow.
        real_hydrate_one = pool_mod._hydrate_one

        def _explode_first(db_, candidate, user, *, commit):
            if candidate.title == "Boom Song":
                raise RuntimeError("simulated hydration failure")
            return real_hydrate_one(db_, candidate, user, commit=commit)

        monkeypatch.setattr(pool_mod, "_hydrate_one", _explode_first)

        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/tidal",
            json={"playlist_id": "abc-123", "label": "Resilient"},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.json()
        source_id = resp.json()["source"]["id"]
        # The source row survived the per-candidate rollback ...
        survived = db.query(SetPoolSource).filter(SetPoolSource.id == source_id).one_or_none()
        assert survived is not None
        # ... and every imported pool track references that LIVE source (no orphan).
        tracks = db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_id).all()
        assert tracks  # at least the non-failing candidate imported
        assert all(t.source_id == source_id for t in tracks)

    def test_import_tidal_fetch_failure_502(self, client, auth_headers, set_id, monkeypatch):
        from app.services.tidal import TidalFetchError

        def boom(db, user, pid):
            raise TidalFetchError("nope")

        monkeypatch.setattr("app.services.setbuilder.pool.candidates_from_tidal", boom)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/tidal",
            json={"playlist_id": "abc-123"},
            headers=auth_headers,
        )
        assert resp.status_code == 502

    def test_import_beatport_playlist(self, client, auth_headers, set_id, monkeypatch):
        from app.services.setbuilder.pool import PoolCandidate

        monkeypatch.setattr(
            "app.services.setbuilder.pool.candidates_from_beatport",
            lambda db, user, pid: [
                PoolCandidate(track_id="beatport:9", title="Beat Song", artist="Beat Artist")
            ],
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/beatport",
            json={"playlist_id": "9"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["source"]["kind"] == "beatport"

    def test_playlist_id_charset_rejected(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/tidal",
            json={"playlist_id": "../../etc"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestUrlImport:
    def test_preview_invalid_url_422(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/url-preview",
            json={"url": "https://evil.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_preview_unsupported_provider(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/url-preview",
            json={"url": "https://music.apple.com/us/playlist/hits/pl.abc123"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["supported"] is False
        assert body["provider"] == "apple_music"
        assert body["message"]

    def test_preview_spotify(self, client, auth_headers, set_id, monkeypatch):
        monkeypatch.setattr(
            "app.services.setbuilder.pool.preview_public_playlist",
            lambda db, user, provider, pid: {
                "name": "Wedding Bangers 2026",
                "owner": "djwedding",
                "track_count": 87,
            },
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/url-preview",
            json={"url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["supported"] is True
        assert body["name"] == "Wedding Bangers 2026"
        assert body["track_count"] == 87

    def test_import_url_end_to_end(self, client, auth_headers, set_id, monkeypatch):
        from app.services.setbuilder.pool import PoolCandidate

        monkeypatch.setattr(
            "app.services.setbuilder.pool.candidates_from_public_url",
            lambda db, user, provider, pid: (
                "Wedding Bangers 2026",
                [
                    PoolCandidate(track_id="spotify:a", title="URL Song", artist="URL Artist"),
                    PoolCandidate(track_id="spotify:b", title="URL Song 2", artist="URL Artist"),
                ],
            ),
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/url",
            json={"url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added"] == 2
        assert body["source"]["kind"] == "public_url"
        assert body["source"]["label"] == "Wedding Bangers 2026"

    def test_import_url_provider_failure_502(self, client, auth_headers, set_id, monkeypatch):
        from app.services.setbuilder.pool import PoolImportError

        def boom(db, user, provider, pid):
            raise PoolImportError("Couldn't fetch that Spotify playlist — is it public?")

        monkeypatch.setattr("app.services.setbuilder.pool.candidates_from_public_url", boom)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/url",
            json={"url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
            headers=auth_headers,
        )
        assert resp.status_code == 502


class TestManualImport:
    def test_manual_import(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/manual",
            json={
                "title": "Bad Romance",
                "artist": "Lady Gaga",
                "bpm": 119,
                "key": "Am",
                "source_service": "tidal",
                "source_track_id": "555",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added"] == 1
        assert body["source"]["kind"] == "manual"
        track = body["pool"]["tracks"][0]
        assert track["track_id"] == "tidal:555"
        assert track["camelot"] == "8A"

    def test_manual_dedupe_toast_counts(self, client, auth_headers, set_id):
        payload = {"title": "Bad Romance", "artist": "Lady Gaga"}
        client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/manual",
            json=payload,
            headers=auth_headers,
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/manual",
            json=payload,
            headers=auth_headers,
        )
        assert (resp.json()["added"], resp.json()["deduped"]) == (0, 1)

    def test_manual_validation(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/manual",
            json={"title": "", "artist": "A", "bpm": 9999},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_manual_artwork_must_be_https(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/manual",
            json={"title": "T", "artist": "A", "artwork_url": "http://evil.com/x.jpg"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestRemovalFlows:
    def _import_two(self, client, auth_headers, set_id):
        for title in ("Song One", "Song Two"):
            client.post(
                f"/api/setbuilder/sets/{set_id}/pool/import/manual",
                json={"title": title, "artist": "Artist"},
                headers=auth_headers,
            )
        pool_state = client.get(f"/api/setbuilder/sets/{set_id}/pool", headers=auth_headers).json()
        return pool_state

    def test_remove_tracks(self, client, auth_headers, set_id):
        state = self._import_two(client, auth_headers, set_id)
        ids = [t["id"] for t in state["tracks"]]
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/tracks/remove",
            json={"track_ids": ids[:1]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["removed"] == 1
        assert len(body["pool"]["tracks"]) == 1

    def test_remove_source_counts_consistent(
        self, client, db, auth_headers, set_id, test_event, monkeypatch
    ):
        from app.services.setbuilder.pool import PoolCandidate

        _seed_requests(db, test_event)
        client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/event",
            json={"event_id": test_event.id},
            headers=auth_headers,
        )
        monkeypatch.setattr(
            "app.services.setbuilder.pool.candidates_from_tidal",
            lambda db_, user, pid: [
                PoolCandidate(track_id="tidal:1", title="Unique Tidal", artist="T")
            ],
        )
        imp = client.post(
            f"/api/setbuilder/sets/{set_id}/pool/import/tidal",
            json={"playlist_id": "p1"},
            headers=auth_headers,
        ).json()
        tidal_source_id = imp["source"]["id"]
        resp = client.delete(
            f"/api/setbuilder/sets/{set_id}/pool/sources/{tidal_source_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["removed"] == 1
        # event tracks untouched, tidal source gone
        assert len(body["pool"]["tracks"]) == 2
        assert all(s["id"] != tidal_source_id for s in body["pool"]["sources"])

    def test_remove_source_404_for_other_set(self, client, auth_headers, other_dj_headers, set_id):
        state = self._import_two(client, auth_headers, set_id)
        source_id = state["sources"][0]["id"]
        # other DJ's set with same source id namespace
        other_set = client.post(
            "/api/setbuilder/sets", json={"name": "Other"}, headers=other_dj_headers
        ).json()["id"]
        resp = client.delete(
            f"/api/setbuilder/sets/{other_set}/pool/sources/{source_id}",
            headers=other_dj_headers,
        )
        assert resp.status_code == 404


class TestBuilderPlaylists:
    def test_playlists_disconnected(self, client, auth_headers):
        resp = client.get("/api/setbuilder/playlists", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tidal_connected"] is False
        assert body["beatport_connected"] is False
        assert body["tidal"] == []
        assert body["beatport"] == []

    def test_playlists_requires_active_user(self, client, pending_headers):
        resp = client.get("/api/setbuilder/playlists", headers=pending_headers)
        assert resp.status_code == 403

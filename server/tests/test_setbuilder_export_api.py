"""API-boundary tests for WrzDJSet export endpoints (issue #396)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack


@pytest.fixture
def set_id(client: TestClient, auth_headers: dict) -> int:
    resp = client.post("/api/setbuilder/sets", json={"name": "Export Set"}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _seed_pool(db: Session, set_id: int, *, with_orphan_slot: bool = False) -> None:
    src = SetPoolSource(set_id=set_id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.add_all(
        [
            SetPoolTrack(
                set_id=set_id,
                source_id=src.id,
                title="Opener",
                artist="DJ One",
                track_id="tidal:101",
                duration_sec=200,
                bpm=124.0,
                camelot="8A",
                dedupe_sig="sig1",
            ),
            SetPoolTrack(
                set_id=set_id,
                source_id=src.id,
                title="Closer",
                artist="DJ Two",
                track_id="beatport:202",
                dedupe_sig="sig2",
            ),
        ]
    )
    if with_orphan_slot:
        db.add(SetSlot(set_id=set_id, position=0, track_id="tidal:101"))
        db.add(SetSlot(set_id=set_id, position=1, track_id="spotify:gone"))
    db.commit()


def _connect_tidal(db: Session, test_user) -> None:
    test_user.tidal_access_token = "tok"  # nosec B105 — test fixture
    db.commit()


class TestPreflight:
    def test_owner_scoping_404(self, client, auth_headers):
        resp = client.post(
            "/api/setbuilder/sets/99999/export/preflight",
            json={"target": "m3u"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight", json={"target": "m3u"}
        )
        assert resp.status_code == 401

    def test_file_target_reports_pool_fallback_and_no_unresolved(
        self, client, auth_headers, db, set_id
    ):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "rekordbox"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "pool"
        assert body["total"] == 2
        assert body["resolved_count"] == 2
        assert body["unresolved"] == []

    def test_file_target_flags_orphan_slots(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id, with_orphan_slot=True)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "m3u"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["source"] == "timeline"
        assert body["total"] == 2
        assert body["resolved_count"] == 1
        assert body["unresolved"][0]["track_id"] == "spotify:gone"
        assert body["unresolved"][0]["reason"] == "missing_metadata"

    def test_enginedj_and_lexicon_preflight_use_file_branch(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        for target in ("enginedj", "lexicon"):
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/export/preflight",
                json={"target": target},
                headers=auth_headers,
            )
            assert resp.status_code == 200, target
            body = resp.json()
            assert body["source"] == "pool"
            assert body["resolved_count"] == 2
            # File targets never run Tidal matching, so tidal_connected stays null.
            assert body["tidal_connected"] is None

    def test_tidal_target_not_connected(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "tidal"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["tidal_connected"] is False
        assert body["resolved_count"] == 0

    def test_tidal_target_resolves_and_lists_unresolved(
        self, client, auth_headers, db, set_id, test_user, monkeypatch
    ):
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "tidal"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["tidal_connected"] is True
        assert body["resolved_count"] == 1  # the tidal:101 track
        assert body["unresolved"][0]["title"] == "Closer"
        assert body["unresolved"][0]["reason"] == "no_tidal_match"


class TestTidalExport:
    def _fake_session(self):
        return SimpleNamespace(
            user=SimpleNamespace(create_playlist=lambda name, desc: SimpleNamespace(id="pl-1"))
        )

    def test_unresolved_interrupts_with_409(
        self, client, auth_headers, db, set_id, test_user, monkeypatch
    ):
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "unresolved_tracks"
        assert detail["unresolved"][0]["title"] == "Closer"
        db.expire_all()
        assert db.get(Set, set_id).status == "draft"

    def test_skip_unresolved_exports_resolved_only(
        self, client, auth_headers, db, set_id, test_user, monkeypatch
    ):
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )
        monkeypatch.setattr(
            "app.services.tidal.get_tidal_session", lambda db_, u: self._fake_session()
        )
        calls = {}

        def fake_add(db_, u, playlist_id, track_ids):
            calls["track_ids"] = track_ids
            return True

        monkeypatch.setattr("app.services.tidal.add_tracks_to_playlist", fake_add)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["playlist_id"] == "pl-1"
        assert body["added"] == 1
        assert body["skipped"] == 1
        assert body["status"] == "exported"
        assert calls["track_ids"] == ["101"]
        db.expire_all()
        s = db.get(Set, set_id)
        assert s.status == "exported"
        assert s.tidal_playlist_id == "pl-1"

    def test_not_connected_400(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_empty_set_400(self, client, auth_headers, db, set_id, test_user):
        _connect_tidal(db, test_user)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_tidal_export_error_502(self, client, auth_headers, db, set_id, test_user, monkeypatch):
        """A generic exception from tidalapi during playlist creation is wrapped by
        export_to_tidal into TidalExportError and surfaces as 502 at the endpoint."""
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )

        broken_session = SimpleNamespace(
            user=SimpleNamespace(
                create_playlist=lambda name, desc: (_ for _ in ()).throw(Exception("boom"))
            )
        )
        monkeypatch.setattr("app.services.tidal.get_tidal_session", lambda db_, u: broken_session)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 502
        db.expire_all()
        assert db.get(Set, set_id).status == "draft"


class TestFileExport:
    def test_rekordbox_download(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "rekordbox", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert 'filename="Export Set.xml"' in resp.headers["content-disposition"]
        assert "DJ_PLAYLISTS" in resp.text

    def test_enginedj_and_lexicon_route_to_rekordbox_xml(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        for fmt in ("enginedj", "lexicon"):
            resp = client.post(
                f"/api/setbuilder/sets/{set_id}/export/file",
                json={"format": fmt, "skip_unresolved": False},
                headers=auth_headers,
            )
            assert resp.status_code == 200, fmt
            assert resp.headers["content-type"].startswith("application/xml")
            assert 'filename="Export Set.xml"' in resp.headers["content-disposition"]
            assert "DJ_PLAYLISTS" in resp.text

    def test_enginedj_export_does_not_mutate_status(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "enginedj", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        db.expire_all()
        assert db.get(Set, set_id).status == "draft"

    def test_m3u_and_txt_downloads(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        m3u = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "m3u", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert m3u.status_code == 200
        assert m3u.text.startswith("#EXTM3U")
        assert 'filename="Export Set.m3u8"' in m3u.headers["content-disposition"]
        txt = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "txt", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert txt.status_code == 200
        assert "1. DJ One - Opener" in txt.text

    def test_unresolved_interrupts_with_409_then_skip_succeeds(
        self, client, auth_headers, db, set_id
    ):
        _seed_pool(db, set_id, with_orphan_slot=True)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "m3u", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "unresolved_tracks"
        resp2 = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "m3u", "skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert "DJ One - Opener" in resp2.text
        assert "spotify:gone" not in resp2.text

    def test_file_export_does_not_mutate_status(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "txt", "skip_unresolved": False},
            headers=auth_headers,
        )
        db.expire_all()
        assert db.get(Set, set_id).status == "draft"

    def test_empty_set_400(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "txt", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 400

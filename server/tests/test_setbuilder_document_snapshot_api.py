"""API-boundary tests for WrzDJSet document snapshots (issue #395)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.set import SetCurvePoint, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services.auth import get_password_hash


def _make_second_dj(db: Session):
    from app.models.user import User

    user = User(username="snapother", password_hash=get_password_hash("otherpassword1"), role="dj")
    db.add(user)
    db.commit()
    return user


def _login(client, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_seeded_set(client, db: Session, auth_headers: dict) -> int:
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Snapshot Set"}, headers=auth_headers
    )
    assert created.status_code == 201, created.json()
    set_id = created.json()["id"]
    source = SetPoolSource(
        set_id=set_id,
        kind="manual",
        external_ref=None,
        label="Manual",
        meta="Single-track search",
        created_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
    )
    db.add(source)
    db.flush()
    db.add_all(
        [
            SetSlot(
                id=9001,
                set_id=set_id,
                position=0,
                track_id="manual:1",
                locked=True,
                notes="opener",
                target_energy=5.5,
            ),
            SetSlot(
                id=9002,
                set_id=set_id,
                position=1,
                track_id="manual:2",
                locked=False,
                target_energy=7.0,
            ),
            SetPoolTrack(
                id=9101,
                set_id=set_id,
                source_id=source.id,
                track_id="manual:1",
                title="Snapshot One",
                artist="Artist One",
                bpm=124.0,
                key="8A",
                camelot="8A",
                energy=6,
                duration_sec=300,
                dedupe_sig="sig-one",
                created_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            ),
            SetPoolTrack(
                id=9102,
                set_id=set_id,
                source_id=source.id,
                track_id="manual:2",
                title="Snapshot Two",
                artist="Artist Two",
                energy=8,
                dedupe_sig="sig-two",
                created_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            ),
            SetCurvePoint(
                id=9201,
                set_id=set_id,
                position_sec=30,
                energy=0,
                label="Dinner",
                is_slow_window_start=True,
            ),
            SetCurvePoint(
                id=9202,
                set_id=set_id,
                position_sec=90,
                energy=0,
                is_slow_window_end=True,
            ),
        ]
    )
    db.commit()
    return set_id


def test_document_snapshot_round_trips_destructive_builder_state(client, db, auth_headers):
    set_id = _create_seeded_set(client, db, auth_headers)

    original = client.get(f"/api/setbuilder/sets/{set_id}/document", headers=auth_headers).json()

    client.patch(
        f"/api/setbuilder/sets/{set_id}/slots/9001/target",
        json={"target_energy": 9.5},
        headers=auth_headers,
    )
    client.delete(
        f"/api/setbuilder/sets/{set_id}/pool/sources/{original['pool']['sources'][0]['id']}",
        headers=auth_headers,
    )
    client.put(
        f"/api/setbuilder/sets/{set_id}/vibe-windows",
        json={"windows": [{"t0_sec": 120, "t1_sec": 150, "label": "Peak"}]},
        headers=auth_headers,
    )

    restore = client.put(
        f"/api/setbuilder/sets/{set_id}/document", json=original, headers=auth_headers
    )
    assert restore.status_code == 200, restore.json()
    restored = restore.json()
    assert restored["slots"] == original["slots"]
    assert restored["pool"] == original["pool"]
    assert restored["curve_points"] == original["curve_points"]


def test_document_snapshot_owner_isolation(client, db, auth_headers):
    set_id = _create_seeded_set(client, db, auth_headers)
    _make_second_dj(db)
    other_headers = _login(client, "snapother", "otherpassword1")

    assert (
        client.get(f"/api/setbuilder/sets/{set_id}/document", headers=other_headers).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/setbuilder/sets/{set_id}/document",
            json={
                "settings": {},
                "slots": [],
                "curve_points": [],
                "pool": {"sources": [], "tracks": []},
            },
            headers=other_headers,
        ).status_code
        == 404
    )


def test_document_snapshot_rejects_tracks_for_missing_source(client, auth_headers):
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Bad Snapshot"}, headers=auth_headers
    )
    set_id = created.json()["id"]
    payload = {
        "settings": {"key_strictness": 0.2},
        "slots": [],
        "curve_points": [],
        "pool": {
            "sources": [],
            "tracks": [
                {
                    "id": 1,
                    "source_id": 404,
                    "track_id": "manual:bad",
                    "title": "Bad",
                    "artist": "Actor",
                    "dedupe_sig": "bad",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        },
    }
    resp = client.put(f"/api/setbuilder/sets/{set_id}/document", json=payload, headers=auth_headers)
    assert resp.status_code == 422

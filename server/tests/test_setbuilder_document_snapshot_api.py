"""API-boundary tests for WrzDJSet document snapshots (issue #395)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.set import SetCurvePoint, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services.auth import get_password_hash


def _without_keys(row: dict, *keys: str) -> dict:
    return {key: value for key, value in row.items() if key not in keys}


def _logical_snapshot(snapshot: dict) -> dict:
    return {
        "settings": snapshot["settings"],
        "slots": [_without_keys(slot, "id") for slot in snapshot["slots"]],
        "curve_points": [_without_keys(point, "id") for point in snapshot["curve_points"]],
        "pool": {
            "sources": [_without_keys(source, "id") for source in snapshot["pool"]["sources"]],
            # enrichment_status is intentionally re-derived on restore (no worker runs
            # there), so it is not part of the round-trip invariant; its derivation is
            # covered by test_document_snapshot_restore_derives_terminal_enrichment_status.
            "tracks": [
                _without_keys(track, "id", "source_id", "enrichment_status")
                for track in snapshot["pool"]["tracks"]
            ],
        },
    }


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

    original_resp = client.get(f"/api/setbuilder/sets/{set_id}/document", headers=auth_headers)
    assert original_resp.status_code == 200, original_resp.json()
    original = original_resp.json()

    patch_resp = client.patch(
        f"/api/setbuilder/sets/{set_id}/slots/9001/target",
        json={"target_energy": 9.5},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.json()

    delete_resp = client.delete(
        f"/api/setbuilder/sets/{set_id}/pool/sources/{original['pool']['sources'][0]['id']}",
        headers=auth_headers,
    )
    assert delete_resp.status_code == 200, delete_resp.json()

    windows_resp = client.put(
        f"/api/setbuilder/sets/{set_id}/vibe-windows",
        json={"windows": [{"t0_sec": 120, "t1_sec": 150, "label": "Peak"}]},
        headers=auth_headers,
    )
    assert windows_resp.status_code == 200, windows_resp.json()

    restore = client.put(
        f"/api/setbuilder/sets/{set_id}/document", json=original, headers=auth_headers
    )
    assert restore.status_code == 200, restore.json()
    restored = restore.json()
    assert _logical_snapshot(restored) == _logical_snapshot(original)


def test_document_snapshot_restore_derives_terminal_enrichment_status(client, db, auth_headers):
    # Regression: a restored pool track must never come back "pending" — restore
    # enqueues no background worker, so a legacy snapshot (whose tracks default to
    # "pending") would otherwise report in_progress forever. Status is re-derived
    # from the contract fields: full contract -> enriched, any gap -> failed.
    set_id = _create_seeded_set(client, db, auth_headers)
    payload = client.get(f"/api/setbuilder/sets/{set_id}/document", headers=auth_headers).json()

    tracks = sorted(payload["pool"]["tracks"], key=lambda t: t["track_id"])
    complete, gappy = tracks[0], tracks[1]
    # Make the first track contract-complete; both arrive as "pending" (legacy).
    complete["genre"] = "House"
    complete["enrichment_status"] = "pending"
    gappy["enrichment_status"] = "pending"

    restore = client.put(
        f"/api/setbuilder/sets/{set_id}/document", json=payload, headers=auth_headers
    )
    assert restore.status_code == 200, restore.json()

    restored = {t["track_id"]: t for t in restore.json()["pool"]["tracks"]}
    assert restored[complete["track_id"]]["enrichment_status"] == "enriched"
    assert restored[gappy["track_id"]]["enrichment_status"] == "failed"
    # And never left pending.
    assert all(t["enrichment_status"] != "pending" for t in restored.values())


def test_document_snapshot_restore_ignores_client_primary_keys(client, db, auth_headers):
    set_id = _create_seeded_set(client, db, auth_headers)
    other = client.post("/api/setbuilder/sets", json={"name": "Other Set"}, headers=auth_headers)
    assert other.status_code == 201, other.json()
    other_set_id = other.json()["id"]
    other_source = SetPoolSource(
        id=9903,
        set_id=other_set_id,
        kind="manual",
        external_ref=None,
        label="Other",
    )
    db.add(other_source)
    db.flush()
    db.add_all(
        [
            SetSlot(id=9901, set_id=other_set_id, position=0, track_id="other:1"),
            SetCurvePoint(id=9902, set_id=other_set_id, position_sec=1, energy=1),
            SetPoolTrack(
                id=9904,
                set_id=other_set_id,
                source_id=other_source.id,
                track_id="other:1",
                title="Other",
                artist="Artist",
                dedupe_sig="other",
            ),
        ]
    )
    db.commit()

    payload_resp = client.get(f"/api/setbuilder/sets/{set_id}/document", headers=auth_headers)
    assert payload_resp.status_code == 200, payload_resp.json()
    payload = payload_resp.json()
    payload["slots"][0]["id"] = 9901
    payload["curve_points"][0]["id"] = 9902
    payload["pool"]["sources"][0]["id"] = 9903
    for track in payload["pool"]["tracks"]:
        track["id"] = 9904
        track["source_id"] = 9903

    restore = client.put(
        f"/api/setbuilder/sets/{set_id}/document", json=payload, headers=auth_headers
    )
    assert restore.status_code == 200, restore.json()
    restored = restore.json()
    restored_source_ids = {source["id"] for source in restored["pool"]["sources"]}
    assert restored["slots"][0]["id"] != 9901
    assert restored["curve_points"][0]["id"] != 9902
    assert restored["pool"]["sources"][0]["id"] != 9903
    assert all(track["id"] != 9904 for track in restored["pool"]["tracks"])
    assert all(track["source_id"] in restored_source_ids for track in restored["pool"]["tracks"])
    assert all(track["source_id"] != 9903 for track in restored["pool"]["tracks"])


def test_document_snapshot_restore_remaps_synthetic_pool_slot_ids(client, db, auth_headers):
    # Regression for 09e2ea69: restored pool rows get new ids, so synthetic slot ids remap.
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Synthetic Pool Ids"}, headers=auth_headers
    )
    assert created.status_code == 201, created.json()
    set_id = created.json()["id"]
    source = SetPoolSource(
        id=9300,
        set_id=set_id,
        kind="manual",
        external_ref=None,
        label="Manual",
    )
    db.add(source)
    db.flush()
    track = SetPoolTrack(
        id=9301,
        set_id=set_id,
        source_id=source.id,
        track_id=None,
        title="Manual Snapshot",
        artist="Manual Artist",
        dedupe_sig="manual-snapshot",
    )
    db.add(track)
    db.add(SetSlot(id=9302, set_id=set_id, position=0, track_id=f"pool:{track.id}"))
    db.commit()

    payload_resp = client.get(f"/api/setbuilder/sets/{set_id}/document", headers=auth_headers)
    assert payload_resp.status_code == 200, payload_resp.json()

    restore = client.put(
        f"/api/setbuilder/sets/{set_id}/document",
        json=payload_resp.json(),
        headers=auth_headers,
    )

    assert restore.status_code == 200, restore.json()
    restored = restore.json()
    restored_track_id = restored["pool"]["tracks"][0]["id"]
    assert restored_track_id != 9301
    assert restored["slots"][0]["track_id"] == f"pool:{restored_track_id}"
    slots = client.get(f"/api/setbuilder/sets/{set_id}/slots", headers=auth_headers).json()
    assert slots[0]["pool_track_id"] == restored_track_id
    assert slots[0]["title"] == "Manual Snapshot"


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
    assert created.status_code == 201, created.json()
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

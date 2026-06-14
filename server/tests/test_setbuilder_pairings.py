"""API + service tests for WrzDJSet DJ-curated pairings (#392)."""

from sqlalchemy.exc import IntegrityError

from app.models.set import Set, SetSlot
from app.models.set_pairing import SetPairing
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.services.setbuilder import pairing_scoring, pairings


def _mk_set(client, auth_headers, name="Pair Set"):
    resp = client.post("/api/setbuilder/sets", json={"name": name}, headers=auth_headers)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def _mk_pool_track(db, set_id, track_id, title, artist, *, bpm=120.0, camelot="8A"):
    source = (
        db.query(SetPoolSource)
        .filter(SetPoolSource.set_id == set_id, SetPoolSource.kind == "manual")
        .one_or_none()
    )
    if source is None:
        source = SetPoolSource(set_id=set_id, kind="manual", label="Manual")
        db.add(source)
        db.flush()
    track = SetPoolTrack(
        set_id=set_id,
        source_id=source.id,
        track_id=track_id,
        title=title,
        artist=artist,
        bpm=bpm,
        key=camelot,
        camelot=camelot,
        dedupe_sig=f"sig-{track_id}",
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def test_create_list_update_pairing_owner_scoped(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings",
        json={
            "from_track_id": "tidal:from",
            "into_track_id": "tidal:into",
            "cue_in_sec": 48,
            "note": "Loop the outro before the vocal.",
            "tags": ["vocal", "safe"],
            "increment_use_count": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.json()
    created = resp.json()
    assert created["from_track_id"] == "tidal:from"
    assert created["into_track_id"] == "tidal:into"
    assert created["use_count"] == 1
    assert created["tags"] == ["vocal", "safe"]

    resp = client.get(f"/api/setbuilder/sets/{set_obj['id']}/pairings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["pairings"][0]["note"] == "Loop the outro before the vocal."

    resp = client.patch(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings/{created['id']}",
        json={"note": "Updated", "tags": ["Peak"], "cue_in_sec": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["note"] == "Updated"
    assert resp.json()["cue_in_sec"] is None
    assert resp.json()["tags"] == ["peak"]


def test_pairings_join_pool_track_display_and_search(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    from_track = _mk_pool_track(db, set_obj["id"], "tidal:1", "Strobe", "deadmau5")
    _mk_pool_track(db, set_obj["id"], "tidal:2", "Ghosts", "Deadmau5", bpm=124, camelot="9A")

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings",
        json={"from_track_id": "tidal:1", "into_track_id": "tidal:2", "tags": ["progressive"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.json()

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings?query=strobe",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["pairings"][0]["from_track"]["id"] == from_track.id
    assert body["pairings"][0]["from_track"]["title"] == "Strobe"
    assert body["pairings"][0]["into_track"]["camelot"] == "9A"


def test_pairing_create_is_idempotent_and_can_increment_uses(client, auth_headers):
    set_obj = _mk_set(client, auth_headers)
    payload = {
        "from_track_id": "tidal:a",
        "into_track_id": "tidal:b",
        "increment_use_count": True,
    }
    first = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings", json=payload, headers=auth_headers
    )
    assert first.status_code == 201, first.json()
    second = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings", json=payload, headers=auth_headers
    )
    assert second.status_code == 200, second.json()
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["use_count"] == 2


def test_pairing_insert_race_returns_existing_pairing(client, auth_headers, db, monkeypatch):
    """Regression for 9e57f7e: concurrent upsert unique races stay idempotent."""
    set_obj = _mk_set(client, auth_headers)
    set_model = db.get(Set, set_obj["id"])
    assert set_model is not None

    real_commit = db.commit
    real_rollback = db.rollback
    raised = False

    def flaky_commit():
        nonlocal raised
        if not raised:
            raised = True
            raise IntegrityError("insert set_pairings", {}, Exception("duplicate"))
        real_commit()

    def seed_concurrent_row():
        real_rollback()
        db.add(
            SetPairing(
                set_id=set_obj["id"],
                from_track_id="tidal:race-a",
                into_track_id="tidal:race-b",
                note="other writer",
                tags_json="[]",
            )
        )
        real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    monkeypatch.setattr(db, "rollback", seed_concurrent_row)

    pairing, created = pairings.upsert_pairing(
        db,
        set_model,
        from_track_id="tidal:race-a",
        into_track_id="tidal:race-b",
        cue_in_sec=16,
        note="winner",
        tags=["Peak"],
        increment_use_count=True,
    )

    assert created is False
    assert pairing.note == "winner"
    assert pairing.cue_in_sec == 16
    assert pairing.use_count == 1
    assert pairings.tags_for_pairing(pairing) == ["peak"]


def test_pairing_validation_and_owner_isolation(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings",
        json={"from_track_id": "tidal:a", "into_track_id": "tidal:a"},
        headers=auth_headers,
    )
    assert resp.status_code == 400

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings",
        json={"from_track_id": "tidal:a", "into_track_id": "tidal:b", "tags": [" x" * 30]},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    resp = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings?query={'x' * 201}",
        headers=auth_headers,
    )
    assert resp.status_code == 422

    from app.models.user import User
    from app.services.auth import get_password_hash

    other = User(username="otherpair", password_hash=get_password_hash("x" * 12), role="dj")
    db.add(other)
    db.commit()
    login = client.post(
        "/api/auth/login",
        data={"username": "otherpair", "password": "xxxxxxxxxxxx"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    their_set = _mk_set(client, other_headers, "Theirs")

    resp = client.get(f"/api/setbuilder/sets/{their_set['id']}/pairings", headers=auth_headers)
    assert resp.status_code == 404


def test_pairing_routes_require_active_dj(client, auth_headers, pending_headers):
    set_obj = _mk_set(client, auth_headers)
    payload = {"from_track_id": "tidal:a", "into_track_id": "tidal:b"}

    assert client.get(f"/api/setbuilder/sets/{set_obj['id']}/pairings").status_code == 401
    assert (
        client.post(f"/api/setbuilder/sets/{set_obj['id']}/pairings", json=payload).status_code
        == 401
    )
    assert (
        client.get(
            f"/api/setbuilder/sets/{set_obj['id']}/pairings", headers=pending_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/setbuilder/sets/{set_obj['id']}/pairings",
            json=payload,
            headers=pending_headers,
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/setbuilder/sets/{set_obj['id']}/pairings/1",
            json={"note": "x"},
        ).status_code
        == 401
    )
    assert client.delete(f"/api/setbuilder/sets/{set_obj['id']}/pairings/1").status_code == 401
    assert (
        client.patch(
            f"/api/setbuilder/sets/{set_obj['id']}/pairings/1",
            json={"note": "x"},
            headers=pending_headers,
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/setbuilder/sets/{set_obj['id']}/pairings/1",
            headers=pending_headers,
        ).status_code
        == 403
    )


def test_delete_pairing_removes_timeline_marker(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    db.add(SetSlot(set_id=set_obj["id"], position=0, track_id="tidal:a"))
    db.add(SetSlot(set_id=set_obj["id"], position=1, track_id="tidal:b"))
    db.commit()
    created = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings",
        json={"from_track_id": "tidal:a", "into_track_id": "tidal:b"},
        headers=auth_headers,
    ).json()

    resp = client.delete(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings/{created['id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 204
    slots = client.get(f"/api/setbuilder/sets/{set_obj['id']}/slots", headers=auth_headers).json()
    assert slots[0]["next_pairing_id"] is None
    assert slots[0]["next_is_dj_pairing"] is False


def test_timeline_capture_pairing_marks_slots_and_score_hook(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    db.add(SetSlot(set_id=set_obj["id"], position=0, track_id="tidal:a"))
    db.add(SetSlot(set_id=set_obj["id"], position=1, track_id="tidal:b"))
    db.commit()

    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/pairings",
        json={
            "from_track_id": "tidal:a",
            "into_track_id": "tidal:b",
            "increment_use_count": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.json()

    slots = client.get(f"/api/setbuilder/sets/{set_obj['id']}/slots", headers=auth_headers).json()
    assert slots[0]["next_pairing_id"] == resp.json()["id"]
    assert slots[0]["next_is_dj_pairing"] is True
    assert slots[1]["next_is_dj_pairing"] is False

    pairings = pairing_scoring.load_pairing_index(db, set_obj["id"])
    paired = pairing_scoring.apply_pairing_boost("tidal:a", "tidal:b", 82.0, pairings)
    unpaired = pairing_scoring.apply_pairing_boost("tidal:a", "tidal:c", 95.0, pairings)
    assert paired.score == 100.0
    assert paired.is_dj_pairing is True
    assert paired.pairing_boost == 20.0
    assert paired.score > unpaired.score

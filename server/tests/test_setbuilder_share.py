"""Tests for WrzDJSet sharing + duplication (issue #398).

Service level: duplicate copies children and resets lifecycle state;
token regenerate/revoke; malformed-token short circuit.
API level: owner-scoped share/revoke/duplicate routes, public view-only
projection (no ids / owner identity leakage), auth gating.
"""

from app.models.set import Set, SetCurvePoint, SetSlot
from app.services.auth import get_password_hash
from app.services.setbuilder import share_service


def _seed_set(db, owner_id, **overrides) -> Set:
    fields = {
        "owner_id": owner_id,
        "name": "Warehouse Closer",
        "vibe_theme": "dark-techno",
        "target_duration_sec": 3600,
        "bpm_floor": 124,
        "bpm_ceiling": 132,
        "key_strictness": 0.7,
        "status": "locked",
        "tidal_playlist_id": "pl-123",
    }
    fields.update(overrides)
    set_obj = Set(**fields)
    db.add(set_obj)
    db.flush()
    db.add(
        SetSlot(
            set_id=set_obj.id,
            position=1,
            track_id="tidal:111",
            locked=True,
            notes="opener",
            transition_score=0.9,
            transition_warnings='["bpm jump"]',
        )
    )
    db.add(SetSlot(set_id=set_obj.id, position=2, track_id="tidal:222"))
    db.add(
        SetCurvePoint(
            set_id=set_obj.id,
            position_sec=0,
            energy=4,
            label="warmup",
            is_slow_window_start=True,
        )
    )
    db.add(
        SetCurvePoint(
            set_id=set_obj.id,
            position_sec=1800,
            energy=9,
            label="peak",
            is_slow_window_end=True,
        )
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _make_second_dj(db):
    from app.models.user import User

    user = User(username="otherdj", password_hash=get_password_hash("x" * 12), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, username, password):
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Service: duplicate
# ---------------------------------------------------------------------------


def test_duplicate_copies_children_and_resets_state(db, test_user):
    src = _seed_set(db, test_user.id)
    src.share_token = "A" * 43
    db.commit()

    dup = share_service.duplicate_set(db, src)

    assert dup.id != src.id
    assert dup.name == "Warehouse Closer (copy)"
    assert dup.owner_id == test_user.id
    # targets + vibe copied
    assert dup.vibe_theme == "dark-techno"
    assert dup.target_duration_sec == 3600
    assert dup.bpm_floor == 124
    assert dup.bpm_ceiling == 132
    assert dup.key_strictness == 0.7
    # lifecycle reset
    assert dup.status == "draft"
    assert dup.sharing_mode == "private"
    assert dup.share_token is None
    assert dup.tidal_playlist_id is None
    assert dup.exported_at is None
    # slots copied with all fields
    assert [(s.position, s.track_id) for s in dup.slots] == [(1, "tidal:111"), (2, "tidal:222")]
    first = next(s for s in dup.slots if s.position == 1)
    assert first.locked is True
    assert first.notes == "opener"
    assert first.transition_score == 0.9
    assert first.transition_warnings == '["bpm jump"]'
    # curve (incl. slow/vibe windows) copied
    points = sorted(dup.curve_points, key=lambda c: c.position_sec)
    assert [(c.position_sec, c.energy, c.label) for c in points] == [
        (0, 4, "warmup"),
        (1800, 9, "peak"),
    ]
    assert points[0].is_slow_window_start is True
    assert points[1].is_slow_window_end is True
    # source untouched
    db.refresh(src)
    assert src.status == "locked"
    assert len(src.slots) == 2


def test_duplicate_truncates_long_name(db, test_user):
    src = _seed_set(db, test_user.id, name="x" * 120)
    dup = share_service.duplicate_set(db, src)
    assert len(dup.name) == 120
    assert dup.name.endswith(" (copy)")


# ---------------------------------------------------------------------------
# Service: token lifecycle
# ---------------------------------------------------------------------------


def test_regenerate_changes_token(db, test_user):
    src = _seed_set(db, test_user.id)
    share_service.regenerate_share_token(db, src)
    first = src.share_token
    assert first is not None and len(first) >= 32
    share_service.regenerate_share_token(db, src)
    assert src.share_token != first


def test_revoke_nulls_token(db, test_user):
    src = _seed_set(db, test_user.id)
    share_service.regenerate_share_token(db, src)
    share_service.revoke_share_token(db, src)
    assert src.share_token is None


def test_get_by_token_rejects_bad_format(db, test_user):
    src = _seed_set(db, test_user.id)
    share_service.regenerate_share_token(db, src)
    assert share_service.get_set_by_share_token(db, src.share_token) is src
    assert share_service.get_set_by_share_token(db, "short") is None
    assert share_service.get_set_by_share_token(db, "x" * 200) is None
    assert share_service.get_set_by_share_token(db, "bad token!@#" + "a" * 20) is None


# ---------------------------------------------------------------------------
# API: owner share routes
# ---------------------------------------------------------------------------


def test_share_create_and_rotate(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    resp = client.post(f"/api/setbuilder/sets/{src.id}/share", headers=auth_headers)
    assert resp.status_code == 200, resp.json()
    first = resp.json()["share_token"]
    assert len(first) >= 32

    # rotating invalidates the old link
    resp = client.post(f"/api/setbuilder/sets/{src.id}/share", headers=auth_headers)
    second = resp.json()["share_token"]
    assert second != first
    assert client.get(f"/api/public/setbuilder/shared/{first}").status_code == 404
    assert client.get(f"/api/public/setbuilder/shared/{second}").status_code == 200


def test_share_revoke(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    token = client.post(f"/api/setbuilder/sets/{src.id}/share", headers=auth_headers).json()[
        "share_token"
    ]
    resp = client.delete(f"/api/setbuilder/sets/{src.id}/share", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/api/public/setbuilder/shared/{token}").status_code == 404


def test_share_routes_owner_scoped(client, auth_headers, db, test_user):
    other = _make_second_dj(db)
    theirs = _seed_set(db, other.id)
    assert (
        client.post(f"/api/setbuilder/sets/{theirs.id}/share", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.delete(f"/api/setbuilder/sets/{theirs.id}/share", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.post(f"/api/setbuilder/sets/{theirs.id}/duplicate", headers=auth_headers).status_code
        == 404
    )


def test_share_routes_require_auth(client, db, test_user, pending_headers):
    src = _seed_set(db, test_user.id)
    assert client.post(f"/api/setbuilder/sets/{src.id}/share").status_code == 401
    assert client.delete(f"/api/setbuilder/sets/{src.id}/share").status_code == 401
    assert client.post(f"/api/setbuilder/sets/{src.id}/duplicate").status_code == 401
    assert (
        client.post(f"/api/setbuilder/sets/{src.id}/share", headers=pending_headers).status_code
        == 403
    )
    assert (
        client.post(f"/api/setbuilder/sets/{src.id}/duplicate", headers=pending_headers).status_code
        == 403
    )


def test_set_list_surfaces_share_state(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    sets = client.get("/api/setbuilder/sets", headers=auth_headers).json()
    assert sets[0]["share_token"] is None
    token = client.post(f"/api/setbuilder/sets/{src.id}/share", headers=auth_headers).json()[
        "share_token"
    ]
    sets = client.get("/api/setbuilder/sets", headers=auth_headers).json()
    assert sets[0]["share_token"] == token


# ---------------------------------------------------------------------------
# API: duplicate route
# ---------------------------------------------------------------------------


def test_duplicate_endpoint(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    resp = client.post(f"/api/setbuilder/sets/{src.id}/duplicate", headers=auth_headers)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["name"] == "Warehouse Closer (copy)"
    assert body["status"] == "draft"
    assert body["sharing_mode"] == "private"
    assert body["share_token"] is None
    assert body["id"] != src.id


# ---------------------------------------------------------------------------
# API: public view-only projection
# ---------------------------------------------------------------------------


def test_public_shared_view_projection(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    token = client.post(f"/api/setbuilder/sets/{src.id}/share", headers=auth_headers).json()[
        "share_token"
    ]

    # no auth header at all
    resp = client.get(f"/api/public/setbuilder/shared/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Warehouse Closer"
    assert body["vibe_theme"] == "dark-techno"
    assert body["bpm_floor"] == 124
    assert [s["position"] for s in body["slots"]] == [1, 2]
    assert body["slots"][0]["notes"] == "opener"
    assert [c["energy"] for c in body["curve_points"]] == [4, 9]
    assert body["curve_points"][0]["is_slow_window_start"] is True

    # never leak owner identity, internal ids, event linkage or the token
    for forbidden in ("id", "owner_id", "event_id", "tidal_playlist_id", "share_token"):
        assert forbidden not in body, forbidden
    for slot in body["slots"]:
        assert "id" not in slot and "set_id" not in slot
    for point in body["curve_points"]:
        assert "id" not in point and "set_id" not in point


def test_public_shared_view_unknown_or_malformed_token(client):
    assert client.get(f"/api/public/setbuilder/shared/{'A' * 43}").status_code == 404
    assert client.get("/api/public/setbuilder/shared/short").status_code == 404
    assert client.get("/api/public/setbuilder/shared/bad%20token%21aaaaaaaaaaaa").status_code == 404

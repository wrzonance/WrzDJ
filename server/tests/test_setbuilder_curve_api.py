"""API tests for the curve-editor endpoints (#389).

Pins auth gating, owner isolation, template CRUD + validation, server-side
template application (uniform + explicit midpoints), slot target patching,
and vibe-window replace/get round trips.
"""

from app.models.set import SetSlot
from app.services.auth import get_password_hash

VALID_POINTS = [
    {"t": 0.0, "e": 3.0, "label": "Start"},
    {"t": 0.5, "e": 8.0, "label": "Peak"},
    {"t": 1.0, "e": 5.0, "label": "End"},
]


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


def _mk_set(client, auth_headers, name="Set"):
    return client.post("/api/setbuilder/sets", json={"name": name}, headers=auth_headers).json()


def _mk_slots(db, set_id, n):
    for i in range(n):
        db.add(SetSlot(set_id=set_id, position=i))
    db.commit()


# ---------------------------------------------------------------------------
# Template list / create / update / delete
# ---------------------------------------------------------------------------


def test_list_templates_includes_builtins(client, auth_headers):
    resp = client.get("/api/setbuilder/curve-templates", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    names = [t["name"] for t in body["builtin"]]
    assert names == ["Open-Format", "Wedding", "Prom", "Club Peak"]
    assert body["user"] == []


def test_templates_require_auth(client):
    assert client.get("/api/setbuilder/curve-templates").status_code == 401


def test_templates_reject_pending(client, pending_headers):
    resp = client.get("/api/setbuilder/curve-templates", headers=pending_headers)
    assert resp.status_code == 403


def test_create_update_delete_template(client, auth_headers):
    resp = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "My Wedding Mod", "points": VALID_POINTS},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.json()
    tpl = resp.json()
    assert tpl["name"] == "My Wedding Mod"
    assert [p["t"] for p in tpl["points"]] == [0.0, 0.5, 1.0]

    resp = client.put(
        f"/api/setbuilder/curve-templates/{tpl['id']}",
        json={
            "name": "Renamed",
            "points": [{"t": 0.0, "e": 1.0}, {"t": 1.0, "e": 9.0}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert len(resp.json()["points"]) == 2

    listed = client.get("/api/setbuilder/curve-templates", headers=auth_headers).json()
    assert [t["name"] for t in listed["user"]] == ["Renamed"]

    resp = client.delete(f"/api/setbuilder/curve-templates/{tpl['id']}", headers=auth_headers)
    assert resp.status_code == 204
    listed = client.get("/api/setbuilder/curve-templates", headers=auth_headers).json()
    assert listed["user"] == []


def test_template_owner_isolation(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    tpl = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Theirs", "points": VALID_POINTS},
        headers=other_headers,
    ).json()

    resp = client.put(
        f"/api/setbuilder/curve-templates/{tpl['id']}",
        json={"name": "Hijack", "points": VALID_POINTS},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    resp = client.delete(f"/api/setbuilder/curve-templates/{tpl['id']}", headers=auth_headers)
    assert resp.status_code == 404


def test_create_template_validation(client, auth_headers):
    # First point must be t=0, last t=1
    bad_endpoint = [{"t": 0.1, "e": 5.0}, {"t": 1.0, "e": 5.0}]
    resp = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Bad", "points": bad_endpoint},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # Non-monotonic t order
    bad_order = [
        {"t": 0.0, "e": 5.0},
        {"t": 0.8, "e": 5.0},
        {"t": 0.4, "e": 5.0},
        {"t": 1.0, "e": 5.0},
    ]
    resp = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Bad", "points": bad_order},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # Out-of-range energy
    bad_energy = [{"t": 0.0, "e": 11.0}, {"t": 1.0, "e": 5.0}]
    resp = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Bad", "points": bad_energy},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # Too many points
    many = (
        [{"t": 0.0, "e": 5.0}]
        + [{"t": round(0.01 + i * 0.02, 3), "e": 5.0} for i in range(40)]
        + [{"t": 1.0, "e": 5.0}]
    )
    resp = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Bad", "points": many},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Slots list + target patch
# ---------------------------------------------------------------------------


def test_list_slots(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_slots(db, set_obj["id"], 3)
    resp = client.get(f"/api/setbuilder/sets/{set_obj['id']}/slots", headers=auth_headers)
    assert resp.status_code == 200
    slots = resp.json()
    assert [s["position"] for s in slots] == [0, 1, 2]
    assert all(s["target_energy"] is None for s in slots)


def test_list_slots_owner_isolation(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = _mk_set(client, other_headers, "Theirs")
    resp = client.get(f"/api/setbuilder/sets/{theirs['id']}/slots", headers=auth_headers)
    assert resp.status_code == 404


def test_patch_slot_target_and_reset(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_slots(db, set_obj["id"], 1)
    slot_id = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/slots", headers=auth_headers
    ).json()[0]["id"]

    resp = client.patch(
        f"/api/setbuilder/sets/{set_obj['id']}/slots/{slot_id}/target",
        json={"target_energy": 7.25},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["target_energy"] == 7.2  # rounded to 0.1

    resp = client.patch(
        f"/api/setbuilder/sets/{set_obj['id']}/slots/{slot_id}/target",
        json={"target_energy": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["target_energy"] is None


def test_patch_slot_target_validation(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_slots(db, set_obj["id"], 1)
    slot_id = client.get(
        f"/api/setbuilder/sets/{set_obj['id']}/slots", headers=auth_headers
    ).json()[0]["id"]
    resp = client.patch(
        f"/api/setbuilder/sets/{set_obj['id']}/slots/{slot_id}/target",
        json={"target_energy": 12},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_patch_slot_target_unknown_slot_404(client, auth_headers):
    set_obj = _mk_set(client, auth_headers)
    resp = client.patch(
        f"/api/setbuilder/sets/{set_obj['id']}/slots/99999/target",
        json={"target_energy": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Apply template
# ---------------------------------------------------------------------------


def test_apply_builtin_template_uniform(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_slots(db, set_obj["id"], 4)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={"builtin": "Club Peak"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert len(body["targets"]) == 4
    # Persisted
    slots = client.get(f"/api/setbuilder/sets/{set_obj['id']}/slots", headers=auth_headers).json()
    assert [s["target_energy"] for s in slots] == [t["target_energy"] for t in body["targets"]]


def test_apply_template_with_midpoints(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_slots(db, set_obj["id"], 2)
    tpl = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Linear", "points": [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]},
        headers=auth_headers,
    ).json()
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={"template_id": tpl["id"], "slot_midpoints": [0.1, 0.9]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert [t["target_energy"] for t in resp.json()["targets"]] == [1.0, 9.0]


def test_apply_template_midpoint_count_mismatch_400(client, auth_headers, db):
    set_obj = _mk_set(client, auth_headers)
    _mk_slots(db, set_obj["id"], 3)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={"builtin": "Prom", "slot_midpoints": [0.5]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_apply_template_exactly_one_source(client, auth_headers):
    set_obj = _mk_set(client, auth_headers)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={"builtin": "Prom", "template_id": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_apply_unknown_builtin_404(client, auth_headers):
    set_obj = _mk_set(client, auth_headers)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={"builtin": "Nope"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_apply_foreign_user_template_404(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    tpl = client.post(
        "/api/setbuilder/curve-templates",
        json={"name": "Theirs", "points": VALID_POINTS},
        headers=other_headers,
    ).json()
    set_obj = _mk_set(client, auth_headers)
    resp = client.post(
        f"/api/setbuilder/sets/{set_obj['id']}/curve/apply-template",
        json={"template_id": tpl["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Vibe windows
# ---------------------------------------------------------------------------


def test_vibe_windows_put_get(client, auth_headers):
    set_obj = _mk_set(client, auth_headers)
    windows = [
        {"t0_sec": 100, "t1_sec": 300, "label": "First Dance"},
        {"t0_sec": 900, "t1_sec": 1200, "label": "Peak Build"},
    ]
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj['id']}/vibe-windows",
        json={"windows": windows},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["windows"] == windows

    resp = client.get(f"/api/setbuilder/sets/{set_obj['id']}/vibe-windows", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["windows"] == windows


def test_vibe_windows_validation(client, auth_headers):
    set_obj = _mk_set(client, auth_headers)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj['id']}/vibe-windows",
        json={"windows": [{"t0_sec": 300, "t1_sec": 100, "label": "Backwards"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_vibe_windows_owner_isolation(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = _mk_set(client, other_headers, "Theirs")
    resp = client.put(
        f"/api/setbuilder/sets/{theirs['id']}/vibe-windows",
        json={"windows": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404

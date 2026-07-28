"""API tests for the SetBuilder template routes (issue #407).

Pins the boundary invariants from the design spec:
- GET /setbuilder/set-templates never 404s on empty (always 200).
- delete_template is safe to call once and 404s on repeat/unowned.
- SetTemplateOut.slot_count always equals len(decoded slots_json).
- No route/helper in this router touches SetCollaborator or sharing/role logic
  — templates are private to their owner, never shared.
"""

from app.api import setbuilder_templates
from app.models.set import Set, SetCurvePoint, SetSlot
from app.services.auth import get_password_hash
from tests import ast_no_sharing_support


def _seed_set(db, owner_id, **overrides) -> Set:
    fields = {
        "owner_id": owner_id,
        "name": "Warehouse Set",
        "vibe_theme": "dark-techno",
        "target_duration_sec": 3600,
        "avg_transition_overlap_sec": 12,
        "bpm_floor": 124,
        "bpm_ceiling": 132,
        "key_strictness": 0.7,
    }
    fields.update(overrides)
    set_obj = Set(**fields)
    db.add(set_obj)
    db.flush()
    db.add(SetSlot(set_id=set_obj.id, position=0, track_id="tidal:1", target_energy=3.0))
    db.add(SetSlot(set_id=set_obj.id, position=1, track_id="tidal:2", target_energy=7.0))
    db.add(
        SetCurvePoint(set_id=set_obj.id, position_sec=0, energy=4, label="warmup"),
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


# ---------------------------------------------------------------------------
# Structural invariant: templates never touch collaborator/sharing logic
# ---------------------------------------------------------------------------


def test_router_never_touches_collaborator_or_sharing_logic():
    """Static check over the module body (all docstrings excluded, not just
    the module's own): no import of SetCollaborator, no use of the
    share/duplicate service, no share-token field access — templates are
    private to their owner, never shared. Shares its token list and
    docstring-stripping with the broader cross-module check in
    ``test_setbuilder_template_no_sharing_coupling.py``.
    """
    ast_no_sharing_support.assert_no_sharing_references(setbuilder_templates)


# ---------------------------------------------------------------------------
# POST /sets/{set_id}/save-as-template
# ---------------------------------------------------------------------------


def test_save_as_template_endpoint(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    resp = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "My Template"},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["name"] == "My Template"
    assert body["vibe_theme"] == "dark-techno"
    assert body["bpm_floor"] == 124
    assert body["slot_count"] == 2
    assert [c["energy"] for c in body["curve_points"]] == [4]


def test_save_as_template_owner_scoped_404(client, auth_headers, db, test_user):
    other = _make_second_dj(db)
    theirs = _seed_set(db, other.id)
    resp = client.post(
        f"/api/setbuilder/sets/{theirs.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Should Not Work"},
    )
    assert resp.status_code == 404


def test_save_as_template_requires_auth(client, db, test_user, pending_headers):
    src = _seed_set(db, test_user.id)
    resp = client.post(f"/api/setbuilder/sets/{src.id}/save-as-template", json={"name": "x"})
    assert resp.status_code == 401
    resp = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=pending_headers,
        json={"name": "x"},
    )
    assert resp.status_code == 403


def test_save_as_template_rejects_blank_name(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    resp = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": ""},
    )
    assert resp.status_code == 422


def test_save_as_template_rejects_whitespace_only_name(client, auth_headers, db, test_user):
    """``min_length=1`` alone accepts ``"   "`` — the dashboard trims, but a
    direct API client must not be able to store a blank gallery entry."""
    src = _seed_set(db, test_user.id)
    resp = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "   "},
    )
    assert resp.status_code == 422


def test_save_as_template_trims_surrounding_whitespace(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    resp = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "  Warehouse  "},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Warehouse"


# ---------------------------------------------------------------------------
# GET /set-templates (gallery)
# ---------------------------------------------------------------------------


def test_list_set_templates_empty_returns_200_not_404(client, auth_headers):
    resp = client.get("/api/setbuilder/set-templates", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"templates": []}


def test_list_set_templates_scoped_to_owner_newest_first(client, auth_headers, db, test_user):
    other = _make_second_dj(db)
    src = _seed_set(db, test_user.id)
    _seed_set(db, other.id)

    client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "First"},
    )
    client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Second"},
    )

    resp = client.get("/api/setbuilder/set-templates", headers=auth_headers)
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()["templates"]]
    assert names == ["Second", "First"]


def test_slot_count_always_equals_decoded_slots_json_length(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    save_resp = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Counted"},
    )
    assert save_resp.json()["slot_count"] == 2

    list_resp = client.get("/api/setbuilder/set-templates", headers=auth_headers)
    listed = list_resp.json()["templates"][0]
    assert listed["slot_count"] == 2


# ---------------------------------------------------------------------------
# POST /set-templates/{template_id}/instantiate
# ---------------------------------------------------------------------------


def test_instantiate_template_endpoint(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    tpl_id = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Base Template"},
    ).json()["id"]

    resp = client.post(
        f"/api/setbuilder/set-templates/{tpl_id}/instantiate",
        headers=auth_headers,
        json={},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["name"] == "Base Template"
    assert body["status"] == "draft"
    assert body["sharing_mode"] == "private"
    assert body["id"] != src.id


def test_instantiate_template_uses_explicit_name_and_event_id(
    client, auth_headers, db, test_user, test_event
):
    src = _seed_set(db, test_user.id)
    tpl_id = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Base"},
    ).json()["id"]

    resp = client.post(
        f"/api/setbuilder/set-templates/{tpl_id}/instantiate",
        headers=auth_headers,
        json={"name": "Custom", "event_id": test_event.id},
    )
    assert resp.status_code == 201, resp.json()
    assert resp.json()["name"] == "Custom"


def test_instantiate_template_owner_scoped_404(client, auth_headers, db, test_user):
    other = _make_second_dj(db)
    theirs = _seed_set(db, other.id)
    from app.services.setbuilder import set_templates

    tpl = set_templates.extract_template(db, theirs, other.id, "Not Mine")

    resp = client.post(
        f"/api/setbuilder/set-templates/{tpl.id}/instantiate",
        headers=auth_headers,
        json={},
    )
    assert resp.status_code == 404


def test_instantiate_rejects_event_owned_by_another_dj(client, auth_headers, db, test_user):
    """A set's ``event_id`` grants access to event-scoped data through the
    set, so a DJ must never be able to bind their own set to someone else's
    event. Pins that the id is validated against the caller's ownership
    instead of being trusted.
    """
    from datetime import timedelta

    from app.core.time import utcnow
    from app.models.event import Event

    other = _make_second_dj(db)
    their_event = Event(
        code="OTHER1",
        join_code="OTHER2",
        name="Not Mine",
        created_by_user_id=other.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(their_event)
    db.commit()
    db.refresh(their_event)

    src = _seed_set(db, test_user.id)
    tpl_id = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Mine"},
    ).json()["id"]

    resp = client.post(
        f"/api/setbuilder/set-templates/{tpl_id}/instantiate",
        headers=auth_headers,
        json={"event_id": their_event.id},
    )

    assert resp.status_code == 404
    assert not [s for s in db.query(Set).all() if s.event_id == their_event.id]


def test_instantiate_rejects_unknown_event_id(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    tpl_id = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Mine"},
    ).json()["id"]

    resp = client.post(
        f"/api/setbuilder/set-templates/{tpl_id}/instantiate",
        headers=auth_headers,
        json={"event_id": 999999},
    )

    assert resp.status_code == 404


def test_instantiate_template_unknown_id_404(client, auth_headers):
    resp = client.post(
        "/api/setbuilder/set-templates/999999/instantiate",
        headers=auth_headers,
        json={},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /set-templates/{template_id}
# ---------------------------------------------------------------------------


def test_delete_template_endpoint_then_repeat_delete_404s(client, auth_headers, db, test_user):
    src = _seed_set(db, test_user.id)
    tpl_id = client.post(
        f"/api/setbuilder/sets/{src.id}/save-as-template",
        headers=auth_headers,
        json={"name": "Doomed"},
    ).json()["id"]

    first = client.delete(f"/api/setbuilder/set-templates/{tpl_id}", headers=auth_headers)
    assert first.status_code == 204

    second = client.delete(f"/api/setbuilder/set-templates/{tpl_id}", headers=auth_headers)
    assert second.status_code == 404

    listed = client.get("/api/setbuilder/set-templates", headers=auth_headers).json()
    assert listed["templates"] == []


def test_delete_template_owner_scoped_404(client, auth_headers, db, test_user):
    other = _make_second_dj(db)
    theirs = _seed_set(db, other.id)
    from app.services.setbuilder import set_templates

    tpl = set_templates.extract_template(db, theirs, other.id, "Not Mine")

    resp = client.delete(f"/api/setbuilder/set-templates/{tpl.id}", headers=auth_headers)
    assert resp.status_code == 404


def test_template_routes_require_auth(client, db, test_user, pending_headers):
    _seed_set(db, test_user.id)
    assert client.get("/api/setbuilder/set-templates").status_code == 401
    assert client.post("/api/setbuilder/set-templates/1/instantiate", json={}).status_code == 401
    assert client.delete("/api/setbuilder/set-templates/1").status_code == 401
    assert client.get("/api/setbuilder/set-templates", headers=pending_headers).status_code == 403

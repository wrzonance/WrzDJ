# server/tests/test_frictionless_event_api.py
from app.models.user import User


def test_event_out_exposes_frictionless_join(client, db, test_user: User, auth_headers):
    r = client.post("/api/events", json={"name": "E1", "expires_hours": 6}, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["frictionless_join"] is False


def test_patch_event_sets_frictionless_join(client, db, test_user: User, auth_headers):
    code = client.post(
        "/api/events", json={"name": "E2", "expires_hours": 6}, headers=auth_headers
    ).json()["code"]
    r = client.patch(f"/api/events/{code}", json={"frictionless_join": True}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["frictionless_join"] is True

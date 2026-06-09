"""API tests for /api/setbuilder set CRUD (Phase 0).

Pins auth gating (pending users rejected, unauthenticated rejected),
owner isolation (404 on another DJ's set), and the create/list/get/
rename/delete happy paths.
"""

from app.services.auth import get_password_hash


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


def test_create_set(client, auth_headers):
    resp = client.post("/api/setbuilder/sets", json={"name": "Friday Set"}, headers=auth_headers)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["name"] == "Friday Set"
    assert body["status"] == "draft"
    assert body["sharing_mode"] == "private"
    assert body["id"] > 0


def test_create_set_requires_auth(client):
    resp = client.post("/api/setbuilder/sets", json={"name": "X"})
    assert resp.status_code == 401


def test_create_set_rejects_pending_user(client, pending_headers):
    resp = client.post("/api/setbuilder/sets", json={"name": "X"}, headers=pending_headers)
    assert resp.status_code == 403


def test_create_set_validates_name(client, auth_headers):
    resp = client.post("/api/setbuilder/sets", json={"name": ""}, headers=auth_headers)
    assert resp.status_code == 422


def test_list_sets_only_owner(client, auth_headers, db):
    client.post("/api/setbuilder/sets", json={"name": "Mine"}, headers=auth_headers)
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    client.post("/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers)

    resp = client.get("/api/setbuilder/sets", headers=auth_headers)
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == ["Mine"]


def test_get_set(client, auth_headers):
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Detail"}, headers=auth_headers
    ).json()
    resp = client.get(f"/api/setbuilder/sets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["key_strictness"] == 0.2


def test_get_other_dj_set_returns_404(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = client.post(
        "/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers
    ).json()
    resp = client.get(f"/api/setbuilder/sets/{theirs['id']}", headers=auth_headers)
    assert resp.status_code == 404


def test_rename_set(client, auth_headers):
    created = client.post("/api/setbuilder/sets", json={"name": "Old"}, headers=auth_headers).json()
    resp = client.patch(
        f"/api/setbuilder/sets/{created['id']}", json={"name": "New"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_rename_other_dj_set_returns_404(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = client.post(
        "/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers
    ).json()
    resp = client.patch(
        f"/api/setbuilder/sets/{theirs['id']}", json={"name": "Hax"}, headers=auth_headers
    )
    assert resp.status_code == 404


def test_delete_set(client, auth_headers):
    created = client.post(
        "/api/setbuilder/sets", json={"name": "Doomed"}, headers=auth_headers
    ).json()
    resp = client.delete(f"/api/setbuilder/sets/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert (
        client.get(f"/api/setbuilder/sets/{created['id']}", headers=auth_headers).status_code == 404
    )


def test_delete_other_dj_set_returns_404(client, auth_headers, db):
    _make_second_dj(db)
    other_headers = _login(client, "otherdj", "xxxxxxxxxxxx")
    theirs = client.post(
        "/api/setbuilder/sets", json={"name": "Theirs"}, headers=other_headers
    ).json()
    resp = client.delete(f"/api/setbuilder/sets/{theirs['id']}", headers=auth_headers)
    assert resp.status_code == 404

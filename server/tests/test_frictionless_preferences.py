# server/tests/test_frictionless_preferences.py
def test_me_exposes_frictionless_default(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["frictionless_join_default"] is False


def test_patch_preferences_updates_default(client, auth_headers):
    r = client.patch(
        "/api/auth/me/preferences",
        json={"frictionless_join_default": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["frictionless_join_default"] is True
    # persisted
    assert (
        client.get("/api/auth/me", headers=auth_headers).json()["frictionless_join_default"] is True
    )

"""Invite-link collaboration API coverage for issue #408."""

from app.models.set import Set, SetCollaborator
from app.services.auth import get_password_hash


def _login(client, username, password):
    response = client.post("/api/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _make_dj(db, username):
    from app.models.user import User

    user = User(username=username, password_hash=get_password_hash("x" * 12), role="dj")
    db.add(user)
    db.commit()
    return user


def test_owner_can_issue_invite_and_recipient_accepts_once(client, db, test_user, auth_headers):
    set_obj = Set(owner_id=test_user.id, name="Collab set")
    db.add(set_obj)
    db.commit()
    recipient = _make_dj(db, "collab-dj")
    recipient_headers = _login(client, "collab-dj", "x" * 12)

    created = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "editor"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    invite = created.json()
    assert invite["role"] == "editor"
    assert len(invite["token"]) >= 40
    assert invite["expires_at"]

    accepted = client.post(
        f"/api/setbuilder/collaborator-invites/{invite['token']}/accept",
        headers=recipient_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"set_id": set_obj.id, "role": "editor"}
    collaboration = db.query(SetCollaborator).one()
    assert collaboration.user_id == recipient.id
    assert collaboration.invited_by == test_user.id

    replay = client.post(
        f"/api/setbuilder/collaborator-invites/{invite['token']}/accept",
        headers=recipient_headers,
    )
    assert replay.status_code == 410
    assert set_obj.sharing_mode == "invite_only"

    owner = client.get(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites", headers=auth_headers
    )
    assert owner.status_code == 200
    assert owner.json()[0]["accepted"] is True
    assert "token" not in owner.json()[0]


def test_invite_creation_is_owner_only_and_role_is_validated(client, db, test_user, auth_headers):
    set_obj = Set(owner_id=test_user.id, name="Private")
    db.add(set_obj)
    db.commit()
    _make_dj(db, "other-owner")
    other_headers = _login(client, "other-owner", "x" * 12)

    denied = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "viewer"},
        headers=other_headers,
    )
    assert denied.status_code == 404

    invalid = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "admin"},
        headers=auth_headers,
    )
    assert invalid.status_code == 422


def test_expired_invite_cannot_be_accepted(client, db, test_user, auth_headers):
    from datetime import timedelta

    from app.core.time import utcnow
    from app.models.set_collaborator_invite import SetCollaboratorInvite

    set_obj = Set(owner_id=test_user.id, name="Expired")
    db.add(set_obj)
    db.commit()
    recipient = _make_dj(db, "expired-recipient")
    headers = _login(client, "expired-recipient", "x" * 12)
    created = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "viewer"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    token = created.json()["token"]
    invite = db.query(SetCollaboratorInvite).one()
    invite.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    accepted = client.post(f"/api/setbuilder/collaborator-invites/{token}/accept", headers=headers)
    assert accepted.status_code == 410
    assert db.query(SetCollaborator).filter_by(user_id=recipient.id).count() == 0


def test_owner_can_revoke_invite_and_token_is_stored_as_hash(client, db, test_user, auth_headers):
    from app.models.set_collaborator_invite import SetCollaboratorInvite

    set_obj = Set(owner_id=test_user.id, name="Revoked")
    db.add(set_obj)
    db.commit()
    created = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "viewer"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    token = created.json()["token"]
    invite = db.query(SetCollaboratorInvite).one()
    assert invite.token_hash != token

    revoked = client.delete(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites/{invite.id}",
        headers=auth_headers,
    )
    assert revoked.status_code == 204
    assert invite.revoked_at is not None

    listed = client.get(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites", headers=auth_headers
    )
    assert listed.json()[0]["revoked"] is True

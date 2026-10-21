"""Invite-link collaboration API coverage for issue #408."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.set import Set, SetCollaborator
from app.models.set_collaborator_invite import SetCollaboratorInvite
from app.services.auth import get_password_hash
from app.services.setbuilder import collaboration


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
    existing_share_token = "s" * 43
    set_obj = Set(owner_id=test_user.id, name="Collab set", share_token=existing_share_token)
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

    second_invite = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "viewer"},
        headers=auth_headers,
    )
    assert second_invite.status_code == 201
    duplicate = client.post(
        f"/api/setbuilder/collaborator-invites/{second_invite.json()['token']}/accept",
        headers=recipient_headers,
    )
    assert duplicate.status_code == 409
    assert db.query(SetCollaborator).filter_by(user_id=recipient.id).count() == 1

    replay = client.post(
        f"/api/setbuilder/collaborator-invites/{invite['token']}/accept",
        headers=recipient_headers,
    )
    assert replay.status_code == 410
    assert set_obj.sharing_mode == "private"
    assert set_obj.share_token == existing_share_token

    owner = client.get(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites", headers=auth_headers
    )
    assert owner.status_code == 200
    assert owner.json()[0]["accepted"] is False
    assert owner.json()[1]["accepted"] is True
    assert "token" not in owner.json()[0]

    revoke_accepted = client.delete(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites/{owner.json()[1]['id']}",
        headers=auth_headers,
    )
    assert revoke_accepted.status_code == 409
    after_revoke = client.get(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites", headers=auth_headers
    )
    assert after_revoke.json()[1]["revoked"] is False


def test_owner_cannot_accept_own_invite(client, db, test_user, auth_headers):
    from app.models.set_collaborator_invite import SetCollaboratorInvite

    set_obj = Set(owner_id=test_user.id, name="Owner invite")
    db.add(set_obj)
    db.commit()
    created = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "viewer"},
        headers=auth_headers,
    )
    assert created.status_code == 201

    accepted = client.post(
        f"/api/setbuilder/collaborator-invites/{created.json()['token']}/accept",
        headers=auth_headers,
    )
    assert accepted.status_code == 409
    invite = db.query(SetCollaboratorInvite).one()
    assert invite.accepted_at is None
    assert db.query(SetCollaborator).count() == 0


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


def test_malformed_invite_token_is_rejected_at_the_acceptance_boundary(
    client, db, test_user, auth_headers
):
    from app.models.set_collaborator_invite import SetCollaboratorInvite

    set_obj = Set(owner_id=test_user.id, name="Malformed invite")
    db.add(set_obj)
    db.commit()
    created = client.post(
        f"/api/setbuilder/sets/{set_obj.id}/collaborator-invites",
        json={"role": "viewer"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    recipient = _make_dj(db, "malformed-recipient")
    recipient_headers = _login(client, "malformed-recipient", "x" * 12)

    rejected = client.post(
        "/api/setbuilder/collaborator-invites/short/accept",
        headers=recipient_headers,
    )

    assert rejected.status_code == 410
    assert rejected.json() == {"detail": "Invite is no longer available"}
    invite = db.query(SetCollaboratorInvite).one()
    assert invite.accepted_at is None
    assert db.query(SetCollaborator).filter_by(user_id=recipient.id).count() == 0


def test_concurrent_invite_acceptance_maps_unique_conflict_to_already_collaborator(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'invite-race.db'}")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as setup:
            owner = _make_isolated_user(setup, "race-owner")
            recipient = _make_isolated_user(setup, "race-recipient")
            set_obj = Set(owner_id=owner.id, name="Concurrent invite")
            setup.add(set_obj)
            setup.commit()
            invite, token = collaboration.create_invite(setup, set_obj.id, owner, "editor")
            invite_id = invite.id
            set_id = set_obj.id
            recipient_id = recipient.id
            owner_id = owner.id

        with sessions() as accepting:
            from app.models.user import User

            recipient = accepting.get(User, recipient_id)
            real_commit = accepting.commit

            def commit_with_competing_acceptance():
                with sessions() as competitor:
                    competitor.add(
                        SetCollaborator(
                            set_id=set_id,
                            user_id=recipient_id,
                            role="editor",
                            invited_by=owner_id,
                        )
                    )
                    competitor.commit()
                real_commit()

            monkeypatch.setattr(accepting, "commit", commit_with_competing_acceptance)
            with pytest.raises(collaboration.AlreadyCollaborator):
                collaboration.accept_invite(accepting, token, recipient)
            accepting.expire_all()
            assert accepting.query(SetCollaborator).filter_by(user_id=recipient_id).count() == 1
            invite = accepting.get(SetCollaboratorInvite, invite_id)
            assert invite.accepted_at is None
            assert invite.revoked_at is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_isolated_user(db: Session, username: str):
    from app.models.user import User

    user = User(username=username, password_hash="test-hash", role="dj")
    db.add(user)
    db.flush()
    return user


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

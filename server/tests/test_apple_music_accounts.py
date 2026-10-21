"""Apple Music connection lifecycle and stored-credential boundary tests."""

import json

import pytest
from sqlalchemy import select, text, update

from app.models.provider_connection import UserProviderConnection
from app.services.apple_music import accounts as apple_music_accounts
from app.services.apple_music import tokens as apple_music_tokens

VALID_TOKEN = "music-user-token-1234567890"
NEW_TOKEN = "music-user-token-0987654321"


def _connected_connection(db, user, *, token: str = VALID_TOKEN, storefront: str = "us"):
    connection = UserProviderConnection(
        user_id=user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload=json.dumps({"version": 1, "music_user_token": token}),
        metadata_json=json.dumps({"storefront": storefront}),
    )
    db.add(connection)
    db.commit()
    return connection


def test_link_validates_and_stores_the_encrypted_user_token(db, test_user, monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))
    monkeypatch.setattr(apple_music_accounts, "fetch_user_storefront", lambda *_: "us")

    connection = apple_music_accounts.link_account(db, test_user, VALID_TOKEN)

    assert connection.connection_state == "connected"
    assert json.loads(connection.credential_payload) == {
        "version": 1,
        "music_user_token": VALID_TOKEN,
    }
    assert json.loads(connection.metadata_json) == {"storefront": "us"}
    stored = db.execute(
        text("SELECT credential_payload FROM user_provider_connections WHERE id = :id"),
        {"id": connection.id},
    ).scalar_one()
    assert VALID_TOKEN not in stored


def test_disconnect_during_validation_invalidates_the_in_flight_link(db, test_user, monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))

    def disconnect_while_apple_is_validating(*_args):
        apple_music_accounts.disconnect_account(db, test_user)
        return "us"

    monkeypatch.setattr(
        apple_music_accounts, "fetch_user_storefront", disconnect_while_apple_is_validating
    )

    with pytest.raises(apple_music_tokens.AppleMusicLinkSuperseded):
        apple_music_accounts.link_account(db, test_user, VALID_TOKEN)

    connection = db.query(UserProviderConnection).filter_by(user_id=test_user.id).one()
    assert connection.connection_state == "disconnected"
    assert connection.credential_payload is None
    assert connection.metadata_json is None
    assert connection.authorization_generation == 2


def test_disconnect_with_unexpired_identity_map_invalidates_the_in_flight_link(
    db, test_user, monkeypatch
):
    db.expire_on_commit = False
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="disconnected",
        credential_type="music_user_token",
    )
    db.add(connection)
    db.commit()
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))

    def disconnect_while_apple_is_validating(*_args):
        connection = db.query(UserProviderConnection).filter_by(user_id=test_user.id).one()
        db.connection().execute(
            update(UserProviderConnection)
            .where(UserProviderConnection.id == connection.id)
            .values(
                authorization_generation=connection.authorization_generation + 1,
                connection_state="disconnected",
                credential_payload=None,
                metadata_json=None,
            )
        )
        db.commit()
        assert connection.authorization_generation == 1
        assert (
            db.connection()
            .execute(
                select(UserProviderConnection.__table__.c.authorization_generation).where(
                    UserProviderConnection.__table__.c.id == connection.id
                )
            )
            .scalar_one()
            == 2
        )
        return "us"

    monkeypatch.setattr(
        apple_music_accounts, "fetch_user_storefront", disconnect_while_apple_is_validating
    )

    with pytest.raises(apple_music_tokens.AppleMusicLinkSuperseded):
        apple_music_accounts.link_account(db, test_user, VALID_TOKEN)

    connection = db.query(UserProviderConnection).filter_by(user_id=test_user.id).one()
    assert connection.connection_state == "disconnected"
    assert connection.credential_payload is None
    assert connection.authorization_generation == 2


def test_invalid_user_token_leaves_a_disconnected_tombstone(db, test_user, monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))

    def reject(*_args):
        raise apple_music_tokens.AppleMusicUserAuthorizationError

    monkeypatch.setattr(apple_music_accounts, "fetch_user_storefront", reject)

    with pytest.raises(apple_music_tokens.AppleMusicUserAuthorizationError):
        apple_music_accounts.link_account(db, test_user, VALID_TOKEN)

    connection = db.query(UserProviderConnection).filter_by(user_id=test_user.id).one()
    assert connection.connection_state == "disconnected"
    assert connection.credential_payload is None


def test_account_status_rechecks_the_saved_user_token(db, test_user, monkeypatch):
    _connected_connection(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))
    monkeypatch.setattr(apple_music_accounts, "fetch_user_storefront", lambda *_: "gb")

    assert apple_music_accounts.account_status(db, test_user) == {
        "configured": True,
        "linked": True,
        "requires_reauthorization": False,
        "storefront": "gb",
    }


def test_account_status_commits_reauthorization_from_storage(db, test_user, monkeypatch):
    connection = _connected_connection(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: False)

    def mark_reauthorization_without_committing(session, user):
        stored = session.query(UserProviderConnection).filter_by(user_id=user.id).one()
        stored.connection_state = "reauthorize"
        raise apple_music_tokens.AppleMusicNotConnected

    monkeypatch.setattr(
        apple_music_accounts.apple_music_storage,
        "read_stored_connection",
        mark_reauthorization_without_committing,
    )

    status = apple_music_accounts.account_status(db, test_user)

    assert status == {
        "configured": False,
        "linked": False,
        "requires_reauthorization": True,
        "storefront": None,
    }
    assert db.query(UserProviderConnection).filter_by(id=connection.id).one().connection_state == (
        "reauthorize"
    )


def test_stale_apple_403_does_not_revoke_a_newer_reconnection(db, test_user, monkeypatch):
    connection = _connected_connection(db, test_user)
    initial_generation = connection.authorization_generation
    connection_id = connection.id
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))

    def reconnect_then_reject(*_args):
        db.connection().execute(
            update(UserProviderConnection)
            .where(UserProviderConnection.id == connection_id)
            .values(
                authorization_generation=initial_generation + 1,
                connection_state="connected",
                credential_payload=json.dumps({"version": 1, "music_user_token": NEW_TOKEN}),
                metadata_json='{"storefront":"ca"}',
            )
        )
        db.commit()
        row = (
            db.connection()
            .execute(
                select(
                    UserProviderConnection.__table__.c.authorization_generation,
                    UserProviderConnection.__table__.c.metadata_json,
                ).where(UserProviderConnection.__table__.c.id == connection_id)
            )
            .one()
        )
        assert row == (initial_generation + 1, '{"storefront":"ca"}')
        raise apple_music_tokens.AppleMusicUserAuthorizationError

    monkeypatch.setattr(apple_music_accounts, "fetch_user_storefront", reconnect_then_reject)

    status = apple_music_accounts.account_status(db, test_user)

    assert status == {
        "configured": True,
        "linked": True,
        "requires_reauthorization": False,
        "storefront": "ca",
    }
    db.refresh(connection)
    assert connection.connection_state == "connected"
    assert json.loads(connection.credential_payload)["music_user_token"] == NEW_TOKEN
    assert json.loads(connection.metadata_json) == {"storefront": "ca"}


def test_stale_apple_success_does_not_overwrite_a_newer_storefront(db, test_user, monkeypatch):
    connection = _connected_connection(db, test_user)
    initial_generation = connection.authorization_generation
    connection_id = connection.id
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))

    def reconnect_then_return_old_storefront(*_args):
        db.connection().execute(
            update(UserProviderConnection)
            .where(UserProviderConnection.id == connection_id)
            .values(
                authorization_generation=initial_generation + 1,
                connection_state="connected",
                credential_payload=json.dumps({"version": 1, "music_user_token": NEW_TOKEN}),
                metadata_json='{"storefront":"ca"}',
            )
        )
        db.commit()
        row = (
            db.connection()
            .execute(
                select(
                    UserProviderConnection.__table__.c.authorization_generation,
                    UserProviderConnection.__table__.c.metadata_json,
                ).where(UserProviderConnection.__table__.c.id == connection_id)
            )
            .one()
        )
        assert row == (initial_generation + 1, '{"storefront":"ca"}')
        return "us"

    monkeypatch.setattr(
        apple_music_accounts,
        "fetch_user_storefront",
        reconnect_then_return_old_storefront,
    )

    status = apple_music_accounts.account_status(db, test_user)

    assert status == {
        "configured": True,
        "linked": True,
        "requires_reauthorization": False,
        "storefront": "ca",
    }
    db.refresh(connection)
    assert json.loads(connection.credential_payload)["music_user_token"] == NEW_TOKEN
    assert json.loads(connection.metadata_json) == {"storefront": "ca"}


def test_disconnect_increments_authorization_generation(db, test_user):
    apple_music_accounts.disconnect_account(db, test_user)

    connection = db.query(UserProviderConnection).filter_by(user_id=test_user.id).one()
    assert connection.connection_state == "disconnected"
    assert connection.authorization_generation == 1


def test_apple_status_codes_separate_deployment_and_user_authorization(monkeypatch):
    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    class Client:
        def __init__(self, status_code, **_kwargs):
            self.status_code = status_code

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return Response(self.status_code)

    monkeypatch.setattr(apple_music_tokens.httpx, "Client", lambda **kw: Client(401, **kw))
    with pytest.raises(apple_music_tokens.AppleMusicNotConfigured):
        apple_music_tokens.apple_get("/me/storefront", "bad-dev")

    with pytest.raises(apple_music_tokens.AppleMusicUserAuthorizationError):
        apple_music_tokens.apple_get("/me/storefront", "dev", music_user_token=VALID_TOKEN)

    monkeypatch.setattr(apple_music_tokens.httpx, "Client", lambda **kw: Client(403, **kw))
    with pytest.raises(apple_music_tokens.AppleMusicUserAuthorizationError):
        apple_music_tokens.apple_get("/me/storefront", "dev", music_user_token=VALID_TOKEN)


def test_apple_get_rejects_non_object_success_json(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(apple_music_tokens.httpx, "Client", Client)

    with pytest.raises(apple_music_tokens.AppleMusicError):
        apple_music_tokens.apple_get("/me/storefront", "developer-token")


def test_malformed_storefront_response_does_not_revoke_the_saved_user_token(
    db, test_user, monkeypatch
):
    connection = _connected_connection(db, test_user)
    monkeypatch.setattr(apple_music_tokens, "is_configured", lambda: True)
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))
    monkeypatch.setattr(
        apple_music_tokens,
        "apple_get",
        lambda *_args, **_kwargs: {"data": [None]},
    )

    with pytest.raises(apple_music_tokens.AppleMusicError):
        apple_music_accounts.account_status(db, test_user)

    db.refresh(connection)
    assert connection.connection_state == "connected"
    assert json.loads(connection.credential_payload)["music_user_token"] == VALID_TOKEN
    assert json.loads(connection.metadata_json) == {"storefront": "us"}


@pytest.mark.parametrize("storefront", ["GB", "g", "usa", "us\n", "éu"])
def test_apple_storefront_response_requires_two_lowercase_ascii_letters(monkeypatch, storefront):
    monkeypatch.setattr(
        apple_music_tokens,
        "apple_get",
        lambda *_args, **_kwargs: {"data": [{"id": storefront}]},
    )

    with pytest.raises(
        apple_music_tokens.AppleMusicError,
        match="Apple Music returned an invalid storefront",
    ):
        apple_music_accounts.fetch_user_storefront("music-user-token", "developer-token")


def test_api_status_returns_reconnect_state_for_malformed_stored_data(
    client, auth_headers, db, test_user
):
    db.add(
        UserProviderConnection(
            user_id=test_user.id,
            provider_id="apple_music",
            connection_state="connected",
            credential_type="music_user_token",
            credential_payload="{not-json",
            metadata_json='{"storefront":"us"}',
        )
    )
    db.commit()

    response = client.get("/api/apple-music/status", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "linked": False,
        "requires_reauthorization": True,
        "storefront": None,
    }
    assert "not-json" not in response.text


def test_api_link_reports_when_disconnect_supersedes_the_attempt(client, auth_headers, monkeypatch):
    def superseded(*_args):
        raise apple_music_tokens.AppleMusicLinkSuperseded

    monkeypatch.setattr(apple_music_accounts, "link_account", superseded)

    response = client.post(
        "/api/apple-music/link",
        headers=auth_headers,
        json={"music_user_token": VALID_TOKEN},
    )

    assert response.status_code == 409
    assert "canceled" in response.json()["detail"]
    assert VALID_TOKEN not in response.text


def test_api_link_rejects_non_latin1_token_characters(client, auth_headers, monkeypatch):
    monkeypatch.setattr(apple_music_tokens, "create_developer_token", lambda: ("dev", 100))
    monkeypatch.setattr(apple_music_accounts, "fetch_user_storefront", lambda *_args: "us")
    response = client.post(
        "/api/apple-music/link",
        headers=auth_headers,
        json={"music_user_token": f"{VALID_TOKEN}\u0100"},
    )

    assert response.status_code == 422

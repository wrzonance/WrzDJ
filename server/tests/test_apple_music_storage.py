"""Stored Apple Music credentials fail closed when encrypted data is incompatible."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.provider_connection import UserProviderConnection
from app.models.user import User
from app.services.apple_music.storage import read_stored_connection
from app.services.apple_music.tokens import AppleMusicNotConnected

VALID_TOKEN = "music-user-token-1234567890"


@pytest.mark.parametrize(
    ("credential_payload", "metadata_json"),
    [
        ("{not-json", '{"storefront":"us"}'),
        ('{"version":1}', '{"storefront":"us"}'),
        ('{"version":true,"music_user_token":"' + VALID_TOKEN + '"}', '{"storefront":"us"}'),
        ('{"version":2,"music_user_token":"' + VALID_TOKEN + '"}', '{"storefront":"us"}'),
        ('{"version":1,"music_user_token":12}', '{"storefront":"us"}'),
        ('{"version":1,"music_user_token":"' + VALID_TOKEN + '"}', "{not-json"),
        ('{"version":1,"music_user_token":"' + VALID_TOKEN + '"}', '{"storefront":12}'),
    ],
)
def test_malformed_stored_credentials_mark_connection_for_reauthorization(
    db, test_user, credential_payload, metadata_json
):
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload=credential_payload,
        metadata_json=metadata_json,
    )
    db.add(connection)
    db.commit()

    with pytest.raises(AppleMusicNotConnected):
        read_stored_connection(db, test_user)

    assert connection.connection_state == "reauthorize"
    db.commit()
    db.refresh(connection)
    assert connection.connection_state == "reauthorize"


def test_expired_stored_connection_marks_connection_for_reauthorization(db, test_user):
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload=json.dumps({"version": 1, "music_user_token": VALID_TOKEN}),
        expires_at=utcnow() - timedelta(seconds=1),
        metadata_json='{"storefront":"us"}',
    )
    db.add(connection)
    db.commit()

    with pytest.raises(AppleMusicNotConnected):
        read_stored_connection(db, test_user)

    assert connection.connection_state == "reauthorize"


def test_read_stored_connection_does_not_commit_callers_transaction(db, test_user):
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload="{not-json",
        metadata_json='{"storefront":"us"}',
    )
    db.add(connection)
    db.commit()
    commits = []
    event.listen(db, "after_commit", lambda _session: commits.append(True))

    with pytest.raises(AppleMusicNotConnected):
        read_stored_connection(db, test_user)

    assert commits == []


def test_valid_stored_connection_returns_token_and_storefront(db, test_user):
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload=json.dumps({"version": 1, "music_user_token": VALID_TOKEN}),
        metadata_json='{"storefront":"gb"}',
    )
    db.add(connection)
    db.commit()

    assert read_stored_connection(db, test_user) == (VALID_TOKEN, "gb")


@pytest.mark.parametrize("storefront", ["GB", "g", "usa", "us\n", "éu"])
def test_malformed_storefront_values_require_reauthorization(db, test_user, storefront):
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload=json.dumps({"version": 1, "music_user_token": VALID_TOKEN}),
        metadata_json=json.dumps({"storefront": storefront}),
    )
    db.add(connection)
    db.commit()

    with pytest.raises(AppleMusicNotConnected):
        read_stored_connection(db, test_user)

    assert connection.connection_state == "reauthorize"


def test_user_can_have_only_one_connection_for_each_provider(db, test_user):
    db.add(
        UserProviderConnection(
            user_id=test_user.id,
            provider_id="apple_music",
            connection_state="disconnected",
            credential_type="music_user_token",
        )
    )
    db.commit()
    db.add(
        UserProviderConnection(
            user_id=test_user.id,
            provider_id="apple_music",
            connection_state="connected",
            credential_type="music_user_token",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    assert (
        db.query(UserProviderConnection)
        .filter_by(user_id=test_user.id, provider_id="apple_music")
        .count()
        == 1
    )


def test_stored_connection_lookup_is_scoped_to_the_dj(db, test_user):
    other_user = User(username="other-dj", password_hash="test-hash", role="dj")
    db.add(other_user)
    db.flush()
    db.add(
        UserProviderConnection(
            user_id=test_user.id,
            provider_id="apple_music",
            connection_state="connected",
            credential_type="music_user_token",
            credential_payload=json.dumps({"version": 1, "music_user_token": VALID_TOKEN}),
            metadata_json='{"storefront":"us"}',
        )
    )
    db.commit()

    with pytest.raises(AppleMusicNotConnected):
        read_stored_connection(db, other_user)


def test_credential_payload_is_ciphertext_in_the_database(db, test_user):
    connection = UserProviderConnection(
        user_id=test_user.id,
        provider_id="apple_music",
        connection_state="connected",
        credential_type="music_user_token",
        credential_payload=json.dumps({"version": 1, "music_user_token": VALID_TOKEN}),
        metadata_json='{"storefront":"us"}',
    )
    db.add(connection)
    db.commit()

    raw_payload = db.execute(
        text("SELECT credential_payload FROM user_provider_connections WHERE id = :id"),
        {"id": connection.id},
    ).scalar_one()

    assert raw_payload.startswith("gAAAA")
    assert VALID_TOKEN not in raw_payload
    assert read_stored_connection(db, test_user) == (VALID_TOKEN, "us")


def test_deleting_a_dj_cascades_to_provider_connections():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    User.__table__.create(engine)
    UserProviderConnection.__table__.create(engine)
    try:
        with Session(engine) as session:
            user = User(username="cascade-dj", password_hash="test-hash", role="dj")
            session.add(user)
            session.flush()
            session.add(
                UserProviderConnection(
                    user_id=user.id,
                    provider_id="apple_music",
                    connection_state="disconnected",
                    credential_type="music_user_token",
                )
            )
            session.commit()

            session.execute(delete(User).where(User.id == user.id))
            session.commit()

            assert session.scalar(select(func.count()).select_from(UserProviderConnection)) == 0
    finally:
        UserProviderConnection.__table__.drop(engine)
        User.__table__.drop(engine)
        engine.dispose()

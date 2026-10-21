"""Database-level invariants for guest profile constraints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.time import utcnow
from app.models.base import Base
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.user import User
from app.services.auth import create_access_token


def _guest(db, suffix: str) -> Guest:
    guest = Guest(
        token=f"profile-constraint-{suffix}".ljust(64, "0"),
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(guest)
    db.flush()
    return guest


def test_nickname_index_rejects_case_insensitive_duplicate_at_database_boundary(db, test_event):
    first_guest = _guest(db, "first")
    second_guest = _guest(db, "second")
    db.add_all(
        [
            GuestProfile(event_id=test_event.id, guest_id=first_guest.id, nickname="DanceFloor"),
            GuestProfile(event_id=test_event.id, guest_id=second_guest.id, nickname="dancefloor"),
        ]
    )

    with pytest.raises(IntegrityError):
        db.commit()


def test_delete_event_endpoint_cascades_guest_profile(test_app):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sqlalchemy_event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        user = User(username="cascade-user", password_hash="unused")
        db.add(user)
        db.flush()
        event = Event(
            code="CASCADE1",
            join_code="CASC123",
            name="Cascade test",
            created_by_user_id=user.id,
            expires_at=utcnow(),
        )
        guest = Guest(token="cascade-guest".ljust(64, "0"))
        db.add_all([event, guest])
        db.flush()
        profile = GuestProfile(event_id=event.id, guest_id=guest.id, nickname="CascadeGuest")
        db.add(profile)
        db.commit()
        event_code = event.code
        profile_id = profile.id
        token = create_access_token(data={"sub": user.username, "tv": user.token_version})

    def override_get_db():
        with session_factory() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(test_app) as client:
            response = client.delete(
                f"/api/events/{event_code}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 204
        with session_factory() as db:
            assert db.query(GuestProfile).filter_by(id=profile_id).first() is None
    finally:
        test_app.dependency_overrides.pop(get_db, None)
        engine.dispose()

"""Shared Beatport test fixtures and response data."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash


@pytest.fixture(name="beatport_user")
def _fixture_beatport_user(db: Session) -> User:
    """User with Beatport tokens."""
    user = User(
        username="beatport_user",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="bp_access_token_123",
        beatport_refresh_token="bp_refresh_token_456",
        beatport_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="beatport_user_expired")
def _fixture_beatport_user_expired(db: Session) -> User:
    """User with expired Beatport tokens."""
    user = User(
        username="beatport_expired",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="bp_expired_token",
        beatport_refresh_token="bp_refresh_token_789",
        beatport_token_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="beatport_user_no_token")
def _fixture_beatport_user_no_token(db: Session) -> User:
    """User without Beatport tokens."""
    user = User(
        username="beatport_notoken",
        password_hash=get_password_hash("testpassword123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


MOCK_SEARCH_RESPONSE = {
    "tracks": [
        {
            "id": 12345,
            "name": "Strobe",
            "slug": "strobe",
            "mix_name": "Original Mix",
            "artists": [{"name": "deadmau5"}],
            "label": {"name": "mau5trap"},
            "genre": {"name": "Progressive House"},
            "bpm": 128,
            "key": {"name": "A min"},
            "length": "10:33",
            "image": {"uri": "https://geo-media.beatport.com/image/12345.jpg"},
            "new_release_date": "2009-09-14",
        }
    ]
}


@pytest.fixture(name="beatport_event")
def _fixture_beatport_event(db: Session, beatport_user: User) -> Event:
    """Event with Beatport sync enabled."""
    from datetime import UTC, datetime, timedelta

    event = Event(
        code="BPTEST",
        join_code="K6L6GZ",
        name="BP Playlist Test",
        created_by_user_id=beatport_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        beatport_sync_enabled=True,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event

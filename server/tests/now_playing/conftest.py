"""Shared now-playing fixtures, retaining function scope."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.auth import get_password_hash
from tests.now_playing.helpers import utcnow


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        password_hash=get_password_hash("testpassword123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_event(db: Session, test_user: User) -> Event:
    """Create a test event."""
    event = Event(
        code="TEST01",
        join_code="UG4BHD",
        name="Test Event",
        created_by_user_id=test_user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def accepted_request(db: Session, test_event: Event) -> Request:
    """Create an accepted request."""
    request = Request(
        event_id=test_event.id,
        song_title="Blue Monday",
        artist="New Order",
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="test_dedupe_key_12345678",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request

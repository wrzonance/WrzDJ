"""Shared Tidal test fixtures and track factory."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User


def _make_mock_track(
    track_id: int,
    name: str,
    artist_name: str,
    album_name: str | None = None,
    *,
    bpm: float | None = None,
    key: str | None = None,
    duration: int = 200,
    cover_url: str | None = None,
    popularity: int = 0,
    isrc: str | None = None,
    version: str | None = None,
    explicit: bool = False,
    artists: list | None = None,
) -> MagicMock:
    """Create a properly configured mock tidalapi.Track.

    Sets all fields explicitly so MagicMock doesn't auto-create
    attributes that trip isinstance checks or Pydantic validation.
    """
    track = MagicMock()
    track.id = track_id
    track.name = name
    track.duration = duration
    track.bpm = bpm
    track.key = key
    track.popularity = popularity
    track.isrc = isrc
    track.version = version
    track.explicit = explicit
    track.artists = artists or []
    track.artist = MagicMock()
    track.artist.name = artist_name
    if album_name:
        track.album = MagicMock()
        track.album.name = album_name
        track.album.image.return_value = cover_url
    else:
        track.album = None
    return track


@pytest.fixture(name="tidal_user")
def _fixture_tidal_user(db: Session) -> User:
    """Create a user with linked Tidal account."""
    from app.services.auth import get_password_hash

    user = User(
        username="tidaluser",
        password_hash=get_password_hash("testpassword123"),
        tidal_access_token="test_access_token",
        tidal_refresh_token="test_refresh_token",
        tidal_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        tidal_user_id="12345",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="tidal_event")
def _fixture_tidal_event(db: Session, tidal_user: User) -> Event:
    """Create an event with Tidal sync enabled."""
    event = Event(
        code="TIDAL1",
        join_code="4MF78Z",
        name="Tidal Test Event",
        created_by_user_id=tidal_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        tidal_sync_enabled=True,
        tidal_playlist_id="playlist123",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture(name="tidal_request")
def _fixture_tidal_request(db: Session, tidal_event: Event) -> Request:
    """Create a test request for Tidal sync."""
    request = Request(
        event_id=tidal_event.id,
        song_title="Test Song",
        artist="Test Artist",
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="tidal_test_dedupe_key",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request

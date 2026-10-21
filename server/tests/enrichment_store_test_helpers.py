"""Shared enrichment-store test fixtures and builders."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User


@pytest.fixture(name="bp_user")
def _fixture_bp_user(db: Session) -> User:
    """A DJ user with a Beatport token (so the Beatport block is entered)."""
    from app.services.auth import get_password_hash

    user = User(
        username="enrich_store_user",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="fake_bp_token",
        tidal_access_token="fake_tidal_token",
        tidal_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_event(db: Session, owner: User, code: str, join_code: str) -> Event:
    event = Event(
        code=code,
        join_code=join_code,
        name=f"Event {code}",
        created_by_user_id=owner.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _make_request(
    db: Session,
    event: Event,
    title: str,
    artist: str,
    dedupe: str,
    *,
    genre: str | None = None,
    bpm: float | None = None,
    musical_key: str | None = None,
    isrc: str | None = None,
) -> Request:
    request = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key=dedupe,
        genre=genre,
        bpm=bpm,
        musical_key=musical_key,
        isrc=isrc,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def _beatport_hit(title: str, artist: str):
    from app.schemas.beatport import BeatportSearchResult

    return BeatportSearchResult(
        track_id="123",
        title=title,
        artist=artist,
        genre="Progressive House",
        bpm=128,
        key="F Minor",
    )


def _settings_stub(*, enabled: bool):
    """Minimal settings stand-in carrying only the audio-features gate."""
    from unittest.mock import MagicMock

    return MagicMock(soundcharts_audio_features_enabled=enabled)


def _spotify_isrc_stub(url: str, *, request_id: int) -> str:
    """Return a fake ISRC while pinning the request correlation contract."""
    assert "open.spotify.com/track/" in url
    assert request_id > 0
    return "USABC1234567"


class _Spy:
    """Callable returning a fixed value, counting invocations."""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.return_value

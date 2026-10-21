"""Shared fixtures for sync orchestrator tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.sync.base import SyncResult, SyncStatus, TrackMatch
from app.services.sync.registry import _clear_adapters


@pytest.fixture(name="tidal_user")
def _fixture_tidal_user(db: Session) -> User:
    from app.services.auth import get_password_hash

    user = User(
        username="sync_orch_user",
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
    event = Event(
        code="ORCH01",
        join_code="8BBQQG",
        name="Orchestrator Test Event",
        created_by_user_id=tidal_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        tidal_sync_enabled=True,
        tidal_playlist_id="playlist_orch",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture(name="accepted_request")
def _fixture_accepted_request(db: Session, tidal_event: Event) -> Request:
    request = Request(
        event_id=tidal_event.id,
        song_title="Strobe",
        artist="deadmau5",
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="orch_test_dedupe_key",
        raw_search_query="deadmau5 Strobe",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@pytest.fixture(name="accepted_request_no_query")
def _fixture_accepted_request_no_query(db: Session, tidal_event: Event) -> Request:
    request = Request(
        event_id=tidal_event.id,
        song_title="Alive",
        artist="Daft Punk",
        source="manual",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="orch_test_no_query",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def _make_accepted_request(db: Session, event: Event, title: str, artist: str, key: str) -> Request:
    """Helper to create accepted requests for batch tests."""
    request = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key=key,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


class MockAdapter:
    """Mock adapter for testing."""

    def __init__(self, name="mock_service", connected=True, sync_result=None, sync_enabled=True):
        self._name = name
        self._connected = connected
        self._sync_result = sync_result
        self._sync_enabled = sync_enabled
        self.search_calls = []
        self.batch_add_calls = []

    @property
    def service_name(self):
        return self._name

    def is_connected(self, user):
        return self._connected

    def is_sync_enabled(self, event):
        return self._sync_enabled

    def sync_track(self, db, user, event, normalized, intent=None):
        if self._sync_result:
            return self._sync_result
        return SyncResult(
            service=self._name,
            status=SyncStatus.ADDED,
            track_match=TrackMatch(
                service=self._name,
                track_id="mock_track_123",
                title="Strobe",
                artist="deadmau5",
                match_confidence=0.95,
            ),
            playlist_id="mock_playlist_456",
        )

    def search_track(self, db, user, normalized, intent=None):
        self.search_calls.append(normalized)
        return TrackMatch(
            service=self._name,
            track_id=f"track_{normalized.raw_title.lower().replace(' ', '_')}",
            title=normalized.raw_title,
            artist=normalized.raw_artist,
            match_confidence=0.95,
        )

    def ensure_playlist(self, db, user, event):
        return event.tidal_playlist_id or "mock_playlist"

    def add_to_playlist(self, db, user, playlist_id, track_id):
        return True

    def add_tracks_to_playlist(self, db, user, playlist_id, track_ids):
        self.batch_add_calls.append(track_ids)
        return True


@pytest.fixture(name="clean_registry", autouse=True)
def _fixture_clean_registry():
    _clear_adapters()
    yield
    _clear_adapters()

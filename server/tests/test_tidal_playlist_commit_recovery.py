"""Database failure boundaries for Tidal playlist creation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.event import Event
from app.models.user import User
from app.services.providers import tidal_playlists


@pytest.mark.parametrize(
    ("ensure_playlist", "playlist_field"),
    [
        (tidal_playlists.create_event_playlist, "tidal_playlist_id"),
        (tidal_playlists.ensure_collection_playlist, "tidal_collection_playlist_id"),
    ],
)
def test_playlist_database_commit_failure_rolls_back_and_propagates(
    db, test_user, test_event, monkeypatch, ensure_playlist, playlist_field
):
    # Regression for baseline 57cfcdc6867f: DB errors were swallowed and poisoned the session.
    session = SimpleNamespace(
        user=SimpleNamespace(create_playlist=Mock(return_value=SimpleNamespace(id="new-playlist")))
    )
    monkeypatch.setattr(tidal_playlists, "get_tidal_session", lambda _db, _user: session)
    db.add(User(username=None, password_hash="invalid-row", role="dj"))

    with pytest.raises(IntegrityError):
        ensure_playlist(db, test_user, test_event)

    assert db.is_active
    stored_event = db.query(Event).filter_by(id=test_event.id).one()
    assert getattr(stored_event, playlist_field) is None
    assert db.query(User).filter_by(username=None).count() == 0


@pytest.mark.parametrize(
    ("ensure_playlist", "playlist_field"),
    [
        (tidal_playlists.create_event_playlist, "tidal_playlist_id"),
        (tidal_playlists.ensure_collection_playlist, "tidal_collection_playlist_id"),
    ],
)
def test_provider_playlist_creation_failure_is_safe_and_leaves_session_usable(
    db, test_user, test_event, monkeypatch, ensure_playlist, playlist_field
):
    session = SimpleNamespace(user=SimpleNamespace(create_playlist=Mock(side_effect=OSError)))
    monkeypatch.setattr(tidal_playlists, "get_tidal_session", lambda _db, _user: session)

    assert ensure_playlist(db, test_user, test_event) is None
    assert db.is_active
    assert getattr(test_event, playlist_field) is None

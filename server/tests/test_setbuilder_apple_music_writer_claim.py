"""Safety tests for the Apple Music playlist writer's one-shot claim."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.provider_connection import UserProviderConnection
from app.models.set import Set
from app.services import apple_music_tokens
from app.services.setbuilder import export_apple_music
from app.services.setbuilder.export_common import ExportTrack

TOKEN = "music-user-token-1234567890"


def _connected(db, user):
    db.add(
        UserProviderConnection(
            user_id=user.id,
            provider_id="apple_music",
            connection_state="connected",
            credential_type="music_user_token",
            credential_payload=json.dumps({"version": 1, "music_user_token": TOKEN}),
            metadata_json='{"storefront":"gb"}',
        )
    )
    db.commit()


def _set(db, user):
    value = Set(owner_id=user.id, name="Night")
    db.add(value)
    db.commit()
    return value


def _resolved():
    return [(ExportTrack(position=0, title="Song", artist="Artist"), "song-1")]


def _post(monkeypatch, behavior):
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens, "create_developer_token", lambda: ("dev", 100)
    )
    monkeypatch.setattr(export_apple_music.apple_music_tokens, "apple_post", behavior)
    monkeypatch.setattr(export_apple_music.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(export_apple_music, "_VERIFY_DELAYS_SECONDS", (0,))


def test_competing_sessions_cannot_claim_with_stale_set_objects(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'claim.sqlite'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    setup = sessions()
    barrier = Barrier(2)
    try:
        created = Set(owner_id=1, name="Night")
        setup.add(created)
        setup.commit()

        def claim():
            session = sessions()
            try:
                stale = session.get(Set, created.id)
                session.expunge(stale)
                session.rollback()
                barrier.wait()
                return export_apple_music._claim_export(session, stale)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: claim(), range(2)))

        assert sorted(outcomes) == [False, True]
        setup.expire(created)
        stored = setup.get(Set, created.id)
        assert stored.apple_music_export_pending is True
        assert stored.apple_music_playlist_id is None
    finally:
        setup.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_export_posts_once_and_confirms_ordered_duplicates(db, test_user, monkeypatch):
    _connected(db, test_user)
    set_obj = _set(db, test_user)
    requests = []

    def post(*args, **kwargs):
        requests.append((args, kwargs))
        return {
            "data": [
                {
                    "id": "p.created123",
                    "type": "library-playlists",
                    "attributes": {"playParams": {"globalId": "pl.shared123"}},
                }
            ]
        }

    _post(monkeypatch, post)
    reads = []

    def get(*args, **kwargs):
        reads.append((args, kwargs))
        return {
            "data": [
                {"type": "library-songs", "attributes": {"playParams": {"catalogId": sid}}}
                for sid in ("song-1", "song-2", "song-1")
            ]
        }

    monkeypatch.setattr(export_apple_music.apple_music_tokens, "apple_get", get)
    resolved = [
        (ExportTrack(position=i, title=f"Song {i}", artist="Artist"), song_id)
        for i, song_id in enumerate(("song-1", "song-2", "song-1"))
    ]

    outcome = export_apple_music.export_to_apple_music(db, test_user, set_obj, resolved)

    assert len(requests) == 1
    assert requests[0][1]["json_body"]["relationships"]["tracks"]["data"] == [
        {"id": song_id, "type": "songs"} for song_id in ("song-1", "song-2", "song-1")
    ]
    assert len(reads) == 1
    assert outcome.added == 3
    assert outcome.playlist_url == "https://music.apple.com/gb/playlist/pl.shared123"
    db.refresh(set_obj)
    assert set_obj.apple_music_playlist_id == "p.created123"
    assert set_obj.apple_music_export_pending is False
    assert set_obj.status == "exported"


def test_uncertain_post_keeps_claim_and_retry_never_posts_again(db, test_user, monkeypatch):
    _connected(db, test_user)
    set_obj = _set(db, test_user)
    posts = []

    def post(*_args, **_kwargs):
        posts.append("POST")
        raise apple_music_tokens.AppleMusicRequestUncertain

    _post(monkeypatch, post)
    with pytest.raises(export_apple_music.AppleMusicWriteUncertain) as first:
        export_apple_music.export_to_apple_music(db, test_user, set_obj, _resolved())
    assert first.value.playlist_id is None

    with pytest.raises(export_apple_music.AppleMusicWriteUncertain) as retry:
        export_apple_music.export_to_apple_music(db, test_user, set_obj, _resolved())

    assert retry.value.playlist_id is None
    assert posts == ["POST"]
    db.refresh(set_obj)
    assert set_obj.apple_music_export_pending is True
    assert set_obj.status == "draft"


def test_stale_rejected_write_does_not_invalidate_a_newer_grant(db, test_user, monkeypatch):
    _connected(db, test_user)
    set_obj = _set(db, test_user)
    connection = (
        db.query(UserProviderConnection)
        .filter_by(user_id=test_user.id, provider_id="apple_music")
        .one()
    )

    def rejected(*_args, **_kwargs):
        connection.authorization_generation += 1
        db.commit()
        raise apple_music_tokens.AppleMusicUserAuthorizationError

    _post(monkeypatch, rejected)
    with pytest.raises(apple_music_tokens.AppleMusicUserAuthorizationError):
        export_apple_music.export_to_apple_music(db, test_user, set_obj, _resolved())

    db.refresh(connection)
    db.refresh(set_obj)
    assert connection.connection_state == "connected"
    assert connection.authorization_generation == 1
    assert set_obj.apple_music_export_pending is False
    assert set_obj.apple_music_playlist_id is None


def test_verified_playlist_id_survives_final_commit_failure(db, test_user, monkeypatch):
    _connected(db, test_user)
    set_obj = _set(db, test_user)

    def request(method, *_args, **_kwargs):
        return {"data": [{"id": "p.created123", "type": "library-playlists"}]}

    _post(monkeypatch, request)
    monkeypatch.setattr(
        export_apple_music.apple_music_tokens,
        "apple_get",
        lambda *_args, **_kwargs: {
            "data": [
                {
                    "type": "library-songs",
                    "attributes": {"playParams": {"catalogId": "song-1"}},
                }
            ]
        },
    )
    original_commit = db.commit
    commits = 0

    def fail_second_commit():
        nonlocal commits
        commits += 1
        if commits == 3:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("commit", {}, RuntimeError("db unavailable"))
        original_commit()

    monkeypatch.setattr(db, "commit", fail_second_commit)
    with pytest.raises(export_apple_music.AppleMusicWriteUncertain) as uncertain:
        export_apple_music.export_to_apple_music(db, test_user, set_obj, _resolved())

    assert uncertain.value.playlist_id == "p.created123"
    db.rollback()
    db.refresh(set_obj)
    assert set_obj.apple_music_playlist_id == "p.created123"
    assert set_obj.apple_music_export_pending is True
    assert set_obj.status == "draft"

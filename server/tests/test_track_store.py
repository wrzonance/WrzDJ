"""Tests for track store — read/write service for master tracks table."""

from datetime import datetime

from app.models.track import Track
from app.services.tracks.store import TrackIdentity, get_track, upsert_track


def _make_track(db, **kw):
    t = Track(signature=kw.pop("signature", "sig-1"), title="T", artist="A", **kw)
    db.add(t)
    db.flush()
    return t


def test_get_track_by_isrc_wins(db):
    _make_track(db, signature="sig-x", isrc="USUM71900764", energy=8)
    found = get_track(db, isrc="USUM71900764")
    assert found is not None and found.energy == 8


def test_get_track_falls_back_to_signature(db):
    _make_track(db, signature="sig-y", isrc=None, energy=5)
    assert get_track(db, isrc="NONEXISTENT00", signature="sig-y").energy == 5


def test_get_track_normalizes_isrc(db):
    _make_track(db, signature="sig-z", isrc="USUM71900764")
    assert get_track(db, isrc="us-um7-1900764") is not None


def test_get_track_miss_returns_none(db):
    assert get_track(db, isrc="MISS00000000", signature="nope") is None


T0 = datetime(2026, 6, 23, 12, 0, 0)


def test_upsert_inserts_new_track(db):
    t = upsert_track(
        db,
        identity=TrackIdentity(
            title="Sandstorm", artist="Darude", signature="sig-sand", isrc="FIXXX1234567"
        ),
        values={"energy": 9, "bpm": 136.0},
        sources={"energy": "soundcharts", "bpm": "beatport"},
        fetched_at=T0,
    )
    assert t.id is not None
    assert t.energy == 9 and t.bpm == 136.0
    assert t.provenance["energy"]["source"] == "soundcharts"
    assert t.provenance["bpm"]["source"] == "beatport"


def test_upsert_updates_existing_by_signature_no_duplicate(db):
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-1"),
        values={"bpm": 120.0},
        sources={"bpm": "tidal"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-1"),
        values={"genre": "trance"},
        sources={"genre": "musicbrainz"},
        fetched_at=T0,
    )
    rows = db.query(Track).filter(Track.signature == "sig-1").all()
    assert len(rows) == 1
    assert rows[0].bpm == 120.0 and rows[0].genre == "trance"

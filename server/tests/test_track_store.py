"""Tests for track store — read/write service for master tracks table."""

from app.models.track import Track
from app.services.tracks.store import get_track


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

"""Tests for track store — read/write service for master tracks table."""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

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


def test_upsert_does_not_downgrade_measured_energy(db):
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-e"),
        values={"energy": 8},
        sources={"energy": "soundcharts"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-e"),
        values={"energy": 3},
        sources={"energy": "llm"},
        fetched_at=T0,
    )
    row = db.query(Track).filter(Track.signature == "sig-e").one()
    assert row.energy == 8  # llm did not clobber soundcharts
    assert row.provenance["energy"]["source"] == "soundcharts"


def test_upsert_allows_higher_precedence_override(db):
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-o"),
        values={"energy": 8},
        sources={"energy": "soundcharts"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-o"),
        values={"energy": 6},
        sources={"energy": "lexicon"},
        fetched_at=T0,
    )
    row = db.query(Track).filter(Track.signature == "sig-o").one()
    assert row.energy == 6 and row.provenance["energy"]["source"] == "lexicon"


def test_upsert_backfills_isrc_onto_signature_row(db):
    # First seen with no ISRC (e.g. manual add)
    upsert_track(
        db,
        identity=TrackIdentity(title="Sandstorm", artist="Darude", signature="sig-bf"),
        values={"bpm": 136.0},
        sources={"bpm": "manual"},
        fetched_at=T0,
    )
    # Later seen WITH an ISRC, same signature → backfill, one row
    upsert_track(
        db,
        identity=TrackIdentity(
            title="Sandstorm", artist="Darude", signature="sig-bf", isrc="FIXXX1234567"
        ),
        values={"energy": 9},
        sources={"energy": "soundcharts"},
        fetched_at=T0,
    )
    rows = db.query(Track).filter(Track.signature == "sig-bf").all()
    assert len(rows) == 1
    assert rows[0].isrc == "FIXXX1234567"
    assert rows[0].bpm == 136.0 and rows[0].energy == 9


# ---------------------------------------------------------------------------
# Fix 1 / Fix 2: input validation — no partial write, clear error messages
# ---------------------------------------------------------------------------


def test_upsert_raises_if_sources_key_missing(db):
    """values has 'energy' but sources is missing 'energy' → ValueError, no row created."""
    with pytest.raises(ValueError, match="sources"):
        upsert_track(
            db,
            identity=TrackIdentity(title="T", artist="A", signature="sig-missing-src"),
            values={"energy": 8, "genre": "x"},
            sources={"energy": "soundcharts"},  # genre not in sources
            fetched_at=T0,
        )
    # no row must have been committed
    assert db.query(Track).filter(Track.signature == "sig-missing-src").count() == 0


def test_upsert_raises_for_unknown_source(db):
    """Typo'd source name → ValueError naming the offending source."""
    with pytest.raises(ValueError, match="sondcharts"):
        upsert_track(
            db,
            identity=TrackIdentity(title="T", artist="A", signature="sig-bad-src"),
            values={"energy": 8},
            sources={"energy": "sondcharts"},  # typo
            fetched_at=T0,
        )
    assert db.query(Track).filter(Track.signature == "sig-bad-src").count() == 0


def test_upsert_raises_for_unknown_field(db):
    """A values key that is not a writable enrichment column → ValueError, no row.

    Without this guard, setattr would create a non-persisted instance attribute
    while provenance recorded a write (silent data-contract mismatch).
    """
    with pytest.raises(ValueError, match="unknown writable field"):
        upsert_track(
            db,
            identity=TrackIdentity(title="T", artist="A", signature="sig-bad-field"),
            values={"enrgy": 8},  # typo for "energy"
            sources={"enrgy": "soundcharts"},
            fetched_at=T0,
        )
    assert db.query(Track).filter(Track.signature == "sig-bad-field").count() == 0


def test_upsert_rejects_identity_field_in_values(db):
    """Identity columns (set via TrackIdentity) are not writable through values."""
    with pytest.raises(ValueError, match="unknown writable field"):
        upsert_track(
            db,
            identity=TrackIdentity(title="T", artist="A", signature="sig-ident"),
            values={"signature": "hijack"},
            sources={"signature": "manual"},
            fetched_at=T0,
        )
    assert db.query(Track).filter(Track.signature == "sig-ident").count() == 0


def test_upsert_skips_none_values(db):
    """A provider lacking a field passes None; it must not overwrite stored data."""
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-none"),
        values={"energy": 8},
        sources={"energy": "soundcharts"},
        fetched_at=T0,
    )
    # Later enrichment has no energy/bpm → passes None at equal/higher precedence
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-none"),
        values={"energy": None, "bpm": None},
        sources={"energy": "lexicon", "bpm": "beatport"},
        fetched_at=T0,
    )
    row = db.query(Track).filter(Track.signature == "sig-none").one()
    assert row.energy == 8  # None did not clobber the measured value
    assert row.bpm is None
    assert row.provenance["energy"]["source"] == "soundcharts"  # unchanged
    assert "bpm" not in row.provenance  # no provenance for an unresolved field


# ---------------------------------------------------------------------------
# Fix 4: ISRC-authoritative on conflict (ISRC match wins over signature)
# ---------------------------------------------------------------------------


def test_upsert_isrc_match_wins_over_different_signature(db):
    """Row A created with sigA + ISRC; upserting with sigB + same ISRC updates row A, no new row."""
    upsert_track(
        db,
        identity=TrackIdentity(title="T", artist="A", signature="sigA", isrc="FIXXX1111111"),
        values={"bpm": 120.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="T", artist="A", signature="sigB", isrc="FIXXX1111111"),
        values={"genre": "house"},
        sources={"genre": "musicbrainz"},
        fetched_at=T0,
    )
    rows = db.query(Track).filter(Track.isrc == "FIXXX1111111").all()
    assert len(rows) == 1, "ISRC match must be authoritative; no duplicate row for sigB"
    assert rows[0].signature == "sigA"  # original row, not a new one
    assert rows[0].genre == "house"  # value was written onto the ISRC row


# ---------------------------------------------------------------------------
# Fix 5: backfill soundcharts_uuid like ISRC
# ---------------------------------------------------------------------------


def test_upsert_backfills_soundcharts_uuid(db):
    """Row first created without soundcharts_uuid; second upsert with one → backfilled, one row."""
    upsert_track(
        db,
        identity=TrackIdentity(title="T", artist="A", signature="sig-sc1"),
        values={"bpm": 120.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="T", artist="A", signature="sig-sc1", soundcharts_uuid="u-1"),
        values={"genre": "techno"},
        sources={"genre": "soundcharts"},
        fetched_at=T0,
    )
    rows = db.query(Track).filter(Track.signature == "sig-sc1").all()
    assert len(rows) == 1
    assert rows[0].soundcharts_uuid == "u-1"


# ---------------------------------------------------------------------------
# Fix 7: energy CHECK constraint (0–10 range enforced by DB)
# ---------------------------------------------------------------------------


def test_energy_check_constraint_rejects_out_of_range(db):
    """Inserting energy=50 must raise IntegrityError due to CHECK constraint."""
    t = Track(signature="sig-energy-bad", title="T", artist="A", energy=50)
    db.add(t)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

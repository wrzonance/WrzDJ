"""Tests for track store — read/write service for master tracks table."""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.track import Track
from app.services.tracks import store
from app.services.tracks.provenance import precedence
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
# #541: "legacy" provenance source — lowest-trust, attributes pre-store data
# backfilled from existing Request columns. Any real later enrichment overrides
# it; legacy never downgrades a higher-precedence value.
# ---------------------------------------------------------------------------


def test_legacy_precedence_is_below_community():
    assert precedence("legacy") == 30
    assert precedence("legacy") < precedence("community")


def test_non_legacy_source_overwrites_legacy_value(db):
    """A real provider (musicbrainz, 50) must overwrite a legacy-sourced value."""
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-leg-up"),
        values={"genre": "pop"},
        sources={"genre": "legacy"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-leg-up"),
        values={"genre": "house"},
        sources={"genre": "musicbrainz"},
        fetched_at=T0,
    )
    row = db.query(Track).filter(Track.signature == "sig-leg-up").one()
    assert row.genre == "house"
    assert row.provenance["genre"]["source"] == "musicbrainz"


def test_legacy_does_not_downgrade_higher_precedence(db):
    """legacy (30) must NOT clobber an existing higher-precedence value."""
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-leg-keep"),
        values={"genre": "house"},
        sources={"genre": "musicbrainz"},
        fetched_at=T0,
    )
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-leg-keep"),
        values={"genre": "pop"},
        sources={"genre": "legacy"},
        fetched_at=T0,
    )
    row = db.query(Track).filter(Track.signature == "sig-leg-keep").one()
    assert row.genre == "house"  # legacy did not downgrade musicbrainz
    assert row.provenance["genre"]["source"] == "musicbrainz"


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


# ---------------------------------------------------------------------------
# #540 debt: concurrent-insert reconciliation (spec §5)
#
# Two callers both miss in get_track for the same new identity and both create a
# Track; the first INSERT wins and the second must NOT raise IntegrityError — it
# must roll back its savepoint, re-read the now-existing row, and apply the
# precedence-guarded merge onto it. Net: exactly one row, no lost writes.
#
# The race is exercised deterministically in a single session by monkeypatching
# get_track so its FIRST call returns None (the TOCTOU window where the caller
# believes the row is absent) while a conflicting row is already committed; later
# calls delegate to the real lookup so reconciliation can re-read the winner.
# ---------------------------------------------------------------------------


def _first_call_none(monkeypatch):
    """Patch store.get_track so the first invocation returns None, then real.

    Returns a one-element list whose item is the count of times the patched
    first-None branch was taken (proves the reconciliation path ran).
    """
    real_get_track = store.get_track
    state = {"calls": 0, "forced_none": 0}

    def fake_get_track(db, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            state["forced_none"] += 1
            return None  # simulate the TOCTOU miss
        return real_get_track(db, **kwargs)

    monkeypatch.setattr(store, "get_track", fake_get_track)
    return state


def test_upsert_reconciles_concurrent_signature_insert(db, monkeypatch):
    """A racing signature INSERT loses cleanly: re-read existing row, merge, one row."""
    # A concurrent caller already created+committed the row with measured energy.
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-race"),
        values={"energy": 8, "bpm": 120.0},
        sources={"energy": "soundcharts", "bpm": "beatport"},
        fetched_at=T0,
    )
    db.commit()

    state = _first_call_none(monkeypatch)

    # This caller thinks the row is absent (first get_track → None), tries to
    # INSERT the same signature, hits the unique constraint, and must reconcile.
    track = upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-race"),
        values={"energy": 3, "genre": "trance"},
        sources={"energy": "llm", "genre": "musicbrainz"},
        fetched_at=T0,
    )

    # (a) no exception — reached here. (e) the first-None reconciliation branch ran.
    assert state["forced_none"] == 1, "reconciliation path was not exercised"

    # (b) exactly one row for that signature.
    rows = db.query(Track).filter(Track.signature == "sig-race").all()
    assert len(rows) == 1
    row = rows[0]
    assert track.id == row.id

    # (c) precedence-correct merge: musicbrainz (50) wrote a new field; llm (10)
    #     did NOT downgrade the measured soundcharts (50) energy.
    assert row.genre == "trance"
    assert row.provenance["genre"]["source"] == "musicbrainz"
    assert row.energy == 8, "low-precedence llm must not clobber measured energy"
    assert row.provenance["energy"]["source"] == "soundcharts"

    # (d) no pre-existing value was lost.
    assert row.bpm == 120.0
    assert row.provenance["bpm"]["source"] == "beatport"


def test_upsert_reconciles_concurrent_isrc_insert(db, monkeypatch):
    """A racing INSERT colliding on the ISRC unique constraint reconciles too."""
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-isrc-a", isrc="FIXXX9999999"),
        values={"bpm": 128.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )
    db.commit()

    state = _first_call_none(monkeypatch)

    # Different signature, SAME ISRC → collides on uq_tracks_isrc, must reconcile
    # onto the existing ISRC row (ISRC is authoritative).
    track = upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-isrc-b", isrc="FIXXX9999999"),
        values={"genre": "house"},
        sources={"genre": "musicbrainz"},
        fetched_at=T0,
    )

    assert state["forced_none"] == 1, "reconciliation path was not exercised"

    rows = db.query(Track).filter(Track.isrc == "FIXXX9999999").all()
    assert len(rows) == 1
    row = rows[0]
    assert track.id == row.id
    assert row.signature == "sig-isrc-a"  # original row survived
    assert row.genre == "house"  # merged onto it
    assert row.bpm == 128.0  # pre-existing value not lost


def test_upsert_reraises_when_conflict_unreconcilable(db, monkeypatch):
    """If get_track keeps returning None after a real IntegrityError, re-raise.

    A genuine unique violation that cannot be reconciled (the conflicting row is
    not findable) must not be silently swallowed.
    """
    # Commit a real conflicting row so the INSERT genuinely violates the constraint.
    upsert_track(
        db,
        identity=TrackIdentity(title="S", artist="D", signature="sig-unrec"),
        values={"bpm": 100.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )
    db.commit()

    # get_track ALWAYS returns None → caller inserts, collides, re-reads, still
    # finds nothing → the IntegrityError must propagate.
    monkeypatch.setattr(store, "get_track", lambda db, **kw: None)

    with pytest.raises(IntegrityError):
        upsert_track(
            db,
            identity=TrackIdentity(title="S", artist="D", signature="sig-unrec"),
            values={"energy": 5},
            sources={"energy": "llm"},
            fetched_at=T0,
        )


def test_upsert_isrc_conflict_does_not_overwrite_different_recording(db):
    """ISRC CONFLICT (#552): when the signature matches a row whose ISRC is a
    DIFFERENT non-null recording, upsert must NOT overwrite it with the incoming
    recording's values. Signature is unique so the new recording can't get its own
    row — the existing row is preserved (no corruption) rather than clobbered."""
    upsert_track(
        db,
        identity=TrackIdentity(
            title="T", artist="A", signature="sig-conflict", isrc="USAAA1111111"
        ),
        values={"bpm": 120.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )

    # Same signature, DIFFERENT ISRC (a different release) — must not clobber.
    result = upsert_track(
        db,
        identity=TrackIdentity(
            title="T", artist="A", signature="sig-conflict", isrc="USBBB2222222"
        ),
        values={"bpm": 200.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )

    rows = db.query(Track).filter(Track.signature == "sig-conflict").all()
    assert len(rows) == 1  # signature is unique — no second row
    assert rows[0].isrc == "USAAA1111111"  # the original recording's ISRC is kept
    assert rows[0].bpm == 120.0  # NOT overwritten by the conflicting recording's 200
    assert result.isrc == "USAAA1111111"  # returned the existing row, unchanged


def test_upsert_isrc_conflict_via_reconcile_race_does_not_overwrite(db, monkeypatch):
    """The ISRC-conflict guard must also catch the reconcile-RACE path: when the
    insert loses the signature unique-constraint and re-reads a DIFFERENT-ISRC row,
    the guard (now checked after resolution, not just on the initial get_track)
    still prevents overwriting it (#552, review)."""
    upsert_track(
        db,
        identity=TrackIdentity(
            title="T", artist="A", signature="sig-race-conflict", isrc="USAAA1111111"
        ),
        values={"bpm": 120.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )
    db.commit()

    # Force the TOCTOU window: first get_track → None (so the insert path runs and
    # collides on the unique signature), later calls delegate to the real lookup.
    real = store.get_track
    state = {"n": 0}

    def fake(db, **kw):
        state["n"] += 1
        return None if state["n"] == 1 else real(db, **kw)

    monkeypatch.setattr(store, "get_track", fake)

    # Incoming: same signature, DIFFERENT ISRC — resolved via the reconcile re-read.
    result = upsert_track(
        db,
        identity=TrackIdentity(
            title="T", artist="A", signature="sig-race-conflict", isrc="USBBB2222222"
        ),
        values={"bpm": 200.0},
        sources={"bpm": "beatport"},
        fetched_at=T0,
    )

    assert state["n"] >= 2, "reconcile re-read path must have been taken"
    rows = db.query(Track).filter(Track.signature == "sig-race-conflict").all()
    assert len(rows) == 1
    assert rows[0].isrc == "USAAA1111111"  # original recording preserved
    assert rows[0].bpm == 120.0  # NOT overwritten via the reconcile path
    assert result.isrc == "USAAA1111111"

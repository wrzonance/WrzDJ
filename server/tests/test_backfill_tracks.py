"""Tests for the request->tracks backfill script (#541).

Seeds Request rows (some sharing artist/title, some with partial metadata, one
with none), runs the backfill, and asserts:
  * tracks rows are created with source="legacy" and the present values,
  * a same-song duplicate request collapses to ONE track row (sig dedup),
  * re-running is a pure no-op (no new rows, values unchanged) — idempotent.
"""

import app.scripts.backfill_tracks as bf
from app.models.request import Request, RequestStatus
from app.models.track import Track
from app.scripts.backfill_tracks import backfill_tracks
from app.services.setbuilder.pool import dedupe_signature


def _make_request(db, event, **kw):
    r = Request(
        event_id=event.id,
        song_title=kw.pop("song_title"),
        artist=kw.pop("artist"),
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key=kw.pop("dedupe_key"),
        **kw,
    )
    db.add(r)
    db.flush()
    return r


def test_backfill_creates_legacy_tracks(db, test_event):
    _make_request(
        db,
        test_event,
        song_title="Sandstorm",
        artist="Darude",
        dedupe_key="dk-1",
        genre="trance",
        bpm=136.0,
        musical_key="8A",
    )
    db.commit()

    result = backfill_tracks(db)

    assert result["scanned"] == 1
    assert result["upserted"] == 1
    assert result["errors"] == 0

    sig = dedupe_signature("Darude", "Sandstorm")
    track = db.query(Track).filter(Track.signature == sig).one()
    assert track.genre == "trance"
    assert track.bpm == 136.0
    assert track.musical_key == "8A"
    assert track.provenance["genre"]["source"] == "legacy"
    assert track.provenance["bpm"]["source"] == "legacy"
    assert track.provenance["musical_key"]["source"] == "legacy"


def test_backfill_partial_metadata_only_writes_present_fields(db, test_event):
    _make_request(
        db,
        test_event,
        song_title="Strobe",
        artist="Deadmau5",
        dedupe_key="dk-2",
        bpm=128.0,
        # genre and musical_key left None
    )
    db.commit()

    backfill_tracks(db)

    sig = dedupe_signature("Deadmau5", "Strobe")
    track = db.query(Track).filter(Track.signature == sig).one()
    assert track.bpm == 128.0
    assert track.genre is None
    assert track.musical_key is None
    assert "bpm" in track.provenance
    assert "genre" not in track.provenance
    assert "musical_key" not in track.provenance


def test_backfill_skips_requests_with_no_metadata(db, test_event):
    _make_request(
        db,
        test_event,
        song_title="Nothing Here",
        artist="No Meta",
        dedupe_key="dk-3",
        # no genre/bpm/musical_key at all
    )
    db.commit()

    result = backfill_tracks(db)

    assert result["scanned"] == 0
    assert result["upserted"] == 0
    sig = dedupe_signature("No Meta", "Nothing Here")
    assert db.query(Track).filter(Track.signature == sig).count() == 0


def test_backfill_duplicate_song_collapses_to_one_row(db, test_event):
    # Two requests for the same song (same artist/title) → one track row.
    _make_request(
        db,
        test_event,
        song_title="Levels",
        artist="Avicii",
        dedupe_key="dk-4a",
        bpm=126.0,
    )
    _make_request(
        db,
        test_event,
        song_title="Levels",
        artist="Avicii",
        dedupe_key="dk-4b",
        genre="house",
    )
    db.commit()

    result = backfill_tracks(db)

    assert result["scanned"] == 2
    sig = dedupe_signature("Avicii", "Levels")
    rows = db.query(Track).filter(Track.signature == sig).all()
    assert len(rows) == 1, "same-song duplicate requests must collapse to one track"
    # Both contributions land on the single row.
    assert rows[0].bpm == 126.0
    assert rows[0].genre == "house"


def test_backfill_is_idempotent(db, test_event):
    _make_request(
        db,
        test_event,
        song_title="One More Time",
        artist="Daft Punk",
        dedupe_key="dk-5",
        genre="french house",
        bpm=123.0,
        musical_key="11B",
    )
    db.commit()

    backfill_tracks(db)
    sig = dedupe_signature("Daft Punk", "One More Time")
    first = db.query(Track).filter(Track.signature == sig).one()
    first_id = first.id
    first_prov = dict(first.provenance)
    rows_before = db.query(Track).count()

    # Second run must add no rows and change no values.
    result = backfill_tracks(db)
    rows_after = db.query(Track).count()
    assert rows_after == rows_before, "re-run must not create new rows"

    again = db.query(Track).filter(Track.signature == sig).one()
    assert again.id == first_id
    assert again.genre == "french house"
    assert again.bpm == 123.0
    assert again.musical_key == "11B"
    assert again.provenance == first_prov
    # The legacy source is still the recorded provenance (no spurious overwrite).
    assert result["upserted"] == 1  # scanned+upsert still counted, but no-op data-wise


def test_backfill_isolates_a_failing_row(db, test_event, monkeypatch):
    """REGRESSION (review #541): a row whose write raises and POISONS the Session
    must be isolated by its per-row savepoint — the run continues and other rows
    still upsert, instead of one bad row aborting the whole backfill + final commit.
    """
    from sqlalchemy import text

    # "Bad Row" sorts first by id (inserted first) → processed first.
    _make_request(
        db, test_event, song_title="Bad Row", artist="Boom", dedupe_key="dk-bad", bpm=100.0
    )
    _make_request(
        db, test_event, song_title="Good Row", artist="Nice", dedupe_key="dk-good", bpm=120.0
    )
    db.commit()

    real_upsert = bf.upsert_track
    bad_sig = dedupe_signature("Boom", "Bad Row")

    def flaky_upsert(db, *, identity, values, sources, fetched_at):
        if identity.signature == bad_sig:
            # A real flush-time IntegrityError (NULL signature) leaves the Session
            # in a rollback-needed state — exactly what the savepoint must recover.
            db.execute(
                text(
                    "INSERT INTO tracks (signature, title, artist, provenance) "
                    "VALUES (NULL, 'x', 'y', '{}')"
                )
            )
        return real_upsert(
            db, identity=identity, values=values, sources=sources, fetched_at=fetched_at
        )

    monkeypatch.setattr(bf, "upsert_track", flaky_upsert)

    result = backfill_tracks(db)

    assert result["errors"] == 1
    assert result["upserted"] == 1  # the good row survived the bad row's failure
    good_sig = dedupe_signature("Nice", "Good Row")
    assert db.query(Track).filter(Track.signature == good_sig).one().bpm == 120.0
    # The poisoning insert was rolled back with its savepoint — no NULL row leaked.
    assert db.query(Track).filter(Track.signature == bad_sig).count() == 0

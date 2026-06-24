"""Backfill the master tracks table from existing Request metadata (#541).

Existing `requests` rows carry genre/bpm/musical_key that pre-date the master
`tracks` store (#540) and have no original-source record. This one-shot, idempotent
script copies those columns into `tracks`, attributing them the lowest-trust
``legacy`` provenance source so any real later enrichment cleanly overrides them.

Idempotent by construction: the normalized artist+title signature dedupes
re-runs onto the same row, and the precedence guard in ``upsert_track`` means a
second pass re-writes identical legacy values without creating rows or losing
higher-precedence data.

Run with: ``python -m app.scripts.backfill_tracks``
"""

import logging

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.session import SessionLocal
from app.models.request import Request
from app.services.setbuilder.pool import dedupe_signature
from app.services.tracks.store import TrackIdentity, upsert_track

logger = logging.getLogger(__name__)

# Request column -> Track column. Request.musical_key and Track.musical_key share
# the name, as do genre/bpm; mapping is 1:1 but kept explicit for clarity.
_FIELD_MAP: dict[str, str] = {
    "genre": "genre",
    "bpm": "bpm",
    "musical_key": "musical_key",
}


def backfill_tracks(db: Session) -> dict:
    """Copy genre/bpm/musical_key from Request rows into the master tracks store.

    Streams every Request with at least one of those fields populated (so memory
    stays bounded as the table grows), upserting a ``legacy``-sourced track per
    row. Each row's write is wrapped in its own SAVEPOINT: a failed flush rolls
    back only that row (the shared Session stays usable and prior rows survive),
    so one bad row never aborts the run. Commits once at the end.

    Returns a summary: {"scanned": rows_with_metadata, "upserted": rows_upserted,
    "errors": rows_that_raised}.
    """
    requests = (
        db.query(Request)
        .filter(
            (Request.genre.isnot(None))
            | (Request.bpm.isnot(None))
            | (Request.musical_key.isnot(None))
        )
        .order_by(Request.id)
        .yield_per(500)
    )

    scanned = 0
    upserted = 0
    errors = 0
    for request in requests:
        scanned += 1
        try:
            values = {
                track_field: getattr(request, req_field)
                for req_field, track_field in _FIELD_MAP.items()
                if getattr(request, req_field) is not None
            }
            if not values:
                # Defensive: the query guarantees at least one field, but skip
                # cleanly if a value vanished between query and read.
                scanned -= 1
                continue
            sources = {field: "legacy" for field in values}
            signature = dedupe_signature(request.artist, request.song_title)
            # Per-row savepoint: a flush/constraint error here would otherwise leave
            # the shared Session in a rollback-needed state and abort every later row
            # plus the final commit. Roll back just this row's savepoint and go on.
            savepoint = db.begin_nested()
            try:
                upsert_track(
                    db,
                    identity=TrackIdentity(
                        title=request.song_title,
                        artist=request.artist,
                        signature=signature,
                    ),
                    values=values,
                    sources=sources,
                    fetched_at=request.updated_at or utcnow(),
                )
                savepoint.commit()
            except Exception:
                savepoint.rollback()
                raise
            upserted += 1
        except Exception:
            errors += 1
            logger.exception("backfill_tracks: skipping request id=%s", request.id)

    db.commit()
    return {"scanned": scanned, "upserted": upserted, "errors": errors}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        summary = backfill_tracks(db)
        print(
            f"backfill_tracks: scanned={summary['scanned']} "
            f"upserted={summary['upserted']} errors={summary['errors']}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""Pre-build pool coverage check (#542).

The pool→builder contract is: **bpm + key + energy + genre + duration must be
present for every pool track before set generation.** This module reports how
well a set's pool satisfies that contract — per-field missing counts plus an
overall ``ready`` signal — so the deterministic build endpoint and the agent
autobuild path can surface a SOFT, overridable warning (never a hard block) in
the build-confirmation dialog (#538).

It is intentionally pure and synchronous: it reads only the pool rows handed to
it (already resolved against the master tracks store on import, see
``pool.hydrate_candidates_from_store``) and computes counts — no DB writes, no
provider calls, trivially unit-testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.set_pool import SetPoolTrack

# The five required pool→builder contract fields, in display order. ``key`` maps
# to ``camelot or key`` (what the builder reads via pass1 ``_track_meta``) and
# ``duration`` to ``duration_sec``; the rest are direct column names.
REQUIRED_FIELDS: tuple[str, ...] = ("bpm", "key", "genre", "duration", "energy")

# A pool is "ready" to build when at least this fraction of its tracks carry all
# five fields. Soft gate only — the build is overridable below it (#538/#542).
READY_THRESHOLD = 0.80


def _has_field(track: SetPoolTrack, field: str) -> bool:
    """Whether a pool track carries the named contract field.

    ``key`` is satisfied by either the resolved Camelot code or a raw key, to
    match the builder's ``camelot or key`` read; the others map to a single
    column. ``bpm``/``duration``/``energy`` use ``is not None`` so a legitimate
    0 still counts as present (never reached for bpm/duration in practice, but
    explicit so the contract is unambiguous)."""
    if field == "key":
        return bool(track.camelot or track.key)
    if field == "genre":
        return bool(track.genre)
    column = "duration_sec" if field == "duration" else field
    return getattr(track, column) is not None


def pool_coverage(tracks: Sequence[SetPoolTrack]) -> dict[str, object]:
    """Report coverage of the five required contract fields over a set's pool.

    Returns a JSON-serializable dict:
      * ``pool_size`` — total pool tracks,
      * ``missing`` — ``{field: count_of_tracks_missing_it}`` for each required field,
      * ``fully_covered_count`` — tracks carrying ALL five fields,
      * ``ready`` — True when the fully-covered fraction meets ``READY_THRESHOLD``
        (an empty pool is vacuously ready: there is nothing under-enriched to warn
        about; the empty-pool case is handled elsewhere).
    """
    pool_size = len(tracks)
    missing = {field: 0 for field in REQUIRED_FIELDS}
    fully_covered = 0
    for track in tracks:
        complete = True
        for field in REQUIRED_FIELDS:
            if not _has_field(track, field):
                missing[field] += 1
                complete = False
        if complete:
            fully_covered += 1

    ready = pool_size == 0 or (fully_covered / pool_size) >= READY_THRESHOLD
    return {
        "pool_size": pool_size,
        "missing": missing,
        "fully_covered_count": fully_covered,
        "ready": ready,
    }


def coverage_for_set(db: Session, set_id: int) -> dict[str, object]:
    """Convenience wrapper: load a set's pool tracks and report their coverage.

    Used by the build endpoint and the agent autobuild path to attach coverage
    to their result without each re-querying the pool."""
    tracks = db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_id).all()
    return pool_coverage(tracks)

"""Set-scoped DJ-curated pairings for WrzDJSet (#392)."""

import json
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_pairing import SetPairing
from app.models.set_pool import SetPoolTrack

MAX_TAGS = 12


@dataclass(frozen=True)
class PairingView:
    pairing: SetPairing
    from_track: SetPoolTrack | None
    into_track: SetPoolTrack | None


def normalize_tags(tags: list[str]) -> list[str]:
    """Lowercase, trim, de-dupe, and cap DJ-entered tags."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag[:32])
        if len(out) >= MAX_TAGS:
            break
    return out


def tags_for_pairing(pairing: SetPairing) -> list[str]:
    """Parse the stored JSON tag list; bad historical data reads as empty."""
    try:
        value = json.loads(pairing.tags_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return normalize_tags([v for v in value if isinstance(v, str)])


def _tags_json(tags: list[str]) -> str:
    return json.dumps(normalize_tags(tags), separators=(",", ":"))


def _persist(db: Session, pairing: SetPairing, commit: bool) -> None:
    """Commit + refresh (REST callers) or just flush (inside an agent turn)."""
    if commit:
        db.commit()
        db.refresh(pairing)
    else:
        db.flush()


def get_pairing(db: Session, set_obj: Set, pairing_id: int) -> SetPairing | None:
    """Fetch a pairing scoped to the set."""
    return (
        db.query(SetPairing)
        .filter(SetPairing.id == pairing_id, SetPairing.set_id == set_obj.id)
        .one_or_none()
    )


def find_pairing(
    db: Session, set_id: int, from_track_id: str, into_track_id: str
) -> SetPairing | None:
    """Find a pairing by its transition identity."""
    return (
        db.query(SetPairing)
        .filter(
            SetPairing.set_id == set_id,
            SetPairing.from_track_id == from_track_id,
            SetPairing.into_track_id == into_track_id,
        )
        .one_or_none()
    )


def upsert_pairing(
    db: Session,
    set_obj: Set,
    *,
    from_track_id: str,
    into_track_id: str,
    cue_in_sec: int | None,
    note: str | None,
    tags: list[str],
    increment_use_count: bool = False,
    commit: bool = True,
) -> tuple[SetPairing, bool]:
    """Create or update a transition pairing. Returns (row, created).

    ``commit=False`` flushes instead of committing so the call can take part in a
    larger transaction (e.g. one WrzDJSet agent turn that rolls back as a unit);
    the IntegrityError reconcile path only applies when this call owns the commit.
    """
    if from_track_id == into_track_id:
        raise ValueError("from_track_id and into_track_id must be different")
    existing = find_pairing(db, set_obj.id, from_track_id, into_track_id)
    if existing is not None:
        existing.cue_in_sec = cue_in_sec
        existing.note = note
        existing.tags_json = _tags_json(tags)
        if increment_use_count:
            existing.use_count += 1
        _persist(db, existing, commit)
        return existing, False

    pairing = SetPairing(
        set_id=set_obj.id,
        from_track_id=from_track_id,
        into_track_id=into_track_id,
        cue_in_sec=cue_in_sec,
        note=note,
        tags_json=_tags_json(tags),
        use_count=1 if increment_use_count else 0,
    )
    db.add(pairing)
    if not commit:
        # Surface a unique-constraint violation to the caller's transaction
        # rather than rolling back work the agent turn has not committed yet.
        db.flush()
        return pairing, True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_pairing(db, set_obj.id, from_track_id, into_track_id)
        if existing is None:
            raise
        existing.cue_in_sec = cue_in_sec
        existing.note = note
        existing.tags_json = _tags_json(tags)
        if increment_use_count:
            existing.use_count += 1
        db.commit()
        db.refresh(existing)
        return existing, False
    db.refresh(pairing)
    return pairing, True


def update_pairing(
    db: Session,
    pairing: SetPairing,
    *,
    cue_in_sec: int | None,
    note: str | None,
    tags: list[str],
) -> SetPairing:
    """Update editable pairing details."""
    pairing.cue_in_sec = cue_in_sec
    pairing.note = note
    pairing.tags_json = _tags_json(tags)
    db.commit()
    db.refresh(pairing)
    return pairing


def delete_pairing(db: Session, pairing: SetPairing, *, commit: bool = True) -> None:
    db.delete(pairing)
    if commit:
        db.commit()
    else:
        db.flush()


def pairing_view(db: Session, set_obj: Set, pairing: SetPairing) -> PairingView:
    """Build display data for one pairing without loading every set pairing."""
    return _attach_pool_tracks(db, set_obj.id, [pairing], "")[0]


def list_pairings(db: Session, set_obj: Set, query: str | None = None) -> list[PairingView]:
    """List pairings with optional pool-track display data."""
    term = (query or "").strip()
    rows = (
        db.query(SetPairing)
        .filter(SetPairing.set_id == set_obj.id)
        .order_by(SetPairing.updated_at.desc(), SetPairing.id.desc())
        .all()
    )
    return _attach_pool_tracks(db, set_obj.id, rows, term)


def _attach_pool_tracks(
    db: Session, set_id: int, rows: list[SetPairing], term: str
) -> list[PairingView]:
    track_ids = {p.from_track_id for p in rows} | {p.into_track_id for p in rows}
    pool_rows = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_id, SetPoolTrack.track_id.in_(track_ids))
        .all()
        if track_ids
        else []
    )
    by_track_id = {t.track_id: t for t in pool_rows if t.track_id}
    views = [
        PairingView(
            pairing=p,
            from_track=by_track_id.get(p.from_track_id),
            into_track=by_track_id.get(p.into_track_id),
        )
        for p in rows
    ]
    if not term:
        return views
    needle = term.lower()
    return [v for v in views if _view_matches(v, needle)]


def _view_matches(view: PairingView, needle: str) -> bool:
    haystacks = [
        view.pairing.from_track_id,
        view.pairing.into_track_id,
        view.pairing.note or "",
        " ".join(tags_for_pairing(view.pairing)),
    ]
    for track in [view.from_track, view.into_track]:
        if track is not None:
            haystacks.extend([track.title, track.artist, track.camelot or "", str(track.bpm or "")])
    return any(needle in h.lower() for h in haystacks)

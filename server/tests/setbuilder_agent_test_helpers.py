"""Shared fixtures for Pass 2 agent behavior tests."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User


def _mk_set_with_tracks(db: Session, user: User) -> Set:
    set_obj = Set(owner_id=user.id, name="Agent Set", target_duration_sec=7 * 60)
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.flush()
    tracks = [
        SetPoolTrack(
            set_id=set_obj.id,
            source_id=source.id,
            track_id=f"tidal:{idx}",
            title=f"Track {idx}",
            artist=f"Artist {idx}",
            bpm=124 + idx,
            key="8A",
            camelot="8A",
            energy=5 + idx,
            duration_sec=210,
            dedupe_sig=f"sig-{idx}",
        )
        for idx in range(3)
    ]
    db.add_all(tracks)
    db.flush()
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=0, track_id="tidal:0"),
            SetSlot(set_id=set_obj.id, position=1, track_id="tidal:1"),
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _mk_set_for_curve(db: Session, user: User, slot_count: int = 4) -> Set:
    """Set with ``slot_count`` slots seeded to a flat baseline target_energy."""
    set_obj = Set(owner_id=user.id, name="Curve Set", target_duration_sec=30 * 60)
    db.add(set_obj)
    db.flush()
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=idx, track_id=f"tidal:{idx}", target_energy=5.0)
            for idx in range(slot_count)
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _pool_track_by_track_id(set_obj: Set, track_id: str) -> SetPoolTrack:
    return next(t for t in set_obj.pool_tracks if t.track_id == track_id)

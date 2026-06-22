"""Tests for the connected-service import agent tools (#524, #442 Family 4a)."""

from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder import pool


def _mk_set(db: Session, user: User) -> Set:
    set_obj = Set(owner_id=user.id, name="Import Set")
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_import_candidates_commit_false_defers_persistence(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    source = set_obj.pool_sources[0]
    cands = [pool.PoolCandidate(title="A", artist="X"), pool.PoolCandidate(title="B", artist="Y")]

    added, deduped = pool.import_candidates(db, set_obj, source, cands, commit=False)
    assert (added, deduped) == (2, 0)
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 2
    db.rollback()
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 0

    # Default commit=True persists across a rollback.
    pool.import_candidates(db, set_obj, source, cands)
    db.rollback()
    assert db.query(SetPoolTrack).filter(SetPoolTrack.set_id == set_obj.id).count() == 2

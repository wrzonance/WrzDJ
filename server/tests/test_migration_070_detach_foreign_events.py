"""Data-migration test for revision 070.

Pins the sweep's invariant: a set whose owner is not the owner of its event
loses the binding; every other set is untouched. Runs the revision's
``upgrade()`` through Alembic's ``Operations`` on the same SQLite connection
the ``db`` fixture uses, so the seeded rows are the ones swept.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.set import Set
from app.models.user import User

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "070_detach_sets_from_foreign_events.py"
)


def _load_migration_070() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_070_detach", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_dj(db: Session, username: str) -> User:
    user = User(username=username, password_hash="x", role="dj")
    db.add(user)
    db.flush()
    return user


def test_sweep_detaches_only_sets_bound_to_foreign_events(db: Session, test_user, test_event):
    other = _make_dj(db, "otherdj")
    own_binding = Set(owner_id=test_user.id, name="own", event_id=test_event.id)
    foreign_binding = Set(owner_id=other.id, name="foreign", event_id=test_event.id)
    unbound = Set(owner_id=other.id, name="unbound", event_id=None)
    db.add_all([own_binding, foreign_binding, unbound])
    db.commit()

    connection = db.connection()
    with Operations.context(MigrationContext.configure(connection)):
        _load_migration_070().upgrade()
    db.expire_all()

    assert db.get(Set, own_binding.id).event_id == test_event.id
    assert db.get(Set, foreign_binding.id).event_id is None
    assert db.get(Set, unbound.id).event_id is None
    assert db.get(Event, test_event.id).created_by_user_id == test_user.id

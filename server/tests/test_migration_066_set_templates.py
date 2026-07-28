"""Migration round-trip test for ``set_templates`` (issue #407, revision 066).

Pins the boundary invariant: revision 066 upgrades cleanly, creates exactly
the columns/index the ``SetTemplate`` model expects, and downgrades cleanly
with no leftover state — repeatably (upgrade -> downgrade -> upgrade ->
downgrade never errors or drifts).

Exercises revision 066's ``upgrade()``/``downgrade()`` functions directly
against a throwaway SQLite connection via Alembic's ``Operations``/
``MigrationContext`` — independent of the full 68-revision chain, which CI
already exercises end-to-end against real Postgres via
``alembic upgrade head && alembic check`` (see CLAUDE.md). ``op.create_table``
/ ``op.create_index`` / ``op.drop_index`` / ``op.drop_table`` are dialect-
agnostic Core operations, so SQLite is a faithful substrate here, matching
the project's existing SQLite-in-memory test convention (conftest.py).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection

from app.models.set_template import SetTemplate

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "alembic" / "versions" / "066_add_set_templates.py"
)

_EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "name",
    "vibe_theme",
    "target_duration_sec",
    "avg_transition_overlap_sec",
    "bpm_floor",
    "bpm_ceiling",
    "key_strictness",
    "slots_json",
    "curve_points_json",
    "created_at",
    "updated_at",
}

_NOT_NULL_COLUMNS = {
    "id",
    "user_id",
    "name",
    "avg_transition_overlap_sec",
    "key_strictness",
    "slots_json",
    "curve_points_json",
    "created_at",
    "updated_at",
}


def _load_migration_066() -> ModuleType:
    """Import revision 066 by file path — its filename is not import-safe."""
    spec = importlib.util.spec_from_file_location("migration_066_set_templates", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration_066() -> ModuleType:
    return _load_migration_066()


@pytest.fixture
def alembic_connection():
    """A throwaway SQLite connection, isolated from the shared test schema."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        yield connection
    engine.dispose()


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _columns(connection: Connection, table_name: str) -> dict[str, dict]:
    return {col["name"]: col for col in inspect(connection).get_columns(table_name)}


def test_upgrade_creates_expected_table_columns_and_index(alembic_connection, migration_066):
    context = MigrationContext.configure(alembic_connection)
    with Operations.context(context):
        migration_066.upgrade()

    assert "set_templates" in _table_names(alembic_connection)
    assert set(_columns(alembic_connection, "set_templates")) == _EXPECTED_COLUMNS

    indexes = inspect(alembic_connection).get_indexes("set_templates")
    assert any(
        idx["name"] == "ix_set_templates_user_id" and idx["column_names"] == ["user_id"]
        for idx in indexes
    )


def test_upgrade_nullability_matches_the_model(alembic_connection, migration_066):
    context = MigrationContext.configure(alembic_connection)
    with Operations.context(context):
        migration_066.upgrade()

    columns = _columns(alembic_connection, "set_templates")
    for name in _NOT_NULL_COLUMNS:
        assert columns[name]["nullable"] is False, f"{name} should be NOT NULL"
    for name in _EXPECTED_COLUMNS - _NOT_NULL_COLUMNS:
        assert columns[name]["nullable"] is True, f"{name} should be nullable"


def test_upgrade_column_types_and_lengths_match_the_model(alembic_connection, migration_066):
    """Names + nullability alone leave the drift-prone properties unchecked:
    a ``String(50)`` silently widened to ``String(120)``, or an ``Integer``
    that became ``Float``, would pass those and still fail ``alembic check``.
    """
    context = MigrationContext.configure(alembic_connection)
    with Operations.context(context):
        migration_066.upgrade()

    migrated = _columns(alembic_connection, "set_templates")
    for column in SetTemplate.__table__.columns:
        actual = str(migrated[column.name]["type"]).upper()
        expected = str(column.type).upper()
        assert actual == expected, (
            f"{column.name}: migration has {actual}, model declares {expected}"
        )


def test_upgrade_server_defaults_and_cascade_fk_match_the_model(alembic_connection, migration_066):
    """``server_default`` and ``ON DELETE CASCADE`` are invisible to a
    name/nullability comparison but are exactly what a hand-written
    migration gets wrong."""
    context = MigrationContext.configure(alembic_connection)
    with Operations.context(context):
        migration_066.upgrade()

    migrated = _columns(alembic_connection, "set_templates")
    assert "8" in str(migrated["avg_transition_overlap_sec"]["default"])
    assert "0.2" in str(migrated["key_strictness"]["default"])

    fks = inspect(alembic_connection).get_foreign_keys("set_templates")
    assert len(fks) == 1, f"expected exactly one FK, got {fks}"
    fk = fks[0]
    assert fk["referred_table"] == "users"
    assert fk["referred_columns"] == ["id"]
    assert fk["constrained_columns"] == ["user_id"]
    assert (fk["options"].get("ondelete") or "").upper() == "CASCADE"


def test_downgrade_drops_table_and_index_cleanly(alembic_connection, migration_066):
    context = MigrationContext.configure(alembic_connection)
    with Operations.context(context):
        migration_066.upgrade()
        migration_066.downgrade()

    assert "set_templates" not in _table_names(alembic_connection)


def test_upgrade_downgrade_round_trips_repeatedly(alembic_connection, migration_066):
    """Applying upgrade/downgrade twice in a row must not error or drift —
    pins that neither leaves residue (e.g. a leaked index) that would break
    a second application."""
    context = MigrationContext.configure(alembic_connection)
    with Operations.context(context):
        migration_066.upgrade()
        migration_066.downgrade()
        migration_066.upgrade()
        second_pass_columns = set(_columns(alembic_connection, "set_templates"))
        migration_066.downgrade()

    assert second_pass_columns == _EXPECTED_COLUMNS
    assert "set_templates" not in _table_names(alembic_connection)

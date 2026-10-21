"""Behavior tests for data transforms hidden behind Alembic's loader."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.llm_connector import LlmConnector
from app.models.user import User

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load_revision(revision: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"migration_{revision}_backfill", _VERSIONS / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(module: ModuleType, connection) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def test_oauth_token_migration_encrypts_and_downgrade_restores_plaintext(
    db: Session, test_user: User, monkeypatch
):
    migration = _load_revision("018", "018_encrypt_oauth_tokens.py")
    db.execute(
        text(
            "UPDATE users SET tidal_access_token = :tidal_access, "
            "tidal_refresh_token = NULL, beatport_access_token = :beatport_access, "
            "beatport_refresh_token = :beatport_refresh WHERE id = :user_id"
        ),
        {
            "tidal_access": "tidal-access",
            "beatport_access": "beatport-access",
            "beatport_refresh": "beatport-refresh",
            "user_id": test_user.id,
        },
    )
    db.commit()

    monkeypatch.setattr(migration, "encrypt_value", lambda value: f"encrypted:{value}")
    monkeypatch.setattr(
        migration,
        "decrypt_value",
        lambda value: value.removeprefix("encrypted:"),
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        migration.upgrade()
        encrypted = db.execute(
            text(
                "SELECT tidal_access_token, tidal_refresh_token, beatport_access_token, "
                "beatport_refresh_token FROM users WHERE id = :user_id"
            ),
            {"user_id": test_user.id},
        ).one()
        assert encrypted == (
            "encrypted:tidal-access",
            None,
            "encrypted:beatport-access",
            "encrypted:beatport-refresh",
        )

        migration.downgrade()

    plaintext = db.execute(
        text(
            "SELECT tidal_access_token, tidal_refresh_token, beatport_access_token, "
            "beatport_refresh_token FROM users WHERE id = :user_id"
        ),
        {"user_id": test_user.id},
    ).one()
    assert plaintext == ("tidal-access", None, "beatport-access", "beatport-refresh")


def test_mru_default_backfill_picks_one_active_connector_per_user(
    db: Session, test_user: User, admin_user: User
):
    migration = _load_revision("049", "049_llm_connector_is_default.py")
    now = datetime.now(UTC).replace(tzinfo=None)
    older = LlmConnector(
        user_id=test_user.id,
        connector_type="anthropic_apikey",
        display_name="Older",
        credentials="{}",
        last_used_at=now - timedelta(days=1),
    )
    mru = LlmConnector(
        user_id=test_user.id,
        connector_type="anthropic_apikey",
        display_name="Most recent",
        credentials="{}",
        last_used_at=now,
    )
    preexisting_default = LlmConnector(
        user_id=admin_user.id,
        connector_type="anthropic_apikey",
        display_name="Already selected",
        credentials="{}",
        is_default=True,
    )
    another_admin_connector = LlmConnector(
        user_id=admin_user.id,
        connector_type="anthropic_apikey",
        display_name="Do not replace",
        credentials="{}",
        last_used_at=now,
    )
    db.add_all([older, mru, preexisting_default, another_admin_connector])
    db.commit()

    migration._backfill_mru_defaults(db.connection())
    db.expire_all()

    assert db.get(LlmConnector, older.id).is_default is False
    assert db.get(LlmConnector, mru.id).is_default is True
    assert db.get(LlmConnector, preexisting_default.id).is_default is True
    assert db.get(LlmConnector, another_admin_connector.id).is_default is False


def test_join_code_backfill_avoids_existing_codes(monkeypatch):
    migration = _load_revision("045", "045_add_event_join_code.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, code VARCHAR(10) NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO events (id, code) VALUES (1, 'COLLIDE')")
        connection.exec_driver_sql("INSERT INTO events (id, code) VALUES (2, 'OTHER01')")
        candidates = iter(["COLLIDE", "JOIN01", "JOIN02"])
        monkeypatch.setattr(migration, "_generate_code", lambda: next(candidates))
        # SQLite cannot alter an existing column's nullability in place; this
        # test targets the collision-safe data backfill, while PG migration CI
        # validates the final NOT NULL constraint and unique index.
        with monkeypatch.context() as patch:
            patch.setattr(migration.op, "alter_column", lambda *args, **kwargs: None)
            patch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)
            _upgrade(migration, connection)

        rows = connection.execute(text("SELECT code, join_code FROM events ORDER BY id")).all()
        assert rows == [("COLLIDE", "JOIN01"), ("OTHER01", "JOIN02")]
    engine.dispose()


def test_acceptance_migration_backfills_only_accepted_request_statuses():
    migration = _load_revision("061", "061_add_request_accepted_at.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE requests (id INTEGER PRIMARY KEY, status VARCHAR(20), "
            "updated_at DATETIME)"
        )
        connection.exec_driver_sql(
            "INSERT INTO requests VALUES (1, 'accepted', '2026-01-01 10:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO requests VALUES (2, 'playing', '2026-01-02 10:00:00')"
        )
        connection.exec_driver_sql("INSERT INTO requests VALUES (3, 'new', '2026-01-03 10:00:00')")

        _upgrade(migration, connection)

        rows = connection.execute(text("SELECT id, accepted_at FROM requests ORDER BY id")).all()
        assert rows == [
            (1, "2026-01-01 10:00:00"),
            (2, "2026-01-02 10:00:00"),
            (3, None),
        ]
    engine.dispose()


def test_pool_enrichment_backfill_marks_complete_and_partial_rows():
    migration = _load_revision("064", "064_add_pool_track_enrichment_status.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            'CREATE TABLE set_pool_tracks (id INTEGER PRIMARY KEY, bpm INTEGER, "key" VARCHAR, '
            "genre VARCHAR, duration_sec INTEGER)"
        )
        connection.exec_driver_sql(
            "INSERT INTO set_pool_tracks VALUES (1, 120, '8A', 'house', 240)"
        )
        connection.exec_driver_sql(
            "INSERT INTO set_pool_tracks VALUES (2, 120, NULL, 'house', 240)"
        )

        _upgrade(migration, connection)

        rows = connection.execute(
            text("SELECT id, enrichment_status FROM set_pool_tracks ORDER BY id")
        ).all()
        assert rows == [(1, "enriched"), (2, "failed")]
    engine.dispose()


def test_apple_music_export_recovery_backfill_marks_only_pending_sets():
    migration = _load_revision("073", "073_set_apple_music_export_recovery.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE sets (id INTEGER PRIMARY KEY, apple_music_export_pending BOOLEAN)"
        )
        connection.exec_driver_sql("INSERT INTO sets VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO sets VALUES (2, 0)")

        _upgrade(migration, connection)

        rows = connection.execute(
            text("SELECT id, apple_music_export_uncertain FROM sets ORDER BY id")
        ).all()
        assert rows == [(1, 1), (2, 0)]
    engine.dispose()


def test_beatport_oauth_migration_clears_abandoned_plaintext_state():
    migration = _load_revision("027", "027_encrypt_beatport_oauth_state.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, beatport_oauth_state VARCHAR(64), "
            "beatport_oauth_code_verifier VARCHAR(128))"
        )
        connection.exec_driver_sql("INSERT INTO users VALUES (1, 'state', 'verifier')")

        _upgrade(migration, connection)

        assert connection.execute(
            text(
                "SELECT beatport_oauth_state, beatport_oauth_code_verifier FROM users WHERE id = 1"
            )
        ).one() == (None, None)
        columns = {row[1]: row[2] for row in connection.exec_driver_sql("PRAGMA table_info(users)")}
        assert columns["beatport_oauth_state"] == "TEXT"
        assert columns["beatport_oauth_code_verifier"] == "TEXT"
    engine.dispose()


def test_listenbrainz_migration_expires_existing_artist_cache_rows():
    migration = _load_revision("031", "031_add_lb_columns_expire_mb_cache.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE mb_artist_cache (id INTEGER PRIMARY KEY, created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO mb_artist_cache VALUES (1, '2026-01-01 10:00:00')")
        connection.exec_driver_sql("INSERT INTO mb_artist_cache VALUES (2, '2026-02-01 10:00:00')")

        _upgrade(migration, connection)

        rows = connection.execute(
            text(
                "SELECT id, created_at, lb_listen_count, lb_user_count "
                "FROM mb_artist_cache ORDER BY id"
            )
        ).all()
        assert rows == [
            (1, "2000-01-01T00:00:00", None, None),
            (2, "2000-01-01T00:00:00", None, None),
        ]
    engine.dispose()


def test_initial_admin_migration_promotes_first_user_and_seeds_settings():
    migration = _load_revision("007", "007_add_user_role_and_settings.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (10)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (20)")

        _upgrade(migration, connection)

        roles = connection.execute(text("SELECT id, role FROM users ORDER BY id")).all()
        assert roles == [(10, "admin"), (20, "dj")]
        assert connection.execute(
            text(
                "SELECT id, registration_enabled, search_rate_limit_per_minute FROM system_settings"
            )
        ).all() == [(1, 1, 30)]
    engine.dispose()


def test_org_connector_migration_rescopes_only_the_migrated_default(monkeypatch):
    migration = _load_revision("056", "056_org_llm_connector.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT)")
        connection.exec_driver_sql(
            "CREATE TABLE llm_connectors (id INTEGER PRIMARY KEY, scope TEXT, user_id INTEGER, "
            "display_name TEXT, is_default BOOLEAN)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE system_settings (id INTEGER PRIMARY KEY, llm_model TEXT, "
            "llm_default_connector_id INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE llm_audit_event (id INTEGER, actor_user_id INTEGER)"
        )
        connection.exec_driver_sql("INSERT INTO users VALUES (1, 'admin')")
        connection.exec_driver_sql(
            "INSERT INTO llm_connectors VALUES (10, 'user', 1, "
            "'Org Default (migrated from env var)', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO llm_connectors VALUES (11, 'user', 1, 'Personal', 1)"
        )
        connection.exec_driver_sql("INSERT INTO system_settings VALUES (1, 'legacy', 10)")

        # The data branch runs after schema changes; SQLite cannot perform the
        # production PostgreSQL ALTER/CHECK operations, so keep those outside
        # this focused seeded-row regression.
        with monkeypatch.context() as patch:
            for name in ("add_column", "alter_column", "drop_column", "create_check_constraint"):
                patch.setattr(migration.op, name, lambda *args, **kwargs: None)
            _upgrade(migration, connection)
            connection.execute(
                text("UPDATE system_settings SET llm_default_connector_id = 11 WHERE id = 1")
            )
            _upgrade(migration, connection)

        rows = connection.execute(
            text("SELECT id, scope, user_id, is_default FROM llm_connectors ORDER BY id")
        ).all()
        assert rows == [(10, "org", None, 0), (11, "user", 1, 1)]
        defaults = connection.execute(
            text("SELECT id, llm_default_connector_id FROM system_settings ORDER BY id")
        ).all()
        assert defaults == [(1, None)]
    engine.dispose()

"""Data-migration tests for revision 047's environment-key migration."""

import importlib.util
import warnings
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.system_settings import SystemSettings

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "alembic" / "versions" / "047_admin_ai_oauth.py"
)


def _load_migration_047() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_047_anthropic", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_moves_env_key_to_admin_connector_once(db: Session, admin_user, monkeypatch):
    migration = _load_migration_047()
    db.add(SystemSettings(id=1))
    db.commit()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-key")
    monkeypatch.setattr(
        migration,
        "encrypt_value",
        lambda value: f"encrypted:{value}",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with Operations.context(MigrationContext.configure(db.connection())):
            migration._migrate_env_var_anthropic_key()
            migration._migrate_env_var_anthropic_key()

    connector = db.execute(
        text(
            "SELECT user_id, connector_type, display_name, status, credentials, model_hint, "
            "created_at, updated_at "
            "FROM llm_connectors"
        )
    ).one()
    assert connector.user_id == admin_user.id
    assert connector.connector_type == "anthropic_apikey"
    assert connector.display_name == "Org Default (migrated from env var)"
    assert connector.status == "active"
    assert connector.credentials == 'encrypted:{"api_key": "secret-key"}'
    assert connector.model_hint
    assert connector.created_at == connector.updated_at

    setting = db.execute(
        text("SELECT llm_default_connector_id FROM system_settings WHERE id = 1")
    ).one()
    assert setting.llm_default_connector_id is not None

    audit = db.execute(
        text("SELECT actor_user_id, target_connector_id, event_type FROM llm_audit_event")
    ).one()
    assert audit.actor_user_id == admin_user.id
    assert audit.target_connector_id == setting.llm_default_connector_id
    assert audit.event_type == "connector_created"

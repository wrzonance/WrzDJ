"""Org-scoped connector storage + resolution tests (org-llm-connector spec)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.llm_connector import SCOPE_ORG, SCOPE_USER, STATUS_ACTIVE
from app.services.llm.connector_storage import (
    CreateConnectorPayload,
    create_connector,
    get_user_label,
    list_connectors_for_user,
    list_org_connectors,
)


def _payload(name: str = "Org Key") -> CreateConnectorPayload:
    return CreateConnectorPayload(
        connector_type="anthropic_apikey",
        display_name=name,
        credentials={"api_key": "sk-ant-test-0000000000000000"},
        base_url_plain=None,
        model_hint=None,
    )


def test_create_org_connector_has_null_user_and_org_scope(db):
    row = create_connector(db, user_id=None, payload=_payload(), scope=SCOPE_ORG)
    db.commit()
    assert row.user_id is None
    assert row.scope == SCOPE_ORG
    assert row.status == STATUS_ACTIVE
    # Credentials encrypted at rest: raw column value must not contain the key.
    raw = db.execute(
        text("SELECT credentials FROM llm_connectors WHERE id = :i"), {"i": row.id}
    ).scalar()
    assert "sk-ant-test" not in (raw or "")


def test_create_user_connector_defaults_to_user_scope(db, test_user):
    row = create_connector(db, user_id=test_user.id, payload=_payload("Mine"))
    db.commit()
    assert row.scope == SCOPE_USER
    assert row.user_id == test_user.id


def test_list_org_connectors_excludes_user_rows(db, test_user):
    create_connector(db, user_id=test_user.id, payload=_payload("Mine"))
    org = create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)
    db.commit()
    rows = list_org_connectors(db)
    assert [r.id for r in rows] == [org.id]


def test_list_connectors_for_user_excludes_org_rows(db, test_user):
    mine = create_connector(db, user_id=test_user.id, payload=_payload("Mine"))
    create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)
    db.commit()
    rows = list_connectors_for_user(db, test_user.id)
    assert [r.id for r in rows] == [mine.id]


def test_create_org_connector_rejects_duplicate_label(db):
    create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)
    db.commit()
    with pytest.raises(ValueError, match="already exists"):
        create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)


def test_get_user_label_for_org_rows(db):
    assert get_user_label(db, None) == "Organization"

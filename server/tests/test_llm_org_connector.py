"""Org-scoped connector storage + resolution tests (org-llm-connector spec)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.llm_connector import SCOPE_ORG, SCOPE_USER, STATUS_ACTIVE, LlmConnector
from app.services.llm.connector_storage import (
    CreateConnectorPayload,
    audit_event,
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


# ---------- admin API surface: org-scope policy + NULL-actor handling ----------


def _mk_user_connector(db, user_id, name="Personal"):
    row = LlmConnector(
        user_id=user_id,
        connector_type="anthropic_apikey",
        display_name=name,
        status="active",
        credentials="{}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_org_connector(db, name="House"):
    row = LlmConnector(
        user_id=None,
        scope=SCOPE_ORG,
        connector_type="anthropic_apikey",
        display_name=name,
        status="active",
        credentials="{}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_policy_rejects_user_scoped_default(client, admin_headers, db, test_user):
    personal = _mk_user_connector(db, test_user.id)
    resp = client.patch(
        "/api/admin/llm/policy",
        json={"llm_default_connector_id": personal.id},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "org-scoped" in resp.json()["detail"]


def test_policy_accepts_org_scoped_default(client, admin_headers, db):
    org = _mk_org_connector(db)
    resp = client.patch(
        "/api/admin/llm/policy",
        json={"llm_default_connector_id": org.id},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["llm_default_connector_id"] == org.id


def test_admin_connector_list_labels_org_rows(client, admin_headers, db):
    _mk_org_connector(db, name="House Key")
    resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
    assert resp.status_code == 200
    org_rows = [r for r in resp.json() if r["display_name"] == "House Key"]
    assert org_rows and org_rows[0]["dj_username"] == "Organization"
    assert org_rows[0]["user_id"] is None
    assert org_rows[0]["scope"] == "org"


def test_audit_browse_handles_null_actor(client, admin_headers, db):
    org = _mk_org_connector(db)
    audit_event(
        db, actor_user_id=None, target_connector_id=org.id, event_type="auth_invalid_observed"
    )
    db.commit()
    resp = client.get("/api/admin/llm/audit", headers=admin_headers)
    assert resp.status_code == 200
    rows = [r for r in resp.json()["rows"] if r["target_connector_id"] == org.id]
    assert rows and rows[0]["actor_user_id"] is None
    assert rows[0]["actor_username"] == "system"


def test_audit_csv_handles_null_actor(client, admin_headers, db):
    org = _mk_org_connector(db)
    audit_event(
        db, actor_user_id=None, target_connector_id=org.id, event_type="auth_invalid_observed"
    )
    db.commit()
    resp = client.get("/api/admin/llm/audit.csv", headers=admin_headers)
    assert resp.status_code == 200
    assert "system" in resp.text
    assert "user#None" not in resp.text


def test_create_org_connector_allows_same_label_different_type(db):
    # Carried review item: the duplicate guard must key on (type, label), not label alone.
    create_connector(db, user_id=None, payload=_payload("House"), scope=SCOPE_ORG)
    db.commit()
    payload2 = CreateConnectorPayload(
        connector_type="openai_apikey",
        display_name="House",
        credentials={"api_key": "sk-test-0000000000000000"},
        base_url_plain=None,
        model_hint=None,
    )
    row = create_connector(db, user_id=None, payload=payload2, scope=SCOPE_ORG)
    db.commit()
    assert row.id is not None

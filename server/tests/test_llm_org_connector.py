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
from app.services.system_settings import get_system_settings


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
    import csv
    import io

    org = _mk_org_connector(db)
    audit_event(
        db, actor_user_id=None, target_connector_id=org.id, event_type="auth_invalid_observed"
    )
    db.commit()
    resp = client.get("/api/admin/llm/audit.csv", headers=admin_headers)
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == [
        "timestamp",
        "actor",
        "actor_user_id",
        "event_type",
        "target_connector",
        "notes",
    ]
    system_rows = [r for r in rows[1:] if r[1] == "system"]
    assert system_rows, resp.text
    # NULL-actor system rows carry an empty actor_user_id cell, so a DJ
    # literally named "system" (who would have a numeric id) can't be confused.
    assert all(r[2] == "" for r in system_rows)
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


# ---------- admin API surface: org connector CRUD ----------

# Known-valid anthropic_apikey body (mirrors tests/test_llm_api.py fixtures —
# Anthropic keys must start "sk-ant-" and clear the minimum length check).
_ORG_CREATE_BODY = {
    "connector_type": "anthropic_apikey",
    "display_name": "House Claude",
    "api_key": "sk-ant-1234567890abcdef1234567890abcdef1234567890",
    "model_hint": "claude-haiku-4-5-20251001",
}


def test_org_crud_requires_admin(client, auth_headers):
    assert client.get("/api/admin/llm/org-connectors", headers=auth_headers).status_code == 403


def test_org_connector_create_list_delete(client, admin_headers):
    create = client.post(
        "/api/admin/llm/org-connectors",
        json=_ORG_CREATE_BODY,
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["user_id"] is None
    assert body["scope"] == "org"
    # Credentials never returned
    assert "credentials" not in body
    assert "api_key" not in body
    cid = body["id"]

    listed = client.get("/api/admin/llm/org-connectors", headers=admin_headers)
    assert [r["id"] for r in listed.json()] == [cid]

    deleted = client.delete(f"/api/admin/llm/org-connectors/{cid}", headers=admin_headers)
    assert deleted.status_code == 204
    assert client.get("/api/admin/llm/org-connectors", headers=admin_headers).json() == []


def test_org_connector_create_rejects_bad_key_format(client, admin_headers):
    resp = client.post(
        "/api/admin/llm/org-connectors",
        json={**_ORG_CREATE_BODY, "api_key": "not-a-valid-key"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_org_connector_create_rejects_duplicate_label(client, admin_headers):
    first = client.post(
        "/api/admin/llm/org-connectors", json=_ORG_CREATE_BODY, headers=admin_headers
    )
    assert first.status_code == 201, first.text
    dup = client.post("/api/admin/llm/org-connectors", json=_ORG_CREATE_BODY, headers=admin_headers)
    assert dup.status_code == 400
    assert "already exists" in dup.json()["detail"]


def test_org_connector_delete_clears_default(client, admin_headers, db):
    org = _mk_org_connector(db, name="House D")
    client.patch(
        "/api/admin/llm/policy",
        json={"llm_default_connector_id": org.id},
        headers=admin_headers,
    )
    client.delete(f"/api/admin/llm/org-connectors/{org.id}", headers=admin_headers)
    policy = client.get("/api/admin/llm/policy", headers=admin_headers).json()
    assert policy["llm_default_connector_id"] is None


def test_org_connector_rotate(client, admin_headers, db):
    org = _mk_org_connector(db, name="House R")
    resp = client.put(
        f"/api/admin/llm/org-connectors/{org.id}/credentials",
        json={"api_key": "sk-ant-rotated7890abcdef1234567890abcdef1234567890"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "org"
    assert "credentials" not in body
    # Audit row written for the rotation
    rows = db.execute(
        text("SELECT event_type FROM llm_audit_event WHERE target_connector_id = :i"),
        {"i": org.id},
    ).all()
    assert ("connector_credentials_rotated",) in rows


def test_org_connector_rotate_invalid_key_returns_400(client, admin_headers, db):
    org = _mk_org_connector(db, name="House RB")
    resp = client.put(
        f"/api/admin/llm/org-connectors/{org.id}/credentials",
        json={"api_key": "bad"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_org_connector_test_endpoint(client, admin_headers, db):
    from unittest.mock import AsyncMock, patch

    org = _mk_org_connector(db, name="House T")
    with patch(
        "app.services.llm.adapters.anthropic_apikey.AnthropicApiKeyAdapter.health_check",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post(f"/api/admin/llm/org-connectors/{org.id}/test", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_org_endpoints_404_for_user_scoped_rows(client, admin_headers, db, test_user):
    personal = _mk_user_connector(db, test_user.id)
    assert (
        client.delete(
            f"/api/admin/llm/org-connectors/{personal.id}", headers=admin_headers
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/admin/llm/org-connectors/{personal.id}/credentials",
            json={"api_key": "sk-ant-rotated7890abcdef1234567890abcdef1234567890"},
            headers=admin_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/admin/llm/org-connectors/{personal.id}/test", headers=admin_headers
        ).status_code
        == 404
    )


# ---------- legacy Anthropic env-var surface removal ----------


def test_ai_settings_no_longer_exposes_api_key_or_model(client, admin_headers):
    resp = client.get("/api/admin/ai/settings", headers=admin_headers)
    assert resp.status_code == 200
    assert set(resp.json()) == {"llm_enabled", "llm_rate_limit_per_minute"}


def test_ai_models_endpoint_removed(client, admin_headers):
    assert client.get("/api/admin/ai/models", headers=admin_headers).status_code == 404


# ---------- per-DJ effective-source admin endpoint + DJ-visible fallback flag ----------


def test_dj_status_reports_effective_source(client, admin_headers, db, test_user):
    org = _mk_org_connector(db, name="House S")
    settings = get_system_settings(db)
    settings.llm_enabled = True
    settings.llm_default_connector_id = org.id
    db.commit()

    resp = client.get("/api/admin/llm/dj-status", headers=admin_headers)
    assert resp.status_code == 200
    by_name = {r["username"]: r["effective_source"] for r in resp.json()["rows"]}
    assert by_name[test_user.username] == "org_fallback"

    own = _mk_user_connector(db, test_user.id, name="Own S")
    by_name = {
        r["username"]: r["effective_source"]
        for r in client.get("/api/admin/llm/dj-status", headers=admin_headers).json()["rows"]
    }
    assert by_name[test_user.username] == "own"

    # A non-active connector must not count as "own" — back to the org fallback.
    own.status = "disabled"
    db.commit()
    by_name = {
        r["username"]: r["effective_source"]
        for r in client.get("/api/admin/llm/dj-status", headers=admin_headers).json()["rows"]
    }
    assert by_name[test_user.username] == "org_fallback"


def test_dj_status_excludes_deactivated_users(client, admin_headers, db, test_user):
    test_user.is_active = False
    db.commit()
    rows = client.get("/api/admin/llm/dj-status", headers=admin_headers).json()["rows"]
    assert test_user.username not in {r["username"] for r in rows}


def test_dj_status_none_when_fallback_disabled(client, admin_headers, db, test_user):
    org = _mk_org_connector(db, name="House S2")
    settings = get_system_settings(db)
    settings.llm_enabled = False
    settings.llm_default_connector_id = org.id
    db.commit()
    rows = client.get("/api/admin/llm/dj-status", headers=admin_headers).json()["rows"]
    by_name = {r["username"]: r["effective_source"] for r in rows}
    assert by_name[test_user.username] == "none"


def test_dj_status_requires_admin(client, auth_headers):
    assert client.get("/api/admin/llm/dj-status", headers=auth_headers).status_code == 403


def test_dj_policy_exposes_org_fallback_available(client, auth_headers, db):
    resp = client.get("/api/llm/policy", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["org_fallback_available"] is False

    org = _mk_org_connector(db, name="House P")
    settings = get_system_settings(db)
    settings.llm_enabled = True
    settings.llm_default_connector_id = org.id
    db.commit()
    assert (
        client.get("/api/llm/policy", headers=auth_headers).json()["org_fallback_available"] is True
    )

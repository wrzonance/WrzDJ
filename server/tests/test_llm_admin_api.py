"""Admin LLM connector API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.models.llm_connector import LlmAuditEvent, LlmConnector


class TestAdminLlm:
    def test_get_policy(self, client: TestClient, admin_headers):
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_apikey_connectors_enabled" in data
        assert "llm_compatible_connector_enabled" in data

    def test_patch_policy_toggles(self, client: TestClient, admin_headers):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={
                "llm_apikey_connectors_enabled": False,
                "llm_compatible_connector_enabled": False,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_apikey_connectors_enabled"] is False
        assert data["llm_compatible_connector_enabled"] is False

    def test_non_admin_cannot_get_policy(self, client: TestClient, auth_headers):
        resp = client.get("/api/admin/llm/policy", headers=auth_headers)
        assert resp.status_code == 403

    def test_patch_policy_rejects_clear_default_with_id(self, client: TestClient, admin_headers):
        # clear_default and a non-null default id are contradictory.
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"clear_default": True, "llm_default_connector_id": 1},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_policy_exposes_retention_default(self, client: TestClient, admin_headers):
        # Issue #342: retention is surfaced via the policy endpoint and defaults to 30.
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["llm_call_log_retention_days"] == 30

    def test_patch_retention_persists(self, client: TestClient, admin_headers, db):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_call_log_retention_days": 90},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["llm_call_log_retention_days"] == 90

        # Persisted to the DB-backed singleton, visible on a fresh GET.
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.json()["llm_call_log_retention_days"] == 90

        from app.services.system_settings import get_system_settings

        assert get_system_settings(db).llm_call_log_retention_days == 90

    def test_patch_retention_below_min_rejected(self, client: TestClient, admin_headers):
        # Sanity bound: minimum 7 days. Rejected at the API level (422).
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_call_log_retention_days": 6},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_patch_retention_above_max_rejected(self, client: TestClient, admin_headers):
        # Sanity bound: maximum 365 days. Rejected at the API level (422).
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_call_log_retention_days": 366},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_patch_retention_accepts_boundaries(self, client: TestClient, admin_headers):
        for value in (7, 365):
            resp = client.patch(
                "/api/admin/llm/policy",
                json={"llm_call_log_retention_days": value},
                headers=admin_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["llm_call_log_retention_days"] == value

    def test_list_connectors_admin_shows_all(
        self, client: TestClient, admin_headers, db, test_user
    ):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
        assert resp.status_code == 200
        users = [r["dj_username"] for r in resp.json()]
        assert "testuser" in users

    def test_force_revoke_clears_default(self, client: TestClient, admin_headers, db, test_user):
        # The system default must be org-scoped (user_id=NULL) — the policy
        # endpoint rejects user-scoped rows.
        row = LlmConnector(
            user_id=None,
            scope="org",
            connector_type="openai_apikey",
            display_name="House",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Set as default
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_default_connector_id": row.id},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        # Revoke
        resp = client.post(f"/api/admin/llm/connectors/{row.id}/revoke", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

        # Default cleared
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.json()["llm_default_connector_id"] is None

        # Audit recorded
        assert (
            db.query(LlmAuditEvent)
            .filter(LlmAuditEvent.event_type == "connector_revoked_by_admin")
            .count()
            == 1
        )

    def test_usage_endpoint(self, client: TestClient, admin_headers, db, test_user):
        # Seed a connector and a call log row
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        from app.services.llm.connector_storage import log_call

        log_call(
            db,
            connector_id=row.id,
            purpose="recommendation",
            status="ok",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
        )
        db.commit()

        resp = client.get("/api/admin/llm/usage?days=30", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["days"] == 30
        assert any(r["connector_id"] == row.id for r in data["rows"])

    def test_usage_endpoint_skips_connector_with_unsupported_persisted_type(
        self, client: TestClient, admin_headers, db, test_user
    ):
        # Regression for baseline 57cfcdc6867f: an unconstrained DB value must not crash the API.
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="unrecognized_provider",
            display_name="Unknown connector",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        from app.services.llm.connector_storage import log_call

        log_call(
            db,
            connector_id=row.id,
            purpose="recommendation",
            status="ok",
            latency_ms=10,
        )
        db.commit()

        response = client.get("/api/admin/llm/usage?days=30", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["rows"] == []

    # ---------- Monthly token cap (issue #339) ----------

    def test_connectors_listing_includes_cap_and_usage(
        self, client: TestClient, admin_headers, db, test_user
    ):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Capped",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
            monthly_token_cap=1000,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        from app.services.llm.connector_storage import log_call

        log_call(
            db,
            connector_id=row.id,
            purpose="recommendation",
            status="ok",
            latency_ms=10,
            tokens_in=120,
            tokens_out=80,
        )
        db.commit()

        resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
        assert resp.status_code == 200
        listed = next(r for r in resp.json() if r["id"] == row.id)
        assert listed["monthly_token_cap"] == 1000
        assert listed["current_month_tokens"] == 200

    def test_set_connector_cap(self, client: TestClient, admin_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="C",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": 50000},
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_token_cap"] == 50000

        # Clearing it (null) returns it to unlimited.
        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": None},
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_token_cap"] is None

        # Audit row written (reuses policy_changed event type).
        assert (
            db.query(LlmAuditEvent)
            .filter(
                LlmAuditEvent.event_type == "policy_changed",
                LlmAuditEvent.target_connector_id == row.id,
            )
            .count()
            == 2
        )

    def test_set_cap_zero_allowed(self, client: TestClient, admin_headers, db, test_user):
        # 0 is a valid cap meaning "no further calls this month".
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Zero",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_token_cap"] == 0

    def test_set_cap_rejects_negative(self, client: TestClient, admin_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Neg",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": -5},
        )
        assert resp.status_code == 422  # Pydantic ge=0 rejection

    def test_set_cap_rejects_empty_body(self, client: TestClient, admin_headers, db, test_user):
        # monthly_token_cap is required: an empty {} body must be rejected (422),
        # not silently treated as null — otherwise an accidental no-field PATCH
        # would wipe a configured cap (CodeRabbit #377).
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="EmptyBody",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
            monthly_token_cap=1000,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={},
        )
        assert resp.status_code == 422
        # The cap must be untouched by the rejected request.
        db.refresh(row)
        assert row.monthly_token_cap == 1000

    def test_set_cap_404_for_missing_connector(self, client: TestClient, admin_headers):
        resp = client.patch(
            "/api/admin/llm/connectors/999999/cap",
            headers=admin_headers,
            json={"monthly_token_cap": 100},
        )
        assert resp.status_code == 404

    def test_set_cap_requires_admin(self, client: TestClient, auth_headers, db, test_user):
        # A non-admin (plain DJ) must be rejected even for their own connector.
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="C3",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=auth_headers,
            json={"monthly_token_cap": 100},
        )
        assert resp.status_code == 403

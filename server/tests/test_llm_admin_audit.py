"""Tests for the admin LLM audit-trail browse + CSV export endpoints (#341).

Exercises:
- GET /api/admin/llm/audit — paginated, filterable JSON browse
- GET /api/admin/llm/audit.csv — filtered CSV export
- admin-only auth guard
- joined actor username + target connector display name
- never leaks credential material
"""

from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import LlmAuditEvent, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash


def _make_dj(db: Session, username: str) -> User:
    user = User(
        username=username,
        password_hash=get_password_hash("password123456"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(db: Session, *, user_id: int, display_name: str) -> LlmConnector:
    row = LlmConnector(
        user_id=user_id,
        connector_type="openai_apikey",
        display_name=display_name,
        status="active",
        credentials=json.dumps({"api_key": "sk-secret-should-never-leak"}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_audit(
    db: Session,
    *,
    actor_user_id: int,
    target_connector_id: int | None,
    event_type: str,
) -> LlmAuditEvent:
    row = LlmAuditEvent(
        actor_user_id=actor_user_id,
        target_connector_id=target_connector_id,
        event_type=event_type,
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestAuditBrowse:
    def test_requires_admin(self, client: TestClient, auth_headers):
        resp = client.get("/api/admin/llm/audit", headers=auth_headers)
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient):
        resp = client.get("/api/admin/llm/audit")
        assert resp.status_code == 401

    def test_empty_list(self, client: TestClient, admin_headers):
        resp = client.get("/api/admin/llm/audit", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["rows"] == []
        assert data["total"] == 0

    def test_lists_events_with_joined_labels(
        self, client: TestClient, admin_headers, db, test_user
    ):
        conn = _make_connector(db, user_id=test_user.id, display_name="My OpenAI")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )

        resp = client.get("/api/admin/llm/audit", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        row = data["rows"][0]
        assert row["event_type"] == "connector_created"
        assert row["actor_username"] == "testuser"
        assert row["target_connector_display_name"] == "My OpenAI"
        assert row["target_connector_id"] == conn.id

    def test_never_leaks_credentials(self, client: TestClient, admin_headers, db, test_user):
        conn = _make_connector(db, user_id=test_user.id, display_name="My OpenAI")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        resp = client.get("/api/admin/llm/audit", headers=admin_headers)
        assert "sk-secret-should-never-leak" not in resp.text
        assert "credentials" not in resp.text

    def test_filter_by_event_type(self, client: TestClient, admin_headers, db, test_user):
        conn = _make_connector(db, user_id=test_user.id, display_name="C")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_credentials_rotated",
        )
        resp = client.get(
            "/api/admin/llm/audit?event_type=connector_credentials_rotated",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["rows"][0]["event_type"] == "connector_credentials_rotated"

    def test_filter_by_actor(self, client: TestClient, admin_headers, db, test_user):
        other = _make_dj(db, "otherdj")
        conn = _make_connector(db, user_id=test_user.id, display_name="C")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        _make_audit(
            db,
            actor_user_id=other.id,
            target_connector_id=conn.id,
            event_type="connector_revoked_by_admin",
        )
        resp = client.get(f"/api/admin/llm/audit?actor_user_id={other.id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["rows"][0]["actor_username"] == "otherdj"

    def test_filter_by_target_connector(self, client: TestClient, admin_headers, db, test_user):
        conn_a = _make_connector(db, user_id=test_user.id, display_name="A")
        conn_b = _make_connector(db, user_id=test_user.id, display_name="B")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn_a.id,
            event_type="connector_created",
        )
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn_b.id,
            event_type="connector_created",
        )
        resp = client.get(
            f"/api/admin/llm/audit?target_connector_id={conn_b.id}", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["rows"][0]["target_connector_id"] == conn_b.id

    def test_pagination(self, client: TestClient, admin_headers, db, test_user):
        conn = _make_connector(db, user_id=test_user.id, display_name="C")
        for _ in range(5):
            _make_audit(
                db,
                actor_user_id=test_user.id,
                target_connector_id=conn.id,
                event_type="connector_created",
            )
        resp = client.get("/api/admin/llm/audit?limit=2&offset=0", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["rows"]) == 2

        resp2 = client.get("/api/admin/llm/audit?limit=2&offset=4", headers=admin_headers)
        assert len(resp2.json()["rows"]) == 1

    def test_invalid_limit_rejected(self, client: TestClient, admin_headers):
        resp = client.get("/api/admin/llm/audit?limit=0", headers=admin_headers)
        assert resp.status_code == 422
        resp = client.get("/api/admin/llm/audit?limit=9999", headers=admin_headers)
        assert resp.status_code == 422

    def test_null_target_connector_renders(self, client: TestClient, admin_headers, db, test_user):
        # policy_changed events may have a null target connector
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=None,
            event_type="policy_changed",
        )
        resp = client.get("/api/admin/llm/audit", headers=admin_headers)
        assert resp.status_code == 200
        row = resp.json()["rows"][0]
        assert row["target_connector_id"] is None
        assert row["target_connector_display_name"] is None


class TestAuditCsvExport:
    def test_requires_admin(self, client: TestClient, auth_headers):
        resp = client.get("/api/admin/llm/audit.csv", headers=auth_headers)
        assert resp.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient):
        resp = client.get("/api/admin/llm/audit.csv")
        assert resp.status_code == 401

    def test_csv_content_type_and_rows(self, client: TestClient, admin_headers, db, test_user):
        conn = _make_connector(db, user_id=test_user.id, display_name="My OpenAI")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        resp = client.get("/api/admin/llm/audit.csv", headers=admin_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")

        reader = list(csv.reader(io.StringIO(resp.text)))
        header = reader[0]
        assert header == ["timestamp", "actor", "event_type", "target_connector", "notes"]
        assert any("connector_created" in r for r in reader[1:])
        assert any("My OpenAI" in r for r in reader[1:])
        assert any("testuser" in r for r in reader[1:])

    def test_csv_honors_event_type_filter(self, client: TestClient, admin_headers, db, test_user):
        conn = _make_connector(db, user_id=test_user.id, display_name="C")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_deleted",
        )
        resp = client.get(
            "/api/admin/llm/audit.csv?event_type=connector_deleted", headers=admin_headers
        )
        assert resp.status_code == 200
        body = resp.text
        assert "connector_deleted" in body
        assert "connector_created" not in body

    def test_csv_never_leaks_credentials(self, client: TestClient, admin_headers, db, test_user):
        conn = _make_connector(db, user_id=test_user.id, display_name="My OpenAI")
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        resp = client.get("/api/admin/llm/audit.csv", headers=admin_headers)
        assert "sk-secret-should-never-leak" not in resp.text

    def test_csv_neutralizes_formula_injection(
        self, client: TestClient, admin_headers, db, test_user
    ):
        # A connector display name that starts with "=" would execute as a
        # spreadsheet formula if written verbatim into the CSV.
        conn = _make_connector(db, user_id=test_user.id, display_name='=HYPERLINK("http://evil")')
        _make_audit(
            db,
            actor_user_id=test_user.id,
            target_connector_id=conn.id,
            event_type="connector_created",
        )
        resp = client.get("/api/admin/llm/audit.csv", headers=admin_headers)
        assert resp.status_code == 200

        rows = list(csv.reader(io.StringIO(resp.text)))
        target_cells = [cell for row in rows[1:] for cell in row if "HYPERLINK" in cell]
        assert target_cells, "expected the injected display name to be present"
        # Every cell carrying the payload must be defanged with a leading quote
        # so spreadsheet apps treat it as literal text, not a formula.
        for cell in target_cells:
            assert cell.startswith("'="), cell

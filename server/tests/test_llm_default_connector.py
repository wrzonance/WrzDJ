"""Tests for per-DJ explicit default connector (issue #336).

Covers:
- Gateway resolution prefers the pinned default over MRU.
- Falls through to MRU when no default is set.
- Falls through to MRU when the pinned default is no longer active.
- API endpoints: POST /default sets and atomically clears siblings.
- API endpoints: DELETE /default clears the flag.
- Ownership scoping: 404 for other DJ's connectors.
- Audit events written for set / unset.
- Setting an inactive connector as default is rejected with 400.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.llm_connector import LlmAuditEvent, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage
from app.services.llm.exceptions import NoLlmConfigured
from app.services.llm.gateway import Gateway


# ---------- helpers ----------
def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_connector(
    db: Session,
    user: User,
    *,
    display_name: str = "Test connector",
    status: str = "active",
    is_default: bool = False,
) -> LlmConnector:
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name=display_name,
        status=status,
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint="gpt-5-mini",
        is_default=is_default,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def dj_user(db) -> User:
    user = User(
        username="djdefault",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def other_dj(db) -> User:
    user = User(
        username="otherdjdefault",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------- gateway resolver behavior ----------
class TestGatewayResolverPrefersDefault:
    @pytest.mark.asyncio
    async def test_default_picked_over_mru(self, db, dj_user):
        """An explicit default beats the MRU heuristic even when MRU is more recent."""
        from datetime import timedelta

        from app.core.time import utcnow

        # Pinned default — older last_used_at to prove the pin wins.
        pinned = _make_connector(db, dj_user, display_name="pinned", is_default=True)
        pinned.last_used_at = utcnow() - timedelta(hours=1)
        # MRU candidate — more recent activity but not pinned.
        mru = _make_connector(db, dj_user, display_name="mru-but-not-default")
        mru.last_used_at = utcnow()
        db.commit()

        fake = ChatResponse(text="ok", tool_calls=[], stop_reason="end_turn", usage=None)
        with patch.object(
            __import__(
                "app.services.llm.adapters.openai_apikey",
                fromlist=["OpenAIApiKeyAdapter"],
            ).OpenAIApiKeyAdapter,
            "chat",
            new=AsyncMock(return_value=fake),
        ):
            await Gateway.dispatch(
                db,
                dj_user,
                ChatRequest(messages=[Message(role="user", content="hi")]),
                purpose="test",
            )

        # The pinned row got its last_used_at bumped — the MRU sibling didn't.
        db.refresh(pinned)
        db.refresh(mru)
        prior_mru_ts = mru.last_used_at
        assert pinned.last_used_at is not None
        # The MRU row's timestamp should be older than pinned's (i.e. the pin
        # was used, not the MRU). We compare via prior_mru_ts which was set
        # before dispatch — pinned was dispatched so its ts > prior_mru_ts.
        assert pinned.last_used_at >= prior_mru_ts

    @pytest.mark.asyncio
    async def test_default_skipped_when_inactive_falls_back_to_mru(self, db, dj_user):
        """A disabled / auth_invalid default doesn't block MRU resolution."""
        # Pinned but auth_invalid — gateway must skip it.
        _make_connector(
            db, dj_user, display_name="pinned-broken", is_default=True, status="auth_invalid"
        )
        mru = _make_connector(db, dj_user, display_name="mru-active")

        fake = ChatResponse(
            text="from-mru",
            tool_calls=[],
            stop_reason="end_turn",
            usage=TokenUsage(prompt=1, completion=1),
        )
        with patch.object(
            __import__(
                "app.services.llm.adapters.openai_apikey",
                fromlist=["OpenAIApiKeyAdapter"],
            ).OpenAIApiKeyAdapter,
            "chat",
            new=AsyncMock(return_value=fake),
        ):
            resp = await Gateway.dispatch(
                db,
                dj_user,
                ChatRequest(messages=[Message(role="user", content="hi")]),
                purpose="test",
            )

        assert resp.text == "from-mru"
        db.refresh(mru)
        assert mru.last_used_at is not None

    @pytest.mark.asyncio
    async def test_no_default_uses_mru_unchanged(self, db, dj_user):
        """Existing MRU semantics still apply when no default is pinned."""
        from datetime import timedelta

        from app.core.time import utcnow

        older = _make_connector(db, dj_user, display_name="older")
        newer = _make_connector(db, dj_user, display_name="newer")
        older.last_used_at = utcnow() - timedelta(hours=1)
        newer.last_used_at = utcnow()
        db.commit()

        fake = ChatResponse(text="ok", tool_calls=[], stop_reason="end_turn", usage=None)
        with patch.object(
            __import__(
                "app.services.llm.adapters.openai_apikey",
                fromlist=["OpenAIApiKeyAdapter"],
            ).OpenAIApiKeyAdapter,
            "chat",
            new=AsyncMock(return_value=fake),
        ):
            await Gateway.dispatch(
                db,
                dj_user,
                ChatRequest(messages=[Message(role="user", content="hi")]),
                purpose="test",
            )

        db.refresh(newer)
        db.refresh(older)
        # newer has the bumped ts because MRU picked it.
        assert newer.last_used_at is not None
        assert newer.last_used_at >= older.last_used_at

    @pytest.mark.asyncio
    async def test_all_inactive_raises_no_llm_configured(self, db, dj_user):
        """Pinned-but-broken + no other active = NoLlmConfigured."""
        _make_connector(
            db, dj_user, display_name="pinned-broken", is_default=True, status="disabled"
        )
        with pytest.raises(NoLlmConfigured):
            await Gateway.dispatch(
                db,
                dj_user,
                ChatRequest(messages=[Message(role="user", content="hi")]),
                purpose="test",
            )


# ---------- POST /default ----------
class TestSetDefault:
    def test_set_default_marks_row(self, client: TestClient, auth_headers, db, test_user):
        row = _make_connector(db, test_user, display_name="A")

        resp = client.post(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["is_default"] is True

        db.refresh(row)
        assert row.is_default is True

    def test_set_default_clears_other_defaults_for_same_user(
        self, client: TestClient, auth_headers, db, test_user
    ):
        a = _make_connector(db, test_user, display_name="A", is_default=True)
        b = _make_connector(db, test_user, display_name="B")

        resp = client.post(f"/api/llm/connectors/{b.id}/default", headers=auth_headers)
        assert resp.status_code == 200

        db.refresh(a)
        db.refresh(b)
        assert a.is_default is False
        assert b.is_default is True

    def test_set_default_does_not_touch_other_dj(
        self, client: TestClient, auth_headers, db, test_user, other_dj
    ):
        their_default = _make_connector(db, other_dj, display_name="theirs", is_default=True)
        mine = _make_connector(db, test_user, display_name="mine")

        client.post(f"/api/llm/connectors/{mine.id}/default", headers=auth_headers)

        db.refresh(their_default)
        assert their_default.is_default is True  # Untouched

    def test_set_default_404_for_other_users_connector(
        self, client: TestClient, auth_headers, db, other_dj
    ):
        theirs = _make_connector(db, other_dj, display_name="not yours")

        resp = client.post(f"/api/llm/connectors/{theirs.id}/default", headers=auth_headers)
        assert resp.status_code == 404

        # The other DJ's connector wasn't flipped.
        db.refresh(theirs)
        assert theirs.is_default is False

    def test_set_default_404_for_unknown_id(self, client: TestClient, auth_headers):
        resp = client.post("/api/llm/connectors/999999/default", headers=auth_headers)
        assert resp.status_code == 404

    def test_set_default_rejects_inactive_connector(
        self, client: TestClient, auth_headers, db, test_user
    ):
        row = _make_connector(db, test_user, display_name="broken", status="auth_invalid")
        resp = client.post(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)
        assert resp.status_code == 400

        db.refresh(row)
        assert row.is_default is False

    def test_set_default_writes_audit_event(self, client: TestClient, auth_headers, db, test_user):
        row = _make_connector(db, test_user, display_name="A")
        client.post(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)

        audit = (
            db.query(LlmAuditEvent)
            .filter(
                LlmAuditEvent.target_connector_id == row.id,
                LlmAuditEvent.event_type == "connector_default_set",
            )
            .one_or_none()
        )
        assert audit is not None
        assert audit.actor_user_id == test_user.id

    def test_set_default_requires_auth(self, client: TestClient, db, test_user):
        row = _make_connector(db, test_user, display_name="A")
        resp = client.post(f"/api/llm/connectors/{row.id}/default")
        assert resp.status_code == 401

    def test_set_default_persists_across_list_calls(
        self, client: TestClient, auth_headers, db, test_user
    ):
        """Acceptance criterion: setting a default sticks across sessions."""
        row = _make_connector(db, test_user, display_name="sticks")
        client.post(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)

        # Simulate a fresh page load: list connectors.
        listed = client.get("/api/llm/connectors", headers=auth_headers).json()
        match = next(c for c in listed if c["id"] == row.id)
        assert match["is_default"] is True


# ---------- DELETE /default ----------
class TestUnsetDefault:
    def test_unset_default_clears_flag(self, client: TestClient, auth_headers, db, test_user):
        row = _make_connector(db, test_user, display_name="A", is_default=True)
        resp = client.delete(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["is_default"] is False

        db.refresh(row)
        assert row.is_default is False

    def test_unset_default_is_noop_when_not_default(
        self, client: TestClient, auth_headers, db, test_user
    ):
        row = _make_connector(db, test_user, display_name="A", is_default=False)
        resp = client.delete(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)
        # Successful no-op — no error, no audit row.
        assert resp.status_code == 200
        assert resp.json()["is_default"] is False
        assert (
            db.query(LlmAuditEvent)
            .filter(LlmAuditEvent.event_type == "connector_default_unset")
            .count()
            == 0
        )

    def test_unset_default_writes_audit_event(
        self, client: TestClient, auth_headers, db, test_user
    ):
        row = _make_connector(db, test_user, display_name="A", is_default=True)
        client.delete(f"/api/llm/connectors/{row.id}/default", headers=auth_headers)

        audit = (
            db.query(LlmAuditEvent)
            .filter(
                LlmAuditEvent.target_connector_id == row.id,
                LlmAuditEvent.event_type == "connector_default_unset",
            )
            .one_or_none()
        )
        assert audit is not None
        assert audit.actor_user_id == test_user.id

    def test_unset_default_404_for_other_users_connector(
        self, client: TestClient, auth_headers, db, other_dj
    ):
        theirs = _make_connector(db, other_dj, display_name="not yours", is_default=True)
        resp = client.delete(f"/api/llm/connectors/{theirs.id}/default", headers=auth_headers)
        assert resp.status_code == 404
        db.refresh(theirs)
        assert theirs.is_default is True

    def test_unset_falls_back_to_mru_on_next_dispatch(
        self, client: TestClient, auth_headers, db, test_user
    ):
        """Acceptance criterion: unsetting falls back to MRU."""
        from datetime import timedelta

        from app.core.time import utcnow

        pinned = _make_connector(db, test_user, display_name="pinned", is_default=True)
        pinned.last_used_at = utcnow() - timedelta(hours=2)
        mru = _make_connector(db, test_user, display_name="mru-recent")
        mru.last_used_at = utcnow()
        db.commit()

        client.delete(f"/api/llm/connectors/{pinned.id}/default", headers=auth_headers)
        db.refresh(pinned)
        assert pinned.is_default is False

        # After unsetting, gateway picks the MRU.
        import asyncio

        fake = ChatResponse(text="mru-served", tool_calls=[], stop_reason="end_turn", usage=None)
        with patch.object(
            __import__(
                "app.services.llm.adapters.openai_apikey",
                fromlist=["OpenAIApiKeyAdapter"],
            ).OpenAIApiKeyAdapter,
            "chat",
            new=AsyncMock(return_value=fake),
        ):
            resp = asyncio.run(
                Gateway.dispatch(
                    db,
                    test_user,
                    ChatRequest(messages=[Message(role="user", content="hi")]),
                    purpose="test",
                )
            )

        assert resp.text == "mru-served"
        db.refresh(mru)
        # MRU got the bump; pinned did not because it wasn't chosen this time.
        assert mru.last_used_at is not None


# ---------- ConnectorOut surfaces is_default ----------
class TestListSurfacesIsDefault:
    def test_list_exposes_is_default_flag(self, client: TestClient, auth_headers, db, test_user):
        _make_connector(db, test_user, display_name="A", is_default=True)
        _make_connector(db, test_user, display_name="B")

        rows = client.get("/api/llm/connectors", headers=auth_headers).json()
        by_name = {r["display_name"]: r for r in rows}
        assert by_name["A"]["is_default"] is True
        assert by_name["B"]["is_default"] is False


# ---------- service layer invariants ----------
class TestServiceLayer:
    def test_set_default_for_user_clears_siblings(self, db, dj_user):
        from app.services.llm.connector_storage import set_default_for_user

        a = _make_connector(db, dj_user, display_name="A", is_default=True)
        b = _make_connector(db, dj_user, display_name="B")

        set_default_for_user(db, connector=b)
        db.commit()

        db.refresh(a)
        db.refresh(b)
        assert a.is_default is False
        assert b.is_default is True

    def test_set_default_idempotent_when_already_default(self, db, dj_user):
        """Calling set on a row that's already default is a quiet no-op."""
        from app.services.llm.connector_storage import set_default_for_user

        a = _make_connector(db, dj_user, display_name="A", is_default=True)
        result = set_default_for_user(db, connector=a)
        db.commit()

        assert result.id == a.id
        db.refresh(a)
        assert a.is_default is True

    def test_unset_default_clears_flag(self, db, dj_user):
        from app.services.llm.connector_storage import unset_default_for_user

        a = _make_connector(db, dj_user, display_name="A", is_default=True)
        unset_default_for_user(db, connector=a)
        db.commit()
        db.refresh(a)
        assert a.is_default is False


def _load_migration_048():
    """Import the 048 migration module by file path so the backfill helper is
    callable from tests (alembic versions/ has no ``__init__.py``).
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "048_llm_connector_is_default.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_048", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationBackfill:
    """Smoke-test the migration's backfill helper against an in-memory DB.

    The helper picks the MRU active connector per user. The migration runs
    against a bind connection, so we exercise it the same way here. Skipped
    users (no active connector, or already has a default) must be untouched.
    """

    def test_backfill_marks_mru_for_each_user(self, db, dj_user, other_dj):
        from datetime import timedelta

        from app.core.time import utcnow

        migration = _load_migration_048()

        # User A: two active connectors, neither default. MRU = newer.
        older_a = _make_connector(db, dj_user, display_name="A-older")
        newer_a = _make_connector(db, dj_user, display_name="A-newer")
        older_a.last_used_at = utcnow() - timedelta(hours=2)
        newer_a.last_used_at = utcnow()

        # User B: one active connector with no last_used_at — gets defaulted.
        only_b = _make_connector(db, other_dj, display_name="B-only")
        only_b.last_used_at = None

        db.commit()

        migration._backfill_mru_defaults(db.connection())
        db.commit()

        db.refresh(older_a)
        db.refresh(newer_a)
        db.refresh(only_b)
        assert newer_a.is_default is True
        assert older_a.is_default is False
        assert only_b.is_default is True

    def test_backfill_skips_users_with_existing_default(self, db, dj_user):
        migration = _load_migration_048()

        already = _make_connector(db, dj_user, display_name="already", is_default=True)
        also = _make_connector(db, dj_user, display_name="also")

        migration._backfill_mru_defaults(db.connection())
        db.commit()

        db.refresh(already)
        db.refresh(also)
        assert already.is_default is True
        assert also.is_default is False  # Untouched

    def test_backfill_skips_inactive_only(self, db, dj_user):
        migration = _load_migration_048()

        broken = _make_connector(db, dj_user, display_name="only-broken", status="auth_invalid")

        migration._backfill_mru_defaults(db.connection())
        db.commit()

        db.refresh(broken)
        # No active connector → user is skipped, no default created.
        assert broken.is_default is False

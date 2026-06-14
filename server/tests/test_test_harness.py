"""Regression tests for backend pytest harness behavior."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app, no_background_lifespan
from app.models.user import User
from app.services.auth import decode_token
from tests.conftest import DIRECT_SESSIONLOCAL_MODULES, _auth_headers_for_user


def test_db_fixture_uses_external_transaction(db: Session):
    """The harness should bind each Session to a transaction-owned Connection."""
    bind = db.get_bind()
    assert hasattr(bind, "in_transaction")
    assert bind.in_transaction() is True
    assert db.join_transaction_mode == "create_savepoint"


def test_committed_rows_are_visible_within_current_test(db: Session):
    user = User(username="transaction_probe", password_hash="x", role="dj")
    db.add(user)
    db.commit()

    assert db.query(User).filter(User.username == "transaction_probe").count() == 1


def test_committed_rows_are_rolled_back_between_tests(db: Session):
    assert db.query(User).filter(User.username == "transaction_probe").count() == 0


def test_no_background_test_client_skips_lifespan_tasks():
    with (
        patch("app.main._tidal_collection_poll_loop") as tidal_loop,
        patch("app.main._llm_call_log_cleanup_loop") as cleanup_loop,
        patch("app.services.llm.health_monitor.health_monitor_loop") as health_loop,
    ):
        test_app = create_app(lifespan_context=no_background_lifespan)
        with TestClient(test_app) as client:
            assert client.get("/health").status_code == 200

    tidal_loop.assert_not_called()
    cleanup_loop.assert_not_called()
    health_loop.assert_not_called()


def test_real_lifespan_starts_and_cancels_background_tasks():
    async def neverending():
        import asyncio

        await asyncio.Event().wait()

    with (
        patch("app.main._tidal_collection_poll_loop", side_effect=neverending) as tidal_loop,
        patch("app.main._llm_call_log_cleanup_loop", side_effect=neverending) as cleanup_loop,
        patch(
            "app.services.llm.health_monitor.health_monitor_loop", side_effect=neverending
        ) as health_loop,
    ):
        real_app = create_app()
        with TestClient(real_app) as client:
            assert client.get("/health").status_code == 200

    tidal_loop.assert_called_once()
    cleanup_loop.assert_called_once()
    health_loop.assert_called_once()


def test_auth_headers_for_user_builds_valid_token(test_user: User):
    headers = _auth_headers_for_user(test_user)
    token = headers["Authorization"].removeprefix("Bearer ")

    token_data = decode_token(token)

    assert token_data is not None
    assert token_data.username == "testuser"
    assert token_data.token_version == test_user.token_version


def test_direct_sessionlocal_module_aliases_are_registered():
    module_names = {module.__name__ for module in DIRECT_SESSIONLOCAL_MODULES}

    assert "app.api.sse" in module_names

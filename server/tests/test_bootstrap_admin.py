from types import SimpleNamespace
from unittest.mock import Mock

from app.models.user import User
from app.scripts import bootstrap


def test_bootstrap_creates_first_admin_with_configured_credentials(db, monkeypatch):
    monkeypatch.setattr(
        bootstrap,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_admin_username="initial-admin",
            bootstrap_admin_password="strong-test-password",
        ),
    )
    monkeypatch.setattr(bootstrap, "SessionLocal", lambda: db)

    bootstrap.bootstrap_admin()

    admin = db.query(User).filter(User.username == "initial-admin").one()
    assert admin.role == "admin"


def test_bootstrap_does_not_promote_existing_user(db, monkeypatch, test_user):
    monkeypatch.setattr(
        bootstrap,
        "get_settings",
        lambda: SimpleNamespace(
            bootstrap_admin_username="initial-admin",
            bootstrap_admin_password="strong-test-password",
        ),
    )
    monkeypatch.setattr(bootstrap, "SessionLocal", lambda: db)

    bootstrap.bootstrap_admin()

    assert db.query(User).count() == 1
    assert db.query(User).filter(User.id == test_user.id).one().role == "dj"
    assert db.query(User).filter(User.username == "initial-admin").first() is None


def test_bootstrap_skips_without_credentials(monkeypatch):
    session_factory = Mock()
    monkeypatch.setattr(
        bootstrap,
        "get_settings",
        lambda: SimpleNamespace(bootstrap_admin_username=None, bootstrap_admin_password=None),
    )
    monkeypatch.setattr(bootstrap, "SessionLocal", session_factory)

    bootstrap.bootstrap_admin()

    session_factory.assert_not_called()

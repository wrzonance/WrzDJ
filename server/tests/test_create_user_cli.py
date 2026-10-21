import sys

from app.models.user import User
from app.scripts import create_user


def test_cli_creates_user_and_closes_session(db, monkeypatch, capsys):
    monkeypatch.setattr(create_user, "SessionLocal", lambda: db)
    monkeypatch.setattr(sys, "argv", ["create_user", "--username", "new-dj", "--password", "pw"])

    assert create_user.main() == 0

    created = db.query(User).filter(User.username == "new-dj").one()
    assert created.role == "dj"
    assert f"Created user 'new-dj' with ID {created.id}\n" == capsys.readouterr().out


def test_cli_refuses_duplicate_username_and_closes_session(db, monkeypatch, test_user, capsys):
    monkeypatch.setattr(create_user, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        sys,
        "argv",
        ["create_user", "--username", test_user.username, "--password", "pw"],
    )

    assert create_user.main() == 1

    assert db.query(User).count() == 1
    assert capsys.readouterr().out == f"User '{test_user.username}' already exists.\n"

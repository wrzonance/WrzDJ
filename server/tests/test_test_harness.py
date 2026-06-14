"""Regression tests for backend pytest harness behavior."""

from sqlalchemy.orm import Session

from app.models.user import User


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

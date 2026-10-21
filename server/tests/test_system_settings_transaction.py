"""System settings transaction ownership regressions."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.services.system_settings import get_system_settings


def test_creating_default_settings_does_not_commit_callers_pending_work(tmp_path):
    # Regression for baseline 57cfcdc6867f: the getter committed unrelated caller work.
    engine = create_engine(f"sqlite:///{tmp_path / 'system-settings-transaction.db'}")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            pending_user = User(
                username="not-yet-committed",
                password_hash="test-hash",
                role="dj",
            )
            db.add(pending_user)

            settings = get_system_settings(db)

            assert settings.id == 1
            assert settings.registration_enabled is True
            db.rollback()

        with sessions() as verification:
            assert verification.query(User).filter_by(username="not-yet-committed").count() == 0
            assert verification.query(SystemSettings).count() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

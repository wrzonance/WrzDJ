from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.user import User
from app.services.providers.tidal import get_tidal_session


@patch("tidalapi.Session")
def test_token_refresh_commits_only_oauth_fields(mock_session_cls, tmp_path, caplog):
    engine = create_engine(f"sqlite:///{tmp_path / 'tidal-refresh.db'}")
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        with sessions() as db:
            user = User(
                username="tidal-refresh-user",
                password_hash="test-hash",
                role="dj",
                tidal_access_token="expired-access",
                tidal_refresh_token="refresh-token",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = user.id
            user.username = "caller change that must remain pending"

            session = MagicMock()
            session.check_login.return_value = False
            session.token_refresh.return_value = True
            session.access_token = "refreshed-access"
            session.refresh_token = "refreshed-refresh"
            session.expiry_time = datetime.now(UTC) + timedelta(hours=1)
            mock_session_cls.return_value = session

            assert get_tidal_session(db, user) is session
            assert "Tidal token refreshed" in caplog.text
            assert str(user_id) not in caplog.text
            db.rollback()

        with sessions() as verify_db:
            persisted = verify_db.get(User, user_id)
            assert persisted is not None
            assert persisted.username == "tidal-refresh-user"
            assert persisted.tidal_access_token == "refreshed-access"
            assert persisted.tidal_refresh_token == "refreshed-refresh"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

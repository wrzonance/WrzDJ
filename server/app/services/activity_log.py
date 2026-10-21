"""Activity log service — lightweight event logging for bridge events, sync errors, etc."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)


def log_activity(
    db: Session,
    level: str,
    source: str,
    message: str,
    event_code: str | None = None,
    user_id: int | None = None,
) -> ActivityLog:
    """Create an activity log entry."""
    entry = ActivityLog(
        created_at=datetime.now(UTC),
        level=level,
        source=source,
        message=message,
        event_code=event_code,
        user_id=user_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_activity_in_fresh_session(
    level: str,
    source: str,
    message: str,
    event_code: str | None = None,
    user_id: int | None = None,
) -> ActivityLog:
    """Persist activity in an isolated session, separate from caller work."""
    from app.db.session import SessionLocal

    with SessionLocal() as activity_db:
        return log_activity(
            activity_db,
            level,
            source,
            message,
            event_code=event_code,
            user_id=user_id,
        )


def get_recent_activity(
    db: Session,
    limit: int = 50,
    event_code: str | None = None,
    user_id: int | None = None,
) -> list[ActivityLog]:
    """Get recent activity log entries, newest first."""
    query = db.query(ActivityLog)
    if event_code is not None:
        query = query.filter(ActivityLog.event_code == event_code)
    if user_id is not None:
        query = query.filter(ActivityLog.user_id == user_id)
    return query.order_by(ActivityLog.created_at.desc()).limit(limit).all()

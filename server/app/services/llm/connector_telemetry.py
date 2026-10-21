"""Call telemetry and audit persistence for LLM connectors."""

from datetime import datetime, timedelta

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import LlmAuditEvent, LlmCallLog
from app.models.user import User


def audit_event(
    db: Session,
    *,
    actor_user_id: int | None,
    target_connector_id: int | None,
    event_type: str,
) -> LlmAuditEvent:
    row = LlmAuditEvent(
        actor_user_id=actor_user_id,
        target_connector_id=target_connector_id,
        event_type=event_type,
    )
    db.add(row)
    db.flush()
    return row


def log_call(
    db: Session,
    *,
    connector_id: int,
    purpose: str,
    status: str,
    latency_ms: int,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    error_code: str | None = None,
) -> LlmCallLog:
    row = LlmCallLog(
        connector_id=connector_id,
        purpose=purpose,
        status=status,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        error_code=error_code,
    )
    db.add(row)
    db.flush()
    return row


def purge_call_log_older_than(db: Session, *, retention_days: int) -> int:
    """Delete old call logs, leaving transaction ownership to the caller."""
    if not 7 <= retention_days <= 365:
        raise ValueError("retention_days must be between 7 and 365")
    cutoff = utcnow() - timedelta(days=retention_days)
    result = db.execute(delete(LlmCallLog).where(LlmCallLog.created_at < cutoff))
    return result.rowcount or 0


def get_user_label(db: Session, user_id: int | None) -> str:
    if user_id is None:
        return "Organization"
    user = db.get(User, user_id)
    return user.username if user else f"user#{user_id}"


def owner_label(user_id: int | None, usernames: dict[int, str]) -> str:
    """Return a display label using a preloaded username map."""
    if user_id is None:
        return "Organization"
    return usernames.get(user_id) or f"user#{user_id}"


def get_usage_stats(db: Session, *, days: int = 30) -> list[dict]:
    """Aggregate per-connector call and token totals for the admin Usage card."""
    cutoff = utcnow() - timedelta(days=days)
    stmt = (
        select(
            LlmCallLog.connector_id,
            func.count(LlmCallLog.id).label("total_calls"),
            func.coalesce(func.sum(LlmCallLog.tokens_in), 0).label("total_tokens_in"),
            func.coalesce(func.sum(LlmCallLog.tokens_out), 0).label("total_tokens_out"),
            func.sum(case((LlmCallLog.status != "ok", 1), else_=0)).label("error_count"),
        )
        .where(LlmCallLog.created_at >= cutoff)
        .group_by(LlmCallLog.connector_id)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "connector_id": int(row.connector_id),
            "total_calls": int(row.total_calls or 0),
            "total_tokens_in": int(row.total_tokens_in or 0),
            "total_tokens_out": int(row.total_tokens_out or 0),
            "error_count": int(row.error_count or 0),
        }
        for row in rows
    ]


def _calendar_month_start() -> datetime:
    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def current_month_token_usage(db: Session, connector_id: int) -> int:
    """Sum current-month input and output tokens for one connector."""
    month_start = _calendar_month_start()
    total = db.execute(
        select(
            func.coalesce(func.sum(LlmCallLog.tokens_in), 0)
            + func.coalesce(func.sum(LlmCallLog.tokens_out), 0)
        ).where(
            LlmCallLog.connector_id == connector_id,
            LlmCallLog.created_at >= month_start,
        )
    ).scalar_one()
    return int(total or 0)


def current_month_token_usage_bulk(db: Session, connector_ids: list[int]) -> dict[int, int]:
    """Sum current-month tokens for multiple connectors in one grouped query."""
    if not connector_ids:
        return {}
    month_start = _calendar_month_start()
    rows = db.execute(
        select(
            LlmCallLog.connector_id,
            (
                func.coalesce(func.sum(LlmCallLog.tokens_in), 0)
                + func.coalesce(func.sum(LlmCallLog.tokens_out), 0)
            ).label("total"),
        )
        .where(
            LlmCallLog.connector_id.in_(connector_ids),
            LlmCallLog.created_at >= month_start,
        )
        .group_by(LlmCallLog.connector_id)
    ).all()
    return {int(row.connector_id): int(row.total or 0) for row in rows}

"""Persistence operations for per-user LLM connector feature pins."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.llm_feature_preference import LlmFeaturePreference


def get_feature_preferences_for_user(db: Session, user_id: int) -> list[LlmFeaturePreference]:
    """Return all of a DJ's per-feature connector pins."""
    return (
        db.query(LlmFeaturePreference)
        .filter(LlmFeaturePreference.user_id == user_id)
        .order_by(LlmFeaturePreference.feature.asc())
        .all()
    )


def get_feature_preference(
    db: Session, *, user_id: int, feature: str
) -> LlmFeaturePreference | None:
    """Return the DJ's pin for ``feature``, or ``None`` if unset."""
    return (
        db.query(LlmFeaturePreference)
        .filter(
            LlmFeaturePreference.user_id == user_id,
            LlmFeaturePreference.feature == feature,
        )
        .one_or_none()
    )


def set_feature_preference(
    db: Session, *, user_id: int, feature: str, connector_id: int
) -> LlmFeaturePreference:
    """Upsert a DJ's connector pin; the caller owns the transaction commit."""
    table = LlmFeaturePreference.__table__
    dialect = db.bind.dialect.name if db.bind is not None else ""
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    statement = insert_fn(table).values(user_id=user_id, feature=feature, connector_id=connector_id)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.user_id, table.c.feature],
        set_={"connector_id": connector_id},
    )
    db.execute(statement)
    db.flush()
    row = get_feature_preference(db, user_id=user_id, feature=feature)
    if row is None:  # pragma: no cover - the upsert guarantees the row exists
        raise RuntimeError("feature preference upsert did not persist a row")
    # The SQL upsert bypasses ORM state synchronization; refresh only this row.
    db.refresh(row)
    return row


def clear_feature_preference(db: Session, *, user_id: int, feature: str) -> bool:
    """Delete a DJ's pin and report whether one existed; the caller commits."""
    existing = get_feature_preference(db, user_id=user_id, feature=feature)
    if existing is None:
        return False
    db.delete(existing)
    db.flush()
    return True

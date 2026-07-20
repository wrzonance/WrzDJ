"""Read-time SetBuilder taste-profile reset markers (#409)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class SetTasteProfileReset(Base):
    """Owner-scoped marker; older vibe overrides are ignored for profile training."""

    __tablename__ = "set_taste_profile_resets"
    __table_args__ = (Index("ix_set_taste_profile_resets_user_reset_at", "user_id", "reset_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reset_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

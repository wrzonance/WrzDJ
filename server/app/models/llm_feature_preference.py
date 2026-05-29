"""Per-feature connector preference — pins a DJ's connector to a feature.

A DJ can pin the recommendation engine to one connector and the set-builder
to another. The gateway consults this table first (keyed by ``purpose``)
before falling back to the per-DJ default / MRU / org-default chain.

See issue #337, spec §11.8.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Allowlist of feature keys a DJ may pin. These mirror the gateway ``purpose``
# strings. ``recommendation`` is the only purpose dispatched today;
# ``set_builder`` is reserved for the upcoming set-builder feature (issue spec
# §11.8). Validation of API input against this set lives in ``schemas/llm.py``
# (the ``FeatureKey`` Literal must stay in sync — guarded by a test).
KNOWN_FEATURES = frozenset({"recommendation", "set_builder"})


class LlmFeaturePreference(Base):
    """Maps ``(user_id, feature)`` to a pinned ``connector_id``.

    At most one row per ``(user_id, feature)`` — enforced by a UNIQUE
    constraint. Deleting the connector cascades (ON DELETE CASCADE) so a stale
    preference never points at a missing connector.
    """

    __tablename__ = "llm_feature_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    feature: Mapped[str] = mapped_column(String(40), nullable=False)
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("llm_connectors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "feature", name="uq_llm_feature_pref_user_feature"),
    )

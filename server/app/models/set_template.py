"""Per-DJ reusable SetBuilder templates (issue #407).

A template snapshots a source Set's target settings plus its slot skeleton
(position/locked/target_energy/notes, no track assignments) and energy curve
as JSON. ``slots_json`` / ``curve_points_json`` are always a valid JSON list
string (``"[]"`` for none) — encode/decode helpers live in
``services/setbuilder/set_templates.py``. Only this application writes these
columns, so the decoded dicts are trusted rather than re-validated on read,
matching the ``SetCurveTemplate`` precedent (#389). Decoded curve points are
still shaped by ``SetTemplateCurvePointModel`` on the way out, because the
API returns them; slots are only counted, never emitted.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class SetTemplate(Base):
    __tablename__ = "set_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vibe_theme: Mapped[str | None] = mapped_column(String(50), nullable=True)

    target_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_transition_overlap_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    bpm_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm_ceiling: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0.0 ignore Camelot ... 1.0 strict +/-1 (matches Set.key_strictness)
    key_strictness: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.2, server_default="0.2"
    )

    slots_json: Mapped[str] = mapped_column(Text, nullable=False)
    curve_points_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

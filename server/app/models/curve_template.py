"""Per-DJ reusable energy-curve templates (#389).

A template is a normalized point list (t in [0,1], e in [0,10]) stored as a
JSON string in ``points_json``. Built-in templates live in code
(``services/setbuilder/curve.py``); only user-created templates persist here.
Validation of the point shape happens at the API boundary (Pydantic).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class SetCurveTemplate(Base):
    __tablename__ = "set_curve_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    points_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

"""Persisted WrzDJSet agent chat sessions and messages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base


class SetAgentSession(Base):
    __tablename__ = "set_agent_sessions"
    __table_args__ = (UniqueConstraint("set_id", "user_id", name="uq_set_agent_session_set_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_through_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    set: Mapped[Set] = relationship("Set", back_populates="agent_sessions")
    messages: Mapped[list[SetAgentMessage]] = relationship(
        "SetAgentMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SetAgentMessage.id",
    )


class SetAgentMessage(Base):
    __tablename__ = "set_agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("set_agent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    display_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_transition_scores_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped[SetAgentSession] = relationship("SetAgentSession", back_populates="messages")

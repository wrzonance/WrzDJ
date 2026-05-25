from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    search_rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)

    # Integration toggles (admin can disable broken services at runtime)
    spotify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tidal_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    beatport_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bridge_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Human verification (Turnstile gate on guest pages)
    # Soft-warn-only when False; hard-enforce 403 when True. See docs/HUMAN-VERIFICATION.md.
    human_verification_enforced: Mapped[bool] = mapped_column(Boolean, default=False)

    # LLM / AI settings
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_model: Mapped[str] = mapped_column(String(100), default="claude-haiku-4-5-20251001")
    llm_rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=3)

    # LLM gateway connector policy (admin-controlled)
    # See docs/superpowers/specs/2026-05-24-admin-ai-oauth-design.md §4.2
    llm_apikey_connectors_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    llm_compatible_connector_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    # Org-default connector — used when a system-context (no actor) LLM call is dispatched
    # FK kept nullable; SET NULL on connector delete to avoid orphan references.
    llm_default_connector_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_connectors.id", ondelete="SET NULL"), nullable=True
    )

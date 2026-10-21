from dataclasses import dataclass, fields
from typing import Any

from sqlalchemy.orm import Session

from app.models.system_settings import SystemSettings


class _Unset:
    """Marker for a patch field that was not provided."""


_UNSET = _Unset()


@dataclass(frozen=True)
class SystemSettingsPatch:
    """Fields to update; None means omitted except for nullable connector ID."""

    registration_enabled: bool | None = None
    search_rate_limit_per_minute: int | None = None
    spotify_enabled: bool | None = None
    tidal_enabled: bool | None = None
    beatport_enabled: bool | None = None
    bridge_enabled: bool | None = None
    human_verification_enforced: bool | None = None
    llm_enabled: bool | None = None
    llm_rate_limit_per_minute: int | None = None
    llm_apikey_connectors_enabled: bool | None = None
    llm_compatible_connector_enabled: bool | None = None
    llm_default_connector_id: int | None | _Unset = _UNSET
    llm_call_log_retention_days: int | None = None
    vibe_consensus_min_sample: int | None = None
    vibe_consensus_max_stddev: float | None = None


def get_system_settings(db: Session) -> SystemSettings:
    """Get defaults in the caller's transaction if the singleton row is missing.

    The caller owns the transaction: creating this row must not commit unrelated
    work staged on the same session.
    """
    settings = db.query(SystemSettings).first()
    if not settings:
        settings = SystemSettings(
            id=1,
            registration_enabled=True,
            search_rate_limit_per_minute=30,
            spotify_enabled=True,
            tidal_enabled=True,
            beatport_enabled=True,
            bridge_enabled=True,
            human_verification_enforced=False,
            llm_enabled=True,
            llm_rate_limit_per_minute=3,
            llm_apikey_connectors_enabled=True,
            llm_compatible_connector_enabled=True,
            llm_default_connector_id=None,
            llm_call_log_retention_days=30,
            vibe_consensus_min_sample=3,
            vibe_consensus_max_stddev=1.5,
        )
        db.add(settings)
        db.flush([settings])
        db.refresh(settings)
    return settings


def update_system_settings(db: Session, patch: SystemSettingsPatch) -> SystemSettings:
    """Update system settings fields."""
    settings = get_system_settings(db)
    for field in fields(patch):
        value: Any = getattr(patch, field.name)
        if value is not None and value is not _UNSET:
            setattr(settings, field.name, value)
        elif field.name == "llm_default_connector_id" and value is None:
            settings.llm_default_connector_id = None
    db.commit()
    db.refresh(settings)
    return settings

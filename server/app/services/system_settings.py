from sqlalchemy.orm import Session

from app.models.system_settings import SystemSettings

# Sentinel for "field intentionally not provided" — distinguishes from explicit
# None (which means "clear the FK"). update_system_settings uses this for the
# llm_default_connector_id field which accepts None as a valid value.
_UNSET: object = object()


def get_system_settings(db: Session) -> SystemSettings:
    """Get the singleton system settings row, creating with defaults if missing."""
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
            llm_model="claude-haiku-4-5-20251001",
            llm_rate_limit_per_minute=3,
            llm_apikey_connectors_enabled=True,
            llm_compatible_connector_enabled=True,
            llm_default_connector_id=None,
            llm_call_log_retention_days=30,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_system_settings(
    db: Session,
    registration_enabled: bool | None = None,
    search_rate_limit_per_minute: int | None = None,
    spotify_enabled: bool | None = None,
    tidal_enabled: bool | None = None,
    beatport_enabled: bool | None = None,
    bridge_enabled: bool | None = None,
    human_verification_enforced: bool | None = None,
    llm_enabled: bool | None = None,
    llm_model: str | None = None,
    llm_rate_limit_per_minute: int | None = None,
    llm_apikey_connectors_enabled: bool | None = None,
    llm_compatible_connector_enabled: bool | None = None,
    llm_default_connector_id: int | None | object = _UNSET,
    llm_call_log_retention_days: int | None = None,
) -> SystemSettings:
    """Update system settings fields."""
    settings = get_system_settings(db)
    if registration_enabled is not None:
        settings.registration_enabled = registration_enabled
    if search_rate_limit_per_minute is not None:
        settings.search_rate_limit_per_minute = search_rate_limit_per_minute
    if spotify_enabled is not None:
        settings.spotify_enabled = spotify_enabled
    if tidal_enabled is not None:
        settings.tidal_enabled = tidal_enabled
    if beatport_enabled is not None:
        settings.beatport_enabled = beatport_enabled
    if bridge_enabled is not None:
        settings.bridge_enabled = bridge_enabled
    if human_verification_enforced is not None:
        settings.human_verification_enforced = human_verification_enforced
    if llm_enabled is not None:
        settings.llm_enabled = llm_enabled
    if llm_model is not None:
        settings.llm_model = llm_model
    if llm_rate_limit_per_minute is not None:
        settings.llm_rate_limit_per_minute = llm_rate_limit_per_minute
    if llm_apikey_connectors_enabled is not None:
        settings.llm_apikey_connectors_enabled = llm_apikey_connectors_enabled
    if llm_compatible_connector_enabled is not None:
        settings.llm_compatible_connector_enabled = llm_compatible_connector_enabled
    if llm_default_connector_id is not _UNSET:
        settings.llm_default_connector_id = llm_default_connector_id  # type: ignore[assignment]
    if llm_call_log_retention_days is not None:
        settings.llm_call_log_retention_days = llm_call_log_retention_days
    db.commit()
    db.refresh(settings)
    return settings

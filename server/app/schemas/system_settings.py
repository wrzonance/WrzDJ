from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema


class SystemSettingsOut(BaseSchema):
    registration_enabled: bool
    search_rate_limit_per_minute: int
    spotify_enabled: bool
    tidal_enabled: bool
    beatport_enabled: bool
    bridge_enabled: bool
    human_verification_enforced: bool
    llm_enabled: bool
    llm_rate_limit_per_minute: int


class SystemSettingsUpdate(BaseModel):
    registration_enabled: bool | None = None
    search_rate_limit_per_minute: int | None = Field(None, ge=1, le=100)
    spotify_enabled: bool | None = None
    tidal_enabled: bool | None = None
    beatport_enabled: bool | None = None
    bridge_enabled: bool | None = None
    human_verification_enforced: bool | None = None
    llm_enabled: bool | None = None
    llm_rate_limit_per_minute: int | None = Field(None, ge=1, le=30)

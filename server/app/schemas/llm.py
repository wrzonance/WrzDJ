"""Pydantic schemas for the LLM gateway / connector API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectorType = Literal["openai_apikey", "anthropic_apikey", "openai_compatible"]
ConnectorStatus = Literal["active", "auth_invalid", "disabled"]


class ConnectorOut(BaseModel):
    """Public-safe connector view — never includes the credential blob."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    connector_type: ConnectorType
    display_name: str
    status: ConnectorStatus
    base_url_plain: str | None = None
    model_hint: str | None = None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    last_error: str | None = None


class AdminConnectorOut(ConnectorOut):
    """Admin view — adds the DJ's username for display."""

    dj_username: str


class ConnectorCreate(BaseModel):
    connector_type: ConnectorType
    display_name: str = Field(..., min_length=1, max_length=80)
    model_hint: str | None = Field(default=None, max_length=80)

    # Set for apikey types
    api_key: str | None = Field(default=None, max_length=512)

    # Set for openai_compatible
    base_url: str | None = Field(default=None, max_length=512)
    bearer: str | None = Field(default=None, max_length=512)


class ConnectorPatch(BaseModel):
    """Metadata-only patch (no credential rotation here)."""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model_hint: str | None = Field(default=None, max_length=80)


class ConnectorCredentialsRotate(BaseModel):
    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)
    bearer: str | None = Field(default=None, max_length=512)


class ConnectorTestResult(BaseModel):
    ok: bool
    error_code: str | None = None
    message: str | None = None


class AdminPolicyOut(BaseModel):
    llm_apikey_connectors_enabled: bool
    llm_compatible_connector_enabled: bool
    llm_default_connector_id: int | None


class AdminPolicyPatch(BaseModel):
    llm_apikey_connectors_enabled: bool | None = None
    llm_compatible_connector_enabled: bool | None = None
    # Use a sentinel sentinel: clients can send null to clear, or omit to leave unchanged
    llm_default_connector_id: int | None = None
    clear_default: bool = False


class UsageRow(BaseModel):
    connector_id: int
    dj_username: str
    display_name: str
    connector_type: ConnectorType
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    error_count: int
    error_rate: float


class AdminUsageOut(BaseModel):
    days: int
    rows: list[UsageRow]

"""Pydantic schemas for the LLM gateway / connector API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConnectorType = Literal["openai_apikey", "anthropic_apikey", "openai_compatible", "gemini_apikey"]
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
    """Provider-agnostic create payload.

    Field requirements vary by ``connector_type``:

    - ``openai_apikey`` / ``anthropic_apikey``: ``api_key`` required;
      ``base_url`` and ``bearer`` are ignored.
    - ``openai_compatible``: ``base_url`` required; ``bearer`` optional;
      ``api_key`` is ignored.

    The combination is enforced by :meth:`_require_credentials_for_type`.
    See ``build_create_payload`` in ``services/llm/connector_storage.py``
    for the full validation flow (including key shape checks).
    """

    connector_type: ConnectorType
    display_name: str = Field(..., min_length=1, max_length=80)
    model_hint: str | None = Field(default=None, max_length=80)

    # Set for apikey types
    api_key: str | None = Field(default=None, max_length=512)

    # Set for openai_compatible
    base_url: str | None = Field(default=None, max_length=512)
    bearer: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _require_credentials_for_type(self) -> ConnectorCreate:
        if self.connector_type in ("openai_apikey", "anthropic_apikey", "gemini_apikey"):
            if not self.api_key:
                raise ValueError("api_key is required for API-key connectors")
        elif self.connector_type == "openai_compatible":
            if not self.base_url:
                raise ValueError("base_url is required for openai_compatible connectors")
        return self


class ConnectorPatch(BaseModel):
    """Metadata-only patch (no credential rotation here)."""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model_hint: str | None = Field(default=None, max_length=80)


class ConnectorCredentialsRotate(BaseModel):
    """Rotation payload — at least one credential field must be supplied.

    Field semantics mirror :class:`ConnectorCreate`. The actual field required
    depends on the connector being rotated (validated in ``rotate_credentials``).
    """

    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)
    bearer: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _require_at_least_one(self) -> ConnectorCredentialsRotate:
        if not (self.api_key or self.base_url or self.bearer):
            raise ValueError("At least one of api_key, base_url, or bearer must be provided")
        return self


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

"""Pydantic schemas for the LLM gateway / connector API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.llm_feature_preference import KNOWN_FEATURES

# Feature keys a DJ may pin a connector to (issue #337). ``FeatureKey`` is the
# static Literal used in the request/response schemas (so the OpenAPI spec
# emits a proper enum and FastAPI rejects unknown values at the boundary).
# ``KNOWN_FEATURE_VALUES`` is the sorted runtime tuple returned to the
# frontend so the picker is deterministic. A test
# (``test_feature_key_literal_matches_known_features``) guards that the Literal
# and ``KNOWN_FEATURES`` never drift apart.
FeatureKey = Literal["recommendation", "set_builder"]
KNOWN_FEATURE_VALUES: tuple[str, ...] = tuple(sorted(KNOWN_FEATURES))

ConnectorType = Literal[
    "openai_apikey",
    "anthropic_apikey",
    "openai_compatible",
    "openrouter_apikey",
    "xai_apikey",
    "bedrock",
    "azure_openai",
    "gemini_apikey",
]
ConnectorStatus = Literal["active", "auth_invalid", "disabled"]


def _provided(value: str | None) -> bool:
    """True only when ``value`` is a non-blank string.

    Used by the credential validators so whitespace-only inputs (``"   "``) are
    treated as missing rather than passing a bare truthiness check.
    """
    return isinstance(value, str) and value.strip() != ""


HealthCheckStatus = Literal[
    "ok",
    "auth_invalid",
    "rate_limited",
    "quota_exceeded",
    "provider_unavailable",
    "error",
]


class ConnectorOut(BaseModel):
    """Public-safe connector view — never includes the credential blob."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    # NULL for org-scoped rows (scope='org') — there is no owning DJ.
    user_id: int | None
    scope: Literal["user", "org"] = "user"
    connector_type: ConnectorType
    display_name: str
    status: ConnectorStatus
    base_url_plain: str | None = None
    model_hint: str | None = None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    last_error: str | None = None
    # Per-DJ explicit default flag (issue #336). When True, the gateway pins
    # routing to this connector for the owning DJ instead of falling back to
    # most-recently-used resolution.
    is_default: bool = False
    # Health-check observability (issues #340 + #346).
    last_health_check_at: datetime | None = None
    last_health_check_status: HealthCheckStatus | None = None
    # Admin-set monthly token cap (issue #339). None = unlimited.
    monthly_token_cap: int | None = None


class AdminConnectorOut(ConnectorOut):
    """Admin view — adds the DJ's username for display."""

    dj_username: str
    # Current calendar-month token usage (tokens_in + tokens_out), so the admin
    # UI can render a usage-vs-cap progress bar without a second round-trip
    # (issue #339).
    current_month_tokens: int = 0


class ConnectorCreate(BaseModel):
    """Provider-agnostic create payload.

    Field requirements vary by ``connector_type``:

    - ``openai_apikey`` / ``anthropic_apikey`` / ``openrouter_apikey`` /
      ``xai_apikey`` / ``gemini_apikey``: ``api_key`` required; ``base_url``
      and ``bearer`` are ignored.
    - ``openai_compatible``: ``base_url`` required; ``bearer`` optional;
      ``api_key`` is ignored.
    - ``bedrock``: ``aws_access_key_id``, ``aws_secret_access_key``,
      ``aws_region`` and ``aws_model_id`` required; other fields ignored.
    - ``azure_openai``: ``api_key``, ``azure_resource_name``,
      ``azure_deployment_name`` and ``azure_api_version`` all required.

    The combination is enforced by :meth:`_require_credentials_for_type`.
    See ``build_create_payload`` in ``services/llm/connector_storage.py``
    for the full validation flow (including key shape checks).
    """

    connector_type: ConnectorType
    display_name: str = Field(..., min_length=1, max_length=80)
    model_hint: str | None = Field(default=None, max_length=80)

    # Set for apikey types (and azure_openai)
    api_key: str | None = Field(default=None, max_length=512)

    # Set for openai_compatible
    base_url: str | None = Field(default=None, max_length=512)
    bearer: str | None = Field(default=None, max_length=512)

    # Set for bedrock (AWS SigV4 — billed to the DJ's AWS account)
    aws_access_key_id: str | None = Field(default=None, max_length=128)
    aws_secret_access_key: str | None = Field(default=None, max_length=512)
    aws_region: str | None = Field(default=None, max_length=64)
    aws_model_id: str | None = Field(default=None, max_length=128)

    # Set for azure_openai (stored in the encrypted credentials blob, not columns)
    azure_resource_name: str | None = Field(default=None, max_length=120)
    azure_deployment_name: str | None = Field(default=None, max_length=120)
    azure_api_version: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _require_credentials_for_type(self) -> ConnectorCreate:
        if self.connector_type in (
            "openai_apikey",
            "anthropic_apikey",
            "openrouter_apikey",
            "xai_apikey",
            "gemini_apikey",
        ):
            if not _provided(self.api_key):
                raise ValueError("api_key is required for API-key connectors")
        elif self.connector_type == "openai_compatible":
            if not _provided(self.base_url):
                raise ValueError("base_url is required for openai_compatible connectors")
        elif self.connector_type == "bedrock":
            missing = [
                name
                for name, value in (
                    ("aws_access_key_id", self.aws_access_key_id),
                    ("aws_secret_access_key", self.aws_secret_access_key),
                    ("aws_region", self.aws_region),
                    ("aws_model_id", self.aws_model_id),
                )
                if not _provided(value)
            ]
            if missing:
                raise ValueError("bedrock connectors require " + ", ".join(missing))
        elif self.connector_type == "azure_openai":
            missing = [
                name
                for name, value in (
                    ("api_key", self.api_key),
                    ("azure_resource_name", self.azure_resource_name),
                    ("azure_deployment_name", self.azure_deployment_name),
                    ("azure_api_version", self.azure_api_version),
                )
                if not _provided(value)
            ]
            if missing:
                raise ValueError("azure_openai connectors require: " + ", ".join(missing))
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

    # Set when rotating bedrock credentials.
    aws_access_key_id: str | None = Field(default=None, max_length=128)
    aws_secret_access_key: str | None = Field(default=None, max_length=512)
    aws_region: str | None = Field(default=None, max_length=64)
    aws_model_id: str | None = Field(default=None, max_length=128)

    # azure_openai rotation — admins can swap resource/deployment/version
    # without recreating the connector (all live in the encrypted blob).
    azure_resource_name: str | None = Field(default=None, max_length=120)
    azure_deployment_name: str | None = Field(default=None, max_length=120)
    azure_api_version: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _require_at_least_one(self) -> ConnectorCredentialsRotate:
        if not any(
            _provided(v)
            for v in (
                self.api_key,
                self.base_url,
                self.bearer,
                self.aws_access_key_id,
                self.aws_secret_access_key,
                self.aws_region,
                self.aws_model_id,
                self.azure_resource_name,
                self.azure_deployment_name,
                self.azure_api_version,
            )
        ):
            raise ValueError("At least one credential field must be provided")
        return self


class ConnectorTestResult(BaseModel):
    ok: bool
    error_code: str | None = None
    message: str | None = None


class AdminPolicyOut(BaseModel):
    llm_apikey_connectors_enabled: bool
    llm_compatible_connector_enabled: bool
    llm_default_connector_id: int | None
    llm_call_log_retention_days: int


class DjPolicyOut(BaseModel):
    """DJ-readable connector policy — the non-sensitive subset of the admin
    policy surface.

    Lets the settings/ai page fail *closed*: a normal DJ can learn which
    connector types the admin has enabled (so disallowed providers are hidden
    in the picker) without exposing admin-only fields such as
    ``llm_default_connector_id``.

    ``allowed_connector_types`` is the pre-computed set of connector types a DJ
    may create given the two toggles, so the frontend doesn't have to hard-code
    the api-key-vs-compatible mapping.
    """

    llm_apikey_connectors_enabled: bool
    llm_compatible_connector_enabled: bool
    allowed_connector_types: list[ConnectorType]


class AdminPolicyPatch(BaseModel):
    llm_apikey_connectors_enabled: bool | None = None
    llm_compatible_connector_enabled: bool | None = None
    # Use a sentinel sentinel: clients can send null to clear, or omit to leave unchanged
    llm_default_connector_id: int | None = None
    clear_default: bool = False
    # Sanity bounds: minimum 7 days (data minimization floor), maximum 365 days
    # (reporting ceiling). Out-of-range values are rejected at the API level.
    llm_call_log_retention_days: int | None = Field(None, ge=7, le=365)

    @model_validator(mode="after")
    def _check_default_consistency(self) -> AdminPolicyPatch:
        if self.clear_default and self.llm_default_connector_id is not None:
            raise ValueError(
                "clear_default cannot be combined with a non-null llm_default_connector_id"
            )
        return self


class AdminConnectorCapPatch(BaseModel):
    """Admin set/clear a connector's monthly token cap (issue #339).

    ``monthly_token_cap`` is **required** so intent is always explicit: an
    integer sets the cap, ``null`` clears it (unlimited). Omitting the field
    (an empty ``{}`` body) is rejected with 422 rather than silently treated as
    ``null`` — that would let an accidental no-field PATCH wipe a configured
    cap. A non-null value must be a non-negative integer; ``0`` means "no
    further calls this month". The upper bound is a sanity ceiling, not a
    billing limit.
    """

    monthly_token_cap: int | None = Field(..., ge=0, le=1_000_000_000)


class UsageRow(BaseModel):
    connector_id: int
    # "Organization" for org-scoped connectors; otherwise the owning DJ's username.
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


class AuditEventRow(BaseModel):
    """A single audit-trail row with joined display labels.

    Never includes credential material — only the target connector's
    human-readable display name (joined from ``llm_connectors``).
    """

    id: int
    created_at: datetime
    event_type: str
    # NULL for system-context events (gateway system calls, org-row health
    # checks) — rendered as "system" in actor_username.
    actor_user_id: int | None
    actor_username: str
    target_connector_id: int | None = None
    target_connector_display_name: str | None = None
    notes: str | None = None


class AdminAuditOut(BaseModel):
    """Paginated audit-event browse response."""

    rows: list[AuditEventRow]
    total: int
    limit: int
    offset: int


class FeaturePreferenceOut(BaseModel):
    """A single per-feature connector pin (issue #337)."""

    model_config = ConfigDict(from_attributes=True)

    feature: FeatureKey
    connector_id: int


class FeaturePreferencesListOut(BaseModel):
    """All of a DJ's per-feature pins + the catalogue of pinnable features."""

    preferences: list[FeaturePreferenceOut]
    known_features: list[FeatureKey]


class FeaturePreferenceSet(BaseModel):
    """Set/change a per-feature pin. Upsert — replaces any existing pin."""

    feature: FeatureKey
    connector_id: int = Field(..., ge=1)

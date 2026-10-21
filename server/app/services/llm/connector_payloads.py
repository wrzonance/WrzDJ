"""Pure connector input and credential payload construction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from app.models.llm_connector import (
    CONNECTOR_TYPE_ANTHROPIC_APIKEY,
    CONNECTOR_TYPE_AZURE_OPENAI,
    CONNECTOR_TYPE_BEDROCK,
    CONNECTOR_TYPE_GEMINI_APIKEY,
    CONNECTOR_TYPE_OPENAI_APIKEY,
    CONNECTOR_TYPE_OPENAI_COMPATIBLE,
    CONNECTOR_TYPE_OPENROUTER_APIKEY,
    CONNECTOR_TYPE_XAI_APIKEY,
)
from app.services.llm.url_validator import InvalidBaseUrlError, validate_compatible_base_url

_APIKEY_CONNECTOR_TYPES = (
    CONNECTOR_TYPE_OPENAI_APIKEY,
    CONNECTOR_TYPE_ANTHROPIC_APIKEY,
    CONNECTOR_TYPE_OPENROUTER_APIKEY,
    CONNECTOR_TYPE_XAI_APIKEY,
    CONNECTOR_TYPE_GEMINI_APIKEY,
)

_OPENAI_KEY_PREFIXES = ("sk-",)
_ANTHROPIC_KEY_PREFIX = "sk-ant-"
_OPENROUTER_KEY_PREFIX = "sk-or-"
_XAI_KEY_PREFIX = "xai-"
_GEMINI_KEY_PREFIX = "AIza"
_GEMINI_KEY_LENGTH = 39
_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
_SAFE_MODEL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./")
_AWS_REGION_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")
_AWS_MODEL_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/")
_AZURE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
_AZURE_VERSION_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.")


class CreateConnectorPayload:
    """Validated creation payload consumed by connector persistence."""

    __slots__ = ("connector_type", "display_name", "credentials", "base_url_plain", "model_hint")

    def __init__(
        self,
        *,
        connector_type: str,
        display_name: str,
        credentials: dict,
        base_url_plain: str | None = None,
        model_hint: str | None = None,
    ) -> None:
        self.connector_type = connector_type
        self.display_name = display_name
        self.credentials = credentials
        self.base_url_plain = base_url_plain
        self.model_hint = model_hint


@dataclass(frozen=True)
class ApiKeyConnectorInput:
    connector_type: Literal[
        "openai_apikey", "anthropic_apikey", "openrouter_apikey", "xai_apikey", "gemini_apikey"
    ]
    display_name: str
    api_key: str
    model_hint: str | None = None


@dataclass(frozen=True)
class CompatibleConnectorInput:
    display_name: str
    base_url: str
    bearer: str | None = None
    model_hint: str | None = None


@dataclass(frozen=True)
class BedrockConnectorInput:
    display_name: str
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    aws_model_id: str
    model_hint: str | None = None


@dataclass(frozen=True)
class AzureConnectorInput:
    display_name: str
    api_key: str
    azure_resource_name: str
    azure_deployment_name: str
    azure_api_version: str
    model_hint: str | None = None


@dataclass(frozen=True)
class ApiKeyCredentialRotation:
    api_key: str | None


@dataclass(frozen=True)
class CompatibleCredentialRotation:
    base_url: str | None
    bearer: str | None


@dataclass(frozen=True)
class BedrockCredentialRotation:
    aws_access_key_id: str | None
    aws_secret_access_key: str | None
    aws_region: str | None
    aws_model_id: str | None


@dataclass(frozen=True)
class AzureCredentialRotation:
    api_key: str | None
    azure_resource_name: str | None
    azure_deployment_name: str | None
    azure_api_version: str | None


CredentialRotationInput: TypeAlias = (
    ApiKeyCredentialRotation
    | CompatibleCredentialRotation
    | BedrockCredentialRotation
    | AzureCredentialRotation
)

ConnectorCreateInput: TypeAlias = (
    ApiKeyConnectorInput | CompatibleConnectorInput | BedrockConnectorInput | AzureConnectorInput
)


@dataclass(frozen=True)
class RotatedCredentialPayload:
    credentials: dict[str, Any]
    base_url_plain: str | None = None


def normalize_model_hint(value: str | None, *, invalid_msg: str) -> str | None:
    """Strip and validate a model hint while preserving caller-specific errors."""
    if value is None:
        return None
    value = value.strip() or None
    if value is not None:
        if len(value) > 80:
            raise ValueError("model_hint must be 80 characters or fewer")
        if not _is_safe_model_hint(value):
            raise ValueError(invalid_msg)
    return value


def build_create_payload(payload: ConnectorCreateInput) -> CreateConnectorPayload:
    """Translate validated API fields into a normalized connector payload."""
    connector_type: str
    if isinstance(payload, ApiKeyConnectorInput):
        if payload.connector_type not in _APIKEY_CONNECTOR_TYPES:
            raise ValueError(f"Unsupported API-key connector type: {payload.connector_type!r}")
        connector_type = payload.connector_type
    elif isinstance(payload, CompatibleConnectorInput):
        connector_type = CONNECTOR_TYPE_OPENAI_COMPATIBLE
    elif isinstance(payload, BedrockConnectorInput):
        connector_type = CONNECTOR_TYPE_BEDROCK
    elif isinstance(payload, AzureConnectorInput):
        connector_type = CONNECTOR_TYPE_AZURE_OPENAI
    else:
        raise TypeError(f"Unsupported connector input: {type(payload).__name__}")

    display_name = payload.display_name.strip()
    if not display_name:
        raise ValueError("display_name is required")
    if len(display_name) > 80:
        raise ValueError("display_name must be 80 characters or fewer")
    if any(ord(char) < 0x20 for char in display_name):
        raise ValueError("display_name must not contain control characters")

    model_hint = normalize_model_hint(
        payload.model_hint,
        invalid_msg=(
            "model_hint may only contain letters, digits, dot, underscore, hyphen, or slash"
        ),
    )

    credentials: dict[str, Any]
    base_url_plain: str | None = None
    if isinstance(payload, ApiKeyConnectorInput):
        credentials = _validate_api_key_blob(
            connector_type, payload.api_key, required_msg="api_key is required"
        )
    elif isinstance(payload, CompatibleConnectorInput):
        try:
            base_url_plain = validate_compatible_base_url(payload.base_url)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc
        credentials = {"base_url": base_url_plain, "bearer": payload.bearer or None}
    elif isinstance(payload, BedrockConnectorInput):
        credentials = _build_bedrock_creds(
            aws_access_key_id=payload.aws_access_key_id,
            aws_secret_access_key=payload.aws_secret_access_key,
            aws_region=payload.aws_region,
            aws_model_id=payload.aws_model_id,
        )
    elif isinstance(payload, AzureConnectorInput):
        credentials = _build_azure_creds(
            api_key=payload.api_key,
            azure_resource_name=payload.azure_resource_name,
            azure_deployment_name=payload.azure_deployment_name,
            azure_api_version=payload.azure_api_version,
        )
    else:
        raise TypeError(f"Unsupported connector input: {type(payload).__name__}")

    return CreateConnectorPayload(
        connector_type=connector_type,
        display_name=display_name,
        credentials=credentials,
        base_url_plain=base_url_plain,
        model_hint=model_hint,
    )


def build_rotated_credentials(
    connector_type: str,
    current_credentials: str | None,
    rotation: CredentialRotationInput,
) -> RotatedCredentialPayload:
    """Validate a credential rotation and return the values persistence should assign."""
    if connector_type in _APIKEY_CONNECTOR_TYPES:
        if not isinstance(rotation, ApiKeyCredentialRotation):
            raise ValueError(f"Rotation fields do not apply to {connector_type}")
        credentials = _validate_api_key_blob(
            connector_type, rotation.api_key, required_msg="api_key is required for rotation"
        )
        return RotatedCredentialPayload(credentials)

    if connector_type == CONNECTOR_TYPE_OPENAI_COMPATIBLE:
        if not isinstance(rotation, CompatibleCredentialRotation):
            raise ValueError("Rotation fields do not apply to openai_compatible")
        if not rotation.base_url:
            raise ValueError("base_url is required for rotation")
        try:
            base_url = validate_compatible_base_url(rotation.base_url)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc
        return RotatedCredentialPayload(
            {"base_url": base_url, "bearer": rotation.bearer or None},
            base_url_plain=base_url,
        )

    if connector_type == CONNECTOR_TYPE_BEDROCK:
        if not isinstance(rotation, BedrockCredentialRotation):
            raise ValueError("Rotation fields do not apply to bedrock")
        existing = _load_existing_credentials(current_credentials)
        credentials = _build_bedrock_creds(
            aws_access_key_id=rotation.aws_access_key_id or existing.get("aws_access_key_id"),
            aws_secret_access_key=(
                rotation.aws_secret_access_key or existing.get("aws_secret_access_key")
            ),
            aws_region=rotation.aws_region or existing.get("aws_region"),
            aws_model_id=rotation.aws_model_id or existing.get("aws_model_id"),
        )
        return RotatedCredentialPayload(credentials)

    if connector_type == CONNECTOR_TYPE_AZURE_OPENAI:
        if not isinstance(rotation, AzureCredentialRotation):
            raise ValueError("Rotation fields do not apply to azure_openai")
        current = _load_existing_credentials(current_credentials)
        api_key = current.get("api_key") if rotation.api_key is None else rotation.api_key.strip()
        credentials = _build_azure_creds(
            api_key=api_key,
            azure_resource_name=_preserve_if_omitted(
                current, "azure_resource_name", rotation.azure_resource_name
            ),
            azure_deployment_name=_preserve_if_omitted(
                current, "azure_deployment_name", rotation.azure_deployment_name
            ),
            azure_api_version=_preserve_if_omitted(
                current, "azure_api_version", rotation.azure_api_version
            ),
        )
        return RotatedCredentialPayload(credentials)

    raise ValueError(f"Unsupported connector_type: {connector_type!r}")


def _preserve_if_omitted(
    current: dict[str, Any], field: str, replacement: str | None
) -> str | None:
    return current.get(field) if replacement is None else replacement


def _load_existing_credentials(raw: str | None) -> dict[str, Any]:
    try:
        blob = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return {}
    return blob if isinstance(blob, dict) else {}


def _validate_api_key_blob(
    connector_type: str, api_key: str | None, *, required_msg: str
) -> dict[str, str]:
    if not api_key:
        raise ValueError(required_msg)
    api_key = api_key.strip()
    if not _looks_like_api_key(connector_type, api_key):
        raise ValueError("api_key format is invalid")
    return {"api_key": api_key}


def _build_bedrock_creds(
    *,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    aws_region: str | None,
    aws_model_id: str | None,
) -> dict[str, str]:
    access_key = (aws_access_key_id or "").strip()
    secret_key = (aws_secret_access_key or "").strip()
    region = (aws_region or "").strip()
    model_id = (aws_model_id or "").strip()
    if not access_key:
        raise ValueError("aws_access_key_id is required")
    if not secret_key:
        raise ValueError("aws_secret_access_key is required")
    if not region:
        raise ValueError("aws_region is required")
    if not model_id:
        raise ValueError("aws_model_id is required")
    if " " in access_key or "\n" in access_key or not all(c in _SAFE_CHARS for c in access_key):
        raise ValueError("aws_access_key_id format is invalid")
    if " " in secret_key or "\n" in secret_key:
        raise ValueError("aws_secret_access_key format is invalid")
    if not all(c in _AWS_REGION_CHARS for c in region):
        raise ValueError("aws_region format is invalid")
    if not all(c in _AWS_MODEL_ID_CHARS for c in model_id):
        raise ValueError("aws_model_id format is invalid")
    return {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "aws_region": region,
        "aws_model_id": model_id,
    }


def _looks_like_api_key(connector_type: str, key: str) -> bool:
    if not key or " " in key or "\n" in key:
        return False
    if not all(c in _SAFE_CHARS for c in key):
        return False
    if connector_type == CONNECTOR_TYPE_ANTHROPIC_APIKEY:
        return key.startswith(_ANTHROPIC_KEY_PREFIX) and len(key) >= len(_ANTHROPIC_KEY_PREFIX) + 30
    if connector_type == CONNECTOR_TYPE_OPENROUTER_APIKEY:
        return key.startswith(_OPENROUTER_KEY_PREFIX) and len(key) >= (
            len(_OPENROUTER_KEY_PREFIX) + 20
        )
    if connector_type == CONNECTOR_TYPE_OPENAI_APIKEY:
        return any(key.startswith(prefix) for prefix in _OPENAI_KEY_PREFIXES) and len(key) >= 20
    if connector_type == CONNECTOR_TYPE_XAI_APIKEY:
        return key.startswith(_XAI_KEY_PREFIX) and len(key) >= len(_XAI_KEY_PREFIX) + 20
    if connector_type == CONNECTOR_TYPE_GEMINI_APIKEY:
        return key.startswith(_GEMINI_KEY_PREFIX) and len(key) == _GEMINI_KEY_LENGTH
    return False


def _build_azure_creds(
    *,
    api_key: str | None,
    azure_resource_name: str | None,
    azure_deployment_name: str | None,
    azure_api_version: str | None,
) -> dict[str, Any]:
    if not api_key or not api_key.strip():
        raise ValueError("api_key is required")
    return {
        "api_key": api_key.strip(),
        "azure_resource_name": _validate_azure_field(
            "azure_resource_name", azure_resource_name, _AZURE_NAME_CHARS, 120
        ),
        "azure_deployment_name": _validate_azure_field(
            "azure_deployment_name", azure_deployment_name, _AZURE_NAME_CHARS, 120
        ),
        "azure_api_version": _validate_azure_field(
            "azure_api_version", azure_api_version, _AZURE_VERSION_CHARS, 40
        ),
    }


def _validate_azure_field(name: str, value: str | None, allowed: set[str], max_len: int) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    if len(value) > max_len:
        raise ValueError(f"{name} must be {max_len} characters or fewer")
    if not all(char in allowed for char in value):
        raise ValueError(f"{name} contains invalid characters")
    return value


def _is_safe_model_hint(value: str) -> bool:
    return all(char in _SAFE_MODEL_CHARS for char in value)

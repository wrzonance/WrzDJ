"""Translate the stable provider-agnostic API schema to service input variants."""

from app.schemas.llm import ConnectorCreate, ConnectorCredentialsRotate
from app.services.llm.connector_payloads import (
    ApiKeyConnectorInput,
    ApiKeyCredentialRotation,
    AzureConnectorInput,
    AzureCredentialRotation,
    BedrockConnectorInput,
    BedrockCredentialRotation,
    CompatibleConnectorInput,
    CompatibleCredentialRotation,
    ConnectorCreateInput,
    CredentialRotationInput,
)


def to_connector_create_input(payload: ConnectorCreate) -> ConnectorCreateInput:
    """Build a provider-specific service input from validated request data."""
    common = {"display_name": payload.display_name, "model_hint": payload.model_hint}
    match payload.connector_type:
        case (
            "openai_apikey"
            | "anthropic_apikey"
            | "openrouter_apikey"
            | "xai_apikey"
            | "gemini_apikey"
        ):
            if payload.api_key is None:
                raise ValueError("api_key is required for API-key connectors")
            return ApiKeyConnectorInput(
                connector_type=payload.connector_type, api_key=payload.api_key, **common
            )
        case "openai_compatible":
            if payload.base_url is None:
                raise ValueError("base_url is required for openai_compatible connectors")
            return CompatibleConnectorInput(
                base_url=payload.base_url, bearer=payload.bearer, **common
            )
        case "bedrock":
            required = {
                "aws_access_key_id": payload.aws_access_key_id,
                "aws_secret_access_key": payload.aws_secret_access_key,
                "aws_region": payload.aws_region,
                "aws_model_id": payload.aws_model_id,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("bedrock connectors require " + ", ".join(missing))
            return BedrockConnectorInput(
                aws_access_key_id=payload.aws_access_key_id,
                aws_secret_access_key=payload.aws_secret_access_key,
                aws_region=payload.aws_region,
                aws_model_id=payload.aws_model_id,
                **common,
            )
        case "azure_openai":
            required = {
                "api_key": payload.api_key,
                "azure_resource_name": payload.azure_resource_name,
                "azure_deployment_name": payload.azure_deployment_name,
                "azure_api_version": payload.azure_api_version,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("azure_openai connectors require: " + ", ".join(missing))
            return AzureConnectorInput(
                api_key=payload.api_key,
                azure_resource_name=payload.azure_resource_name,
                azure_deployment_name=payload.azure_deployment_name,
                azure_api_version=payload.azure_api_version,
                **common,
            )
    raise ValueError(f"Unsupported connector_type: {payload.connector_type!r}")


def to_credential_rotation_input(
    connector_type: str, payload: ConnectorCredentialsRotate
) -> CredentialRotationInput:
    """Adapt the stable rotation JSON shape to the loaded connector's fields.

    Explicit ``null`` is treated like omission for applicable optional fields,
    preserving partial-rotation behavior. A key present for another provider
    is rejected even when its value is null.
    """
    fields_by_connector = {
        "openai_apikey": {"api_key"},
        "anthropic_apikey": {"api_key"},
        "openrouter_apikey": {"api_key"},
        "xai_apikey": {"api_key"},
        "gemini_apikey": {"api_key"},
        "openai_compatible": {"base_url", "bearer"},
        "bedrock": {
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_region",
            "aws_model_id",
        },
        "azure_openai": {
            "api_key",
            "azure_resource_name",
            "azure_deployment_name",
            "azure_api_version",
        },
    }
    allowed_fields = fields_by_connector.get(connector_type)
    if allowed_fields is None:
        raise ValueError(f"Unsupported connector_type: {connector_type!r}")

    irrelevant = payload.model_fields_set - allowed_fields
    if irrelevant:
        field_list = ", ".join(sorted(irrelevant))
        raise ValueError(f"Fields not supported for {connector_type} connector: {field_list}")

    match connector_type:
        case (
            "openai_apikey"
            | "anthropic_apikey"
            | "openrouter_apikey"
            | "xai_apikey"
            | "gemini_apikey"
        ):
            return ApiKeyCredentialRotation(api_key=payload.api_key)
        case "openai_compatible":
            return CompatibleCredentialRotation(base_url=payload.base_url, bearer=payload.bearer)
        case "bedrock":
            return BedrockCredentialRotation(
                aws_access_key_id=payload.aws_access_key_id,
                aws_secret_access_key=payload.aws_secret_access_key,
                aws_region=payload.aws_region,
                aws_model_id=payload.aws_model_id,
            )
        case "azure_openai":
            return AzureCredentialRotation(
                api_key=payload.api_key,
                azure_resource_name=payload.azure_resource_name,
                azure_deployment_name=payload.azure_deployment_name,
                azure_api_version=payload.azure_api_version,
            )
    raise ValueError(f"Unsupported connector_type: {connector_type!r}")

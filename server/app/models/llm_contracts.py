"""Shared constrained values used by LLM schemas and API response builders."""

from typing import Literal, TypeAlias

FeatureKey: TypeAlias = Literal["recommendation", "set_builder"]
FEATURE_KEY_VALUES: tuple[FeatureKey, ...] = ("recommendation", "set_builder")

ConnectorType: TypeAlias = Literal[
    "openai_apikey",
    "anthropic_apikey",
    "openai_compatible",
    "openrouter_apikey",
    "xai_apikey",
    "bedrock",
    "azure_openai",
    "gemini_apikey",
]
CONNECTOR_TYPE_VALUES: tuple[ConnectorType, ...] = (
    "anthropic_apikey",
    "azure_openai",
    "bedrock",
    "gemini_apikey",
    "openai_apikey",
    "openai_compatible",
    "openrouter_apikey",
    "xai_apikey",
)

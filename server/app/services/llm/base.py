"""Canonical request / response types + LlmAdapter ABC.

Adapters convert between provider-native request/response shapes and these
canonical models. See spec §4.4.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContentBlock(BaseModel):
    """Optional multi-modal content block — text-only in MVP."""

    type: Literal["text"] = "text"
    text: str


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentBlock]
    tool_call_id: str | None = None
    # When role == "assistant" and the message includes tool_use blocks,
    # callers may serialise them as text + tool_calls separately. Adapters
    # handle the per-provider shape; gateway callers just supply text/role.


class ToolSpec(BaseModel):
    """Canonical tool definition — JSON Schema shape carries the input schema."""

    name: str
    description: str
    input_schema: dict


class ToolCall(BaseModel):
    """An LLM-issued call to a tool, parsed from the provider response."""

    id: str
    name: str
    input: dict


class TokenUsage(BaseModel):
    prompt: int
    completion: int


class ChatRequest(BaseModel):
    """Provider-agnostic chat request."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: list[Message]
    tools: list[ToolSpec] | None = None
    force_tool: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    # Overrides the connector's model_hint when present.
    model: str | None = None
    # Per-call timeout in seconds; adapters may clamp to a max.
    timeout_seconds: float | None = None
    # Optional system prompt — adapters surface this as the provider's native
    # system role (Anthropic top-level system; OpenAI as the first system msg).
    system: str | None = None


class ChatResponse(BaseModel):
    """Provider-agnostic chat response."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "error"]
    usage: TokenUsage | None = None
    # The provider model id that actually produced the response (for telemetry).
    model: str | None = None


class LlmAdapter(ABC):
    """Adapter interface — one per connector_type.

    Adapters are instantiated per call, given the resolved ``LlmConnector`` row.
    They must read credentials lazily (the row's ``credentials`` column is an
    ``EncryptedText`` column; accessing the attribute auto-decrypts).
    """

    #: connector_type identifier — set on the subclass.
    connector_type: str = ""

    def __init__(self, connector) -> None:  # noqa: ANN001 — LlmConnector type
        self.connector = connector

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Dispatch a chat request, returning a canonical response.

        Must raise one of:
        - AuthInvalid (401/403)
        - RateLimited (429, with retry_after_seconds if provided)
        - QuotaExceeded (402 / billing failure)
        - ProviderUnavailable (5xx / network / timeout)
        - ToolTranslationError (couldn't translate input or parse output)
        """

    @abstractmethod
    async def health_check(self) -> None:
        """Validate the credential against the provider.

        Raises the same typed exceptions as ``chat()``. Returns ``None`` on
        success.
        """

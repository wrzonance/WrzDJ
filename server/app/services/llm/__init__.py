"""LLM gateway — provider-agnostic dispatch for agentic features.

See docs/superpowers/specs/2026-05-24-admin-ai-oauth-design.md.

Entrypoint: ``Gateway.dispatch(db, actor, request, *, purpose)`` →
``ChatResponse``. Adapters live under :mod:`app.services.llm.adapters`.
"""

from app.services.llm.base import (
    ChatRequest,
    ChatResponse,
    ContentBlock,
    LlmAdapter,
    Message,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from app.services.llm.exceptions import (
    AuthInvalid,
    LlmError,
    NoLlmConfigured,
    ProviderUnavailable,
    QuotaCapReached,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.gateway import Gateway

__all__ = [
    "AuthInvalid",
    "ChatRequest",
    "ChatResponse",
    "ContentBlock",
    "Gateway",
    "LlmAdapter",
    "LlmError",
    "Message",
    "NoLlmConfigured",
    "ProviderUnavailable",
    "QuotaCapReached",
    "QuotaExceeded",
    "RateLimited",
    "TokenUsage",
    "ToolCall",
    "ToolSpec",
    "ToolTranslationError",
]

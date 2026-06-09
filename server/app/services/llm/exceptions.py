"""Typed exceptions for the LLM gateway.

Adapters raise these specific types; the gateway never re-raises a provider's
native exception or HTTP error body to callers — that prevents bearer-token /
credential leakage in error messages.
"""

from __future__ import annotations


class LlmError(Exception):
    """Base class for all gateway-raised LLM errors."""


class NoLlmConfigured(LlmError):
    """No active connector for the actor and no system default connector."""


class AuthInvalid(LlmError):
    """The provider returned 401 / 403 — connector marked auth_invalid."""


class RateLimited(LlmError):
    """The provider returned 429 — caller should back off and try later."""

    def __init__(self, message: str = "Rate limited", retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class QuotaExceeded(LlmError):
    """Billing / quota failure (402 or provider-specific quota error)."""


class QuotaCapReached(LlmError):
    """The DJ's admin-set monthly token cap for this connector is reached.

    Distinct from :class:`QuotaExceeded` (a provider-side billing/quota error):
    this is a WrzDJ-internal pre-flight refusal raised *before* any provider
    call, so no tokens are spent. The DJ-facing message is fixed and contains
    no internal details — see the gateway pre-flight check (issue #339).
    """


class ProviderUnavailable(LlmError):
    """Transient upstream failure — 5xx, network error, or timeout."""


class ToolTranslationError(LlmError):
    """Canonical ToolSpec couldn't be translated or the response couldn't be parsed."""


class StreamingUnsupported(LlmError):
    """The resolved adapter does not implement provider-native streaming."""

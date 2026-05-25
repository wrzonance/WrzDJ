"""xAI Grok API-key adapter.

xAI exposes an OpenAI-compatible Chat Completions surface at a fixed base URL
(``https://api.x.ai/v1``). Rather than re-implement the OpenAI wire format we
subclass :class:`OpenAICompatibleAdapter` and:

- pin the base URL (it is NOT user-supplied — credentials only carry an api_key),
- extract the api_key from the ``{"api_key": "..."}`` credential blob and pass it
  through as the bearer token,
- layer xAI-specific error context on top of the inherited error mapping.

Tool-use mirrors OpenAI function-calling and is handled entirely by the inherited
``call_openai_chat`` path (``to_openai_tools`` / ``parse_openai_response``).
"""

from __future__ import annotations

import json
import logging

from app.services.llm.adapters._httpx_openai import (
    build_healthcheck_request,
    call_openai_chat,
)
from app.services.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.services.llm.base import ChatRequest, ChatResponse
from app.services.llm.exceptions import AuthInvalid, ProviderUnavailable
from app.services.llm.registry import register_adapter

logger = logging.getLogger(__name__)

# Fixed xAI Chat Completions API root — never taken from user input.
XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-3-mini"


class XaiApiKeyAdapter(OpenAICompatibleAdapter):
    """xAI Grok adapter — fixed base URL, api_key credential, OpenAI-compatible wire."""

    connector_type = "xai_apikey"

    def _extract_credentials(self) -> tuple[str, str | None]:
        """Return (fixed xAI base_url, api_key).

        Unlike the parent ``openai_compatible`` adapter, xAI connectors store an
        ``{"api_key": "..."}`` blob (the same shape as the other api-key
        connectors) and the base URL is pinned — it is never user-supplied.
        """
        raw = self.connector.credentials or ""
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthInvalid("Connector credentials are malformed") from exc
        if not isinstance(blob, dict):
            raise AuthInvalid("Connector credentials shape is invalid")
        api_key = blob.get("api_key")
        if not api_key:
            raise AuthInvalid("Connector is missing an api_key")
        return XAI_BASE_URL, str(api_key)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        base_url, api_key = self._extract_credentials()
        try:
            return await call_openai_chat(
                base_url=base_url,
                api_key=api_key,
                request=request,
                fallback_model=self.connector.model_hint or DEFAULT_MODEL,
            )
        except ProviderUnavailable as exc:
            # Attach xAI context so telemetry/logs are unambiguous about which
            # upstream failed. The error class (and gateway mapping) is unchanged.
            raise ProviderUnavailable(f"xAI provider unavailable: {exc}") from exc

    async def health_check(self) -> None:
        base_url, api_key = self._extract_credentials()
        ping = build_healthcheck_request()
        await call_openai_chat(
            base_url=base_url,
            api_key=api_key,
            request=ping,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
        )


register_adapter("xai_apikey", XaiApiKeyAdapter)

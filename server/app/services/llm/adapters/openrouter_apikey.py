"""OpenRouter API-key adapter.

OpenRouter (https://openrouter.ai) exposes an OpenAI-compatible Chat
Completions API at a fixed base URL and routes each request to one of many
upstream models selected via the ``model`` field. A single OpenRouter API key
therefore unlocks dozens of providers.

This adapter subclasses :class:`OpenAICompatibleAdapter` to inherit the entire
request/response + error-mapping pipeline. It differs only in:

- a fixed ``base_url`` (``https://openrouter.ai/api/v1``) — never user-supplied
- credentials stored as ``{"api_key": "sk-or-..."}`` (api-key shape), surfaced
  to the shared OpenAI caller as the ``Authorization: Bearer`` token.
"""

from __future__ import annotations

from app.services.llm.adapters._shared import extract_fixed_base_credentials
from app.services.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.services.llm.registry import register_adapter

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# OpenRouter model ids are namespaced ("provider/model"). This cheap, broadly
# available default is only used when the connector has no model_hint.
DEFAULT_MODEL = "openai/gpt-4o-mini"


class OpenRouterApiKeyAdapter(OpenAICompatibleAdapter):
    """OpenRouter connector — OpenAI-compatible with a fixed base URL."""

    connector_type = "openrouter_apikey"
    default_model = DEFAULT_MODEL

    def _extract_credentials(self) -> tuple[str, str | None]:
        """Return (fixed base_url, api-key bearer).

        OpenRouter stores credentials as ``{"api_key": "..."}`` (like the other
        api-key connectors) rather than the ``{"base_url", "bearer"}`` shape
        used by ``openai_compatible``. The base URL is always the fixed
        OpenRouter endpoint — never user-supplied — which removes the SSRF
        surface of arbitrary base URLs.
        """
        return extract_fixed_base_credentials(self.connector.credentials or "", OPENROUTER_BASE_URL)


register_adapter("openrouter_apikey", OpenRouterApiKeyAdapter)

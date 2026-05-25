"""OpenAI-compatible endpoint adapter (Hermes Agent / Ollama / LMStudio / vLLM)."""

from __future__ import annotations

import json
import logging

from app.services.llm.adapters._httpx_openai import (
    build_healthcheck_request,
    call_openai_chat,
)
from app.services.llm.base import ChatRequest, ChatResponse, LlmAdapter
from app.services.llm.exceptions import AuthInvalid
from app.services.llm.registry import register_adapter
from app.services.llm.url_validator import InvalidBaseUrlError, validate_compatible_base_url

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5-mini"


class OpenAICompatibleAdapter(LlmAdapter):
    connector_type = "openai_compatible"

    def _extract_credentials(self) -> tuple[str, str | None]:
        """Return (base_url, bearer-or-None)."""
        raw = self.connector.credentials or ""
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthInvalid("Connector credentials are malformed") from exc
        if not isinstance(blob, dict):
            raise AuthInvalid("Connector credentials shape is invalid")
        base_url = blob.get("base_url") or self.connector.base_url_plain
        if not base_url:
            raise AuthInvalid("Connector is missing a base_url")
        # Final SSRF boundary check: re-validate at call time, since storage-time
        # validation can be bypassed by stale rows or manual DB edits.
        try:
            base_url = validate_compatible_base_url(str(base_url))
        except InvalidBaseUrlError as exc:
            raise AuthInvalid("Connector base_url failed validation") from exc
        bearer = blob.get("bearer")
        # Empty-string bearer is treated as no bearer.
        return base_url, (str(bearer) if bearer else None)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        base_url, bearer = self._extract_credentials()
        return await call_openai_chat(
            base_url=base_url,
            api_key=bearer,
            request=request,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
        )

    async def health_check(self) -> None:
        base_url, bearer = self._extract_credentials()
        ping = build_healthcheck_request()
        await call_openai_chat(
            base_url=base_url,
            api_key=bearer,
            request=ping,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
        )


register_adapter("openai_compatible", OpenAICompatibleAdapter)

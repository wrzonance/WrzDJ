"""OpenAI Platform API-key adapter."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.services.llm.adapters._httpx_openai import (
    build_healthcheck_request,
    call_openai_chat,
    stream_openai_chat,
)
from app.services.llm.adapters._shared import extract_api_key
from app.services.llm.base import ChatRequest, ChatResponse, ChatResponseChunk, LlmAdapter
from app.services.llm.registry import register_adapter

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5-mini"

# OpenAI Platform's GPT-5 / o-series models reject the legacy ``max_tokens`` field
# (HTTP 400 ``unsupported_parameter``) and require ``max_completion_tokens``, which
# every current OpenAI Platform chat model also accepts. Third-party OpenAI-compatible
# servers still speak ``max_tokens``, so this override is scoped to the Platform adapter.
_MAX_TOKENS_FIELD = "max_completion_tokens"


class OpenAIApiKeyAdapter(LlmAdapter):
    connector_type = "openai_apikey"

    def _extract_api_key(self) -> str:
        return extract_api_key(self.connector.credentials or "")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        api_key = self._extract_api_key()
        return await call_openai_chat(
            base_url=OPENAI_BASE_URL,
            api_key=api_key,
            request=request,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
            max_tokens_field=_MAX_TOKENS_FIELD,
        )

    async def health_check(self) -> None:
        api_key = self._extract_api_key()
        ping = build_healthcheck_request()
        # We just need to exercise the auth path — discard the response.
        await call_openai_chat(
            base_url=OPENAI_BASE_URL,
            api_key=api_key,
            request=ping,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
            max_tokens_field=_MAX_TOKENS_FIELD,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponseChunk]:
        api_key = self._extract_api_key()
        async for chunk in stream_openai_chat(
            base_url=OPENAI_BASE_URL,
            api_key=api_key,
            request=request,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
            max_tokens_field=_MAX_TOKENS_FIELD,
        ):
            yield chunk


register_adapter("openai_apikey", OpenAIApiKeyAdapter)

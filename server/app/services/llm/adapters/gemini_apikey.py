"""Google Gemini API-key adapter (native generativelanguage API).

Gemini's native API is NOT OpenAI-compatible, so this adapter talks to
``generativelanguage.googleapis.com`` directly via httpx rather than reusing
the shared OpenAI caller. Key differences handled here:

- Tools are nested ``function_declarations`` under a single ``tools`` entry
  (see ``tool_translation.to_gemini_tools``).
- Messages use ``contents`` with roles ``user`` / ``model`` and ``parts``.
- The system prompt maps to ``systemInstruction``.
- Auth is via the ``x-goog-api-key`` header (never the URL/query string, so the
  key is not captured in proxy/access logs).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.llm.base import ChatRequest, ChatResponse, LlmAdapter, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.registry import register_adapter
from app.services.llm.tool_translation import parse_gemini_response, to_gemini_tools

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0


class GeminiApiKeyAdapter(LlmAdapter):
    connector_type = "gemini_apikey"

    def _extract_api_key(self) -> str:
        raw = self.connector.credentials or ""
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthInvalid("Connector credentials are malformed") from exc
        api_key = blob.get("api_key") if isinstance(blob, dict) else None
        if not api_key:
            raise AuthInvalid("Connector is missing an api_key")
        return str(api_key)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        api_key = self._extract_api_key()
        model = request.model or self.connector.model_hint or DEFAULT_MODEL

        payload = self._build_payload(request)
        endpoint = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Header auth keeps the key out of URLs / access logs.
            "x-goog-api-key": api_key,
        }

        timeout = min(
            max(request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS, 1.0),
            MAX_TIMEOUT_SECONDS,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable("Upstream timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Upstream network error") from exc

        _raise_for_status(resp)

        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ToolTranslationError("Upstream returned non-JSON body") from exc

        return parse_gemini_response(body)

    async def health_check(self) -> None:
        # 1-token ping to validate the key + reach the API.
        ping = ChatRequest(
            messages=[Message(role="user", content="ping")],
            max_tokens=1,
            temperature=0.0,
        )
        await self.chat(ping)

    def _build_payload(self, request: ChatRequest) -> dict:
        body: dict[str, Any] = {"contents": self._translate_messages(request.messages)}

        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}

        generation_config: dict[str, Any] = {}
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if generation_config:
            body["generationConfig"] = generation_config

        tools, tool_config = to_gemini_tools(request.tools, request.force_tool)
        if tools:
            body["tools"] = tools
        if tool_config is not None:
            body["toolConfig"] = tool_config

        return body

    @staticmethod
    def _translate_messages(messages: list[Message]) -> list[dict]:
        """Translate canonical messages to Gemini ``contents``.

        System messages are pulled out by the caller (``request.system``).
        Assistant turns map to the Gemini ``model`` role; tool-result messages
        map to a ``functionResponse`` part on a ``user`` turn.
        """
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                # Surfaced via request.system; swallow here for legacy callers.
                continue

            content = m.content
            if isinstance(content, list):
                chunks: list[str] = []
                for b in content:
                    if isinstance(b, dict):
                        chunks.append(str(b.get("text") or ""))
                    else:
                        chunks.append(str(getattr(b, "text", "") or ""))
                text = "".join(chunks)
            else:
                text = content or ""

            if m.role == "tool":
                if not m.tool_call_id:
                    raise ToolTranslationError("Tool message missing tool_call_id")
                out.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": m.tool_call_id,
                                    "response": {"content": text},
                                }
                            }
                        ],
                    }
                )
                continue

            role = "model" if m.role == "assistant" else "user"
            out.append({"role": role, "parts": [{"text": text}]})
        return out


def _raise_for_status(resp: httpx.Response) -> None:
    if 200 <= resp.status_code < 300:
        return

    code = resp.status_code
    if code in (401, 403):
        raise AuthInvalid(f"Auth failed (HTTP {code})")
    if code == 402:
        raise QuotaExceeded("Quota or billing failure (HTTP 402)")
    if code == 429:
        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
        raise RateLimited("Rate limited (HTTP 429)", retry_after_seconds=retry_after)
    if 500 <= code < 600:
        raise ProviderUnavailable(f"Upstream error (HTTP {code})")
    raise ToolTranslationError(f"Upstream rejected request (HTTP {code})")


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


register_adapter("gemini_apikey", GeminiApiKeyAdapter)

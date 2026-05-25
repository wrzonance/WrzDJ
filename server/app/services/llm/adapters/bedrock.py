"""AWS Bedrock adapter — SigV4-signed ``InvokeModel`` over httpx (no boto3).

Billing flows to the DJ's own AWS account. Auth is AWS Signature V4 (not a
Bearer token), implemented manually in ``services/llm/sigv4.py`` so we add no
new dependency.

Per-family request/response handling, keyed off ``aws_model_id``:

- ``anthropic.*`` (Claude on Bedrock) — uses the Anthropic Messages body
  (``anthropic_version`` + ``messages`` + ``tools``), so it reuses the existing
  Anthropic tool-schema translation and response parser.
- ``meta.*`` / ``llama*`` (Llama on Bedrock) — uses the Llama prompt body.
  Llama has no structured tool field, so tools are described in the system
  prompt and tool calls are parsed out of the generated text.

Other families are rejected with a ``ToolTranslationError`` (clear message)
rather than guessing a body shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.time import utcnow
from app.services.llm.base import ChatRequest, ChatResponse, LlmAdapter, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.registry import register_adapter
from app.services.llm.sigv4 import sign_request
from app.services.llm.tool_translation import (
    parse_anthropic_response,
    parse_llama_response,
    render_llama_tool_instructions,
    to_anthropic_tools,
)

logger = logging.getLogger(__name__)

ANTHROPIC_BEDROCK_VERSION = "bedrock-2023-05-31"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0

FAMILY_ANTHROPIC = "anthropic"
FAMILY_LLAMA = "llama"


def model_family(model_id: str) -> str:
    """Map a Bedrock model id (or inference-profile id) to a request family."""
    mid = (model_id or "").lower()
    # Inference profiles prefix the region, e.g. "us.anthropic.claude-...".
    if "anthropic." in mid:
        return FAMILY_ANTHROPIC
    if "meta." in mid or "llama" in mid:
        return FAMILY_LLAMA
    raise ToolTranslationError(f"Unsupported Bedrock model family for model_id={model_id!r}")


class BedrockAdapter(LlmAdapter):
    connector_type = "bedrock"

    def _extract_credentials(self) -> dict[str, str]:
        raw = self.connector.credentials or ""
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthInvalid("Connector credentials are malformed") from exc
        if not isinstance(blob, dict):
            raise AuthInvalid("Connector credentials shape is invalid")
        for field in ("aws_access_key_id", "aws_secret_access_key", "aws_region", "aws_model_id"):
            if not blob.get(field):
                raise AuthInvalid(f"Connector is missing {field}")
        return {k: str(v) for k, v in blob.items()}

    def _resolve_model_id(self, request: ChatRequest, creds: dict[str, str]) -> str:
        # ChatRequest.model / model_hint override the stored aws_model_id.
        return request.model or self.connector.model_hint or creds["aws_model_id"]

    async def chat(self, request: ChatRequest) -> ChatResponse:
        creds = self._extract_credentials()
        model_id = self._resolve_model_id(request, creds)
        family = model_family(model_id)

        if family == FAMILY_ANTHROPIC:
            body, tool_names = self._build_anthropic_body(request)
        else:  # FAMILY_LLAMA
            body, tool_names = self._build_llama_body(request)

        payload = json.dumps(body).encode("utf-8")
        timeout = min(
            max(request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS, 1.0),
            MAX_TIMEOUT_SECONDS,
        )

        region = creds["aws_region"]
        host = f"bedrock-runtime.{region}.amazonaws.com"
        canonical_uri = f"/model/{model_id}/invoke"
        url = f"https://{host}{canonical_uri}"

        signed_headers = sign_request(
            access_key_id=creds["aws_access_key_id"],
            secret_access_key=creds["aws_secret_access_key"],
            region=region,
            host=host,
            canonical_uri=canonical_uri,
            body=payload,
            now=utcnow(),
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **signed_headers,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, content=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable("Upstream timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Upstream network error") from exc

        _raise_for_status(resp)

        try:
            response_body = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ToolTranslationError("Upstream returned non-JSON body") from exc

        if family == FAMILY_ANTHROPIC:
            parsed = parse_anthropic_response(response_body)
        else:
            parsed = parse_llama_response(response_body, tool_names=tool_names)
        # The Bedrock model id is the source of truth for telemetry — the
        # InvokeModel body doesn't reliably echo the full id.
        parsed.model = model_id
        return parsed

    async def health_check(self) -> None:
        ping = ChatRequest(
            messages=[Message(role="user", content="ping")],
            max_tokens=1,
            temperature=0.0,
        )
        await self.chat(ping)

    # -- Per-family request bodies -----------------------------------------
    def _build_anthropic_body(self, request: ChatRequest) -> tuple[dict, set[str] | None]:
        tools, choice = to_anthropic_tools(request.tools, request.force_tool)
        body: dict[str, Any] = {
            "anthropic_version": ANTHROPIC_BEDROCK_VERSION,
            "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
            "messages": self._anthropic_messages(request.messages),
        }
        if request.system:
            body["system"] = request.system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if tools:
            body["tools"] = tools
        if choice is not None:
            body["tool_choice"] = choice
        return body, None

    def _build_llama_body(self, request: ChatRequest) -> tuple[dict, set[str] | None]:
        tool_names = {t.name for t in request.tools} if request.tools else None
        tool_instructions = render_llama_tool_instructions(request.tools, request.force_tool)
        prompt = _render_llama_prompt(request, tool_instructions)
        body: dict[str, Any] = {"prompt": prompt}
        if request.max_tokens is not None:
            body["max_gen_len"] = request.max_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return body, tool_names

    @staticmethod
    def _anthropic_messages(messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            content = m.content
            if isinstance(content, list):
                text = "".join(getattr(b, "text", "") or "" for b in content)
            else:
                text = content or ""
            if m.role == "tool":
                if not m.tool_call_id:
                    raise ToolTranslationError("Tool message missing tool_call_id")
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": text,
                            }
                        ],
                    }
                )
                continue
            role = "assistant" if m.role == "assistant" else "user"
            out.append({"role": role, "content": text})
        return out


def _render_llama_prompt(request: ChatRequest, tool_instructions: str | None) -> str:
    """Render canonical messages into Llama 3's instruction-tuned chat format."""
    parts: list[str] = ["<|begin_of_text|>"]

    system_chunks: list[str] = []
    if request.system:
        system_chunks.append(request.system)
    if tool_instructions:
        system_chunks.append(tool_instructions)
    for m in request.messages:
        if m.role == "system":
            system_chunks.append(_message_text(m))
    if system_chunks:
        parts.append(
            "<|start_header_id|>system<|end_header_id|>\n\n"
            + "\n\n".join(system_chunks)
            + "<|eot_id|>"
        )

    for m in request.messages:
        if m.role == "system":
            continue
        role = "assistant" if m.role == "assistant" else "user"
        parts.append(f"<|start_header_id|>{role}<|end_header_id|>\n\n{_message_text(m)}<|eot_id|>")

    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


def _message_text(m: Message) -> str:
    content = m.content
    if isinstance(content, list):
        return "".join(getattr(b, "text", "") or "" for b in content)
    return content or ""


def _raise_for_status(resp: httpx.Response) -> None:
    if 200 <= resp.status_code < 300:
        return
    code = resp.status_code
    if code in (401, 403):
        raise AuthInvalid(f"Auth failed (HTTP {code})")
    if code == 402:
        raise QuotaExceeded("Quota or billing failure (HTTP 402)")
    # Bedrock throttling can arrive as 429, or as 400 with a ThrottlingException
    # error-type header. Treat both as rate-limited so callers back off.
    if code == 429 or (code == 400 and _is_throttle(resp)):
        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
        raise RateLimited("Rate limited (HTTP 429)", retry_after_seconds=retry_after)
    if 500 <= code < 600:
        raise ProviderUnavailable(f"Upstream error (HTTP {code})")
    raise ToolTranslationError(f"Upstream rejected request (HTTP {code})")


def _is_throttle(resp: httpx.Response) -> bool:
    """Bedrock signals throttling via the ``ThrottlingException`` error type.

    It can arrive as HTTP 429 or, on some paths, HTTP 400 with an
    ``x-amzn-errortype`` header. Detect both so callers back off correctly.
    """
    err_type = resp.headers.get("x-amzn-errortype") or resp.headers.get("X-Amzn-ErrorType") or ""
    return "throttl" in err_type.lower()


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


register_adapter("bedrock", BedrockAdapter)

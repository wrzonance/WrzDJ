"""Shared primitives for the httpx-backed LLM adapters.

Centralises three pieces that were copy-pasted across the OpenAI-wire, Gemini
and Bedrock adapters:

- ``parse_retry_after`` — HTTP ``Retry-After`` header → ``int`` seconds.
- ``raise_for_status`` — httpx status code → canonical typed exception.
- ``extract_api_key`` / ``extract_fixed_base_credentials`` — parse the encrypted
  ``{"api_key": "..."}`` credential blob.

The Anthropic adapter talks to the official SDK (``APIStatusError``), not httpx,
so it keeps its own status mapping; the two api-key extractors intentionally
differ in how they treat a non-dict blob (see ``extract_fixed_base_credentials``)
to preserve each adapter's established error message.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def raise_for_status(
    resp: httpx.Response,
    *,
    throttle_detector: Callable[[httpx.Response], bool] | None = None,
) -> None:
    """Map a non-2xx httpx response to a canonical adapter exception.

    ``throttle_detector`` lets Bedrock treat an HTTP 400 carrying a
    ``ThrottlingException`` error-type header as rate-limiting; the default
    ``None`` preserves the plain OpenAI/Gemini mapping.
    """
    if 200 <= resp.status_code < 300:
        return

    code = resp.status_code
    if code in (401, 403):
        raise AuthInvalid(f"Auth failed (HTTP {code})")
    if code == 402:
        raise QuotaExceeded("Quota or billing failure (HTTP 402)")
    if code == 429 or (code == 400 and throttle_detector is not None and throttle_detector(resp)):
        retry_after = parse_retry_after(resp.headers.get("Retry-After"))
        raise RateLimited("Rate limited (HTTP 429)", retry_after_seconds=retry_after)
    if 500 <= code < 600:
        raise ProviderUnavailable(f"Upstream error (HTTP {code})")
    # 4xx other than the above → treat as a malformed input / translation error
    # since the gateway only emits known shapes.
    raise ToolTranslationError(f"Upstream rejected request (HTTP {code})")


def extract_api_key(raw: str) -> str:
    """Parse an ``{"api_key": "..."}`` credential blob → bare api key.

    Used by the OpenAI / Gemini / Anthropic api-key adapters. A non-dict blob
    falls through to the missing-key path (matching their established behaviour).
    """
    try:
        blob = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AuthInvalid("Connector credentials are malformed") from exc
    api_key = blob.get("api_key") if isinstance(blob, dict) else None
    if not api_key:
        raise AuthInvalid("Connector is missing an api_key")
    return str(api_key)


def extract_fixed_base_credentials(raw: str, base_url: str) -> tuple[str, str]:
    """Parse an ``{"api_key": "..."}`` blob for fixed-base-URL adapters.

    Used by xAI and OpenRouter, whose base URL is pinned (never user-supplied).
    Stricter than :func:`extract_api_key`: a non-dict blob raises
    ``"Connector credentials shape is invalid"`` rather than falling through.
    """
    try:
        blob = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AuthInvalid("Connector credentials are malformed") from exc
    if not isinstance(blob, dict):
        raise AuthInvalid("Connector credentials shape is invalid")
    api_key = blob.get("api_key")
    if not api_key:
        raise AuthInvalid("Connector is missing an api_key")
    return base_url, str(api_key)

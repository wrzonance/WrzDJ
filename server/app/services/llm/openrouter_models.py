"""OpenRouter model catalogue fetcher with an in-memory TTL cache.

OpenRouter publishes its full model catalogue at ``GET /api/v1/models`` (a
public, unauthenticated endpoint). The DJ "AI providers" page surfaces this as
a model-hint dropdown so DJs pick a valid namespaced model id ("provider/model")
instead of free-typing.

The catalogue changes rarely, so we cache it process-wide for one hour. The
cache is best-effort: on any fetch failure (network, timeout, malformed body)
we return the last good cache if present, otherwise an empty list. Callers
treat an empty list as "dropdown unavailable, fall back to free-text input".

No credentials are involved — the endpoint is public.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.schemas.ai_settings import AIModelInfo

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 3600.0  # refresh hourly
_FETCH_TIMEOUT_SECONDS = 10.0

# Process-wide cache: (fetched_at_monotonic, models)
_cache: tuple[float, list[AIModelInfo]] | None = None


def _now() -> float:
    return time.monotonic()


def _parse_models(body: object) -> list[AIModelInfo]:
    """Translate the OpenRouter /models payload into our AIModelInfo list.

    The payload shape is ``{"data": [{"id": "provider/model", "name": "..."}]}``.
    We defensively skip entries missing an ``id``.
    """
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if not isinstance(data, list):
        return []
    out: list[AIModelInfo] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id or not isinstance(model_id, str):
            continue
        name = entry.get("name")
        display = name if isinstance(name, str) and name else model_id
        out.append(AIModelInfo(id=model_id, name=display))
    return out


async def get_openrouter_models(*, force_refresh: bool = False) -> list[AIModelInfo]:
    """Return the OpenRouter model catalogue, served from cache when fresh.

    On fetch failure, returns the last good cache (even if stale) or an empty
    list. Never raises — the dropdown is a convenience, not a hard dependency.
    """
    global _cache

    if not force_refresh and _cache is not None:
        fetched_at, models = _cache
        if _now() - fetched_at < CACHE_TTL_SECONDS:
            return models

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
        resp.raise_for_status()
        body = resp.json()
    except Exception:  # noqa: BLE001 — best-effort, fall back to stale/empty
        logger.warning("Failed to fetch OpenRouter model catalogue")
        if _cache is not None:
            return _cache[1]
        return []

    models = _parse_models(body)
    if models:
        _cache = (_now(), models)
    elif _cache is not None:
        # Empty parse but we had a prior good list — keep serving it.
        return _cache[1]
    return models


def _reset_cache_for_tests() -> None:
    """Clear the module cache. Test-only helper."""
    global _cache
    _cache = None

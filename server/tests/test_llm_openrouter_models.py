"""Tests for the OpenRouter model-catalogue fetcher + TTL cache."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.services.llm import openrouter_models as om

_HTTPX_PATH = "app.services.llm.openrouter_models.httpx.AsyncClient"


class _AsyncClient:
    """Minimal httpx.AsyncClient stub supporting .get()."""

    def __init__(self, response: httpx.Response | Exception):
        self._response = response
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        self.calls += 1
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _models_body(*ids):
    return {"data": [{"id": i, "name": i.split("/")[-1]} for i in ids]}


def _ok(json_body):
    return httpx.Response(
        200,
        request=httpx.Request("GET", om.OPENROUTER_MODELS_URL),
        json=json_body,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    om._reset_cache_for_tests()
    yield
    om._reset_cache_for_tests()


@pytest.mark.asyncio
async def test_fetches_and_parses_models():
    client = _AsyncClient(_ok(_models_body("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet")))
    with patch(_HTTPX_PATH, return_value=client):
        models = await om.get_openrouter_models()
    ids = [m.id for m in models]
    assert ids == ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"]
    assert models[0].name == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_second_call_uses_cache_no_refetch():
    client = _AsyncClient(_ok(_models_body("openai/gpt-4o-mini")))
    with patch(_HTTPX_PATH, return_value=client):
        await om.get_openrouter_models()
        await om.get_openrouter_models()
    # Second call should be served from cache — only one HTTP fetch.
    assert client.calls == 1


@pytest.mark.asyncio
async def test_expired_cache_refetches():
    client = _AsyncClient(_ok(_models_body("openai/gpt-4o-mini")))
    with patch(_HTTPX_PATH, return_value=client):
        await om.get_openrouter_models()
        # Force the cache to look stale.
        fetched_at, models = om._cache
        om._cache = (fetched_at - om.CACHE_TTL_SECONDS - 1, models)
        await om.get_openrouter_models()
    assert client.calls == 2


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache():
    client = _AsyncClient(_ok(_models_body("openai/gpt-4o-mini")))
    with patch(_HTTPX_PATH, return_value=client):
        await om.get_openrouter_models()
        await om.get_openrouter_models(force_refresh=True)
    assert client.calls == 2


@pytest.mark.asyncio
async def test_fetch_failure_returns_empty_when_no_cache():
    client = _AsyncClient(httpx.TimeoutException("timeout"))
    with patch(_HTTPX_PATH, return_value=client):
        models = await om.get_openrouter_models()
    assert models == []


@pytest.mark.asyncio
async def test_fetch_failure_returns_stale_cache():
    good = _AsyncClient(_ok(_models_body("openai/gpt-4o-mini")))
    with patch(_HTTPX_PATH, return_value=good):
        await om.get_openrouter_models()

    # Now expire the cache and make the next fetch fail — stale cache served.
    fetched_at, models = om._cache
    om._cache = (fetched_at - om.CACHE_TTL_SECONDS - 1, models)
    bad = _AsyncClient(httpx.ConnectError("boom"))
    with patch(_HTTPX_PATH, return_value=bad):
        out = await om.get_openrouter_models()
    assert [m.id for m in out] == ["openai/gpt-4o-mini"]


@pytest.mark.asyncio
async def test_http_5xx_returns_empty_when_no_cache():
    resp = httpx.Response(
        503, request=httpx.Request("GET", om.OPENROUTER_MODELS_URL), json={"error": "down"}
    )
    client = _AsyncClient(resp)
    with patch(_HTTPX_PATH, return_value=client):
        models = await om.get_openrouter_models()
    assert models == []


@pytest.mark.asyncio
async def test_malformed_body_returns_empty():
    client = _AsyncClient(_ok({"unexpected": "shape"}))
    with patch(_HTTPX_PATH, return_value=client):
        models = await om.get_openrouter_models()
    assert models == []


@pytest.mark.asyncio
async def test_entries_missing_id_are_skipped():
    body = {"data": [{"name": "no id"}, {"id": "openai/gpt-4o-mini"}]}
    client = _AsyncClient(_ok(body))
    with patch(_HTTPX_PATH, return_value=client):
        models = await om.get_openrouter_models()
    assert [m.id for m in models] == ["openai/gpt-4o-mini"]

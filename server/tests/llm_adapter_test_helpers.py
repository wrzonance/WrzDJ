"""Shared transport helpers for LLM adapter contract tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx


def _make_openai_connector():
    return SimpleNamespace(
        connector_type="openai_apikey",
        credentials=json.dumps({"api_key": "sk-test-key-123456789012"}),
        model_hint="gpt-5-mini",
        base_url_plain=None,
    )


def _make_compatible_connector(base_url="http://127.0.0.1:11434/v1", bearer=None):
    creds = {"base_url": base_url, "bearer": bearer}
    return SimpleNamespace(
        connector_type="openai_compatible",
        credentials=json.dumps(creds),
        model_hint="llama3",
        base_url_plain=base_url,
    )


def _make_azure_connector(
    api_key="azure-secret-key",
    resource="my-resource",
    deployment="gpt4o",
    api_version="2024-06-01",
):
    creds = {
        "api_key": api_key,
        "azure_resource_name": resource,
        "azure_deployment_name": deployment,
        "azure_api_version": api_version,
    }
    return SimpleNamespace(
        connector_type="azure_openai",
        credentials=json.dumps(creds),
        model_hint=None,
        base_url_plain=None,
    )


def _make_openrouter_connector(model_hint="openai/gpt-4o-mini"):
    return SimpleNamespace(
        connector_type="openrouter_apikey",
        credentials=json.dumps({"api_key": "sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        model_hint=model_hint,
        base_url_plain=None,
    )


def _make_anthropic_connector():
    return SimpleNamespace(
        connector_type="anthropic_apikey",
        credentials=json.dumps({"api_key": "sk-ant-fake-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        model_hint="claude-haiku-4-5-20251001",
        base_url_plain=None,
    )


def _make_xai_connector(model_hint="grok-3-mini"):
    return SimpleNamespace(
        connector_type="xai_apikey",
        credentials=json.dumps({"api_key": "xai-fake-key-1234567890123456789012"}),
        model_hint=model_hint,
        base_url_plain=None,
    )


# Non-secret placeholder — avoids committing an "AIza…"-shaped literal that trips
# secret scanners. The adapter doesn't validate key shape (that's done upstream),
# so any string works for transport-level assertions.
_GEMINI_TEST_KEY = "gemini-test-key-not-a-real-secret"


def _make_gemini_connector(model_hint="gemini-2.5-flash"):
    return SimpleNamespace(
        connector_type="gemini_apikey",
        credentials=json.dumps({"api_key": _GEMINI_TEST_KEY}),
        model_hint=model_hint,
        base_url_plain=None,
    )


def _gemini_success_body(text="hi"):
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
        "modelVersion": "gemini-2.5-flash",
    }


def _openai_success_body(text="hi"):
    return {
        "model": "gpt-5-mini",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }


def _ok_response(json_body):
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
        json=json_body,
    )


class _AsyncClient:
    """Minimal httpx.AsyncClient stub for unit tests."""

    def __init__(self, response: httpx.Response | Exception):
        self._response = response
        self.calls: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

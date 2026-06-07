"""Tests for the provider-agnostic LLM gateway stub (Phase 0).

The gateway is the single surface WrzDJSet codes against. Phase 0 ships an
interface + a temporary delegating implementation. These tests pin the
interface shape and the normalization contract, NOT the live LLM.
"""

import ast
from pathlib import Path

import pytest

from app.services.llm import gateway


def test_gateway_response_shape():
    resp = gateway.GatewayResponse(tool_calls=[{"name": "x", "input": {}}], text="hi")
    assert resp.tool_calls == [{"name": "x", "input": {}}]
    assert resp.text == "hi"


def test_gateway_response_defaults():
    resp = gateway.GatewayResponse()
    assert resp.tool_calls == []
    assert resp.text == ""


def test_model_hint_literal_values_documented():
    # The two documented hints from the exec summary.
    assert gateway.MODEL_HINTS == ("fast", "strong")


@pytest.mark.asyncio
async def test_dispatch_normalizes_delegated_response(monkeypatch):
    """dispatch() returns a GatewayResponse normalized from the provider call."""

    class _FakeBlock:
        def __init__(self, type, **kw):
            self.type = type
            for k, v in kw.items():
                setattr(self, k, v)

    class _FakeResponse:
        content = [
            _FakeBlock("text", text="thinking"),
            _FakeBlock("tool_use", name="critique_set", input={"grade": "A"}),
        ]

    async def _fake_raw_call(*, model, system, tools, tool_choice, messages, max_tokens):
        # Assert the gateway passed a concrete model string (data, not import).
        assert isinstance(model, str) and model
        return _FakeResponse()

    monkeypatch.setattr(gateway, "_raw_provider_call", _fake_raw_call)

    result = await gateway.dispatch(
        messages=[{"role": "user", "content": "grade this set"}],
        tool={"name": "critique_set", "input_schema": {"type": "object"}},
        model_hint="strong",
    )
    assert isinstance(result, gateway.GatewayResponse)
    assert result.text == "thinking"
    assert result.tool_calls == [{"name": "critique_set", "input": {"grade": "A"}}]


def test_no_provider_sdk_import_in_gateway_module():
    """gateway.py must not import a provider SDK directly (anthropic/openai/etc.)."""
    src = Path(gateway.__file__).read_text()
    tree = ast.parse(src)
    banned = {"anthropic", "openai", "google", "cohere", "mistralai", "litellm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned

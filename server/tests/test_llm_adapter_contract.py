"""Adapter contract tests — parametrised over every registered adapter.

This test file defines the *public extension surface* for LLM adapters. Any
adapter (built-in or third-party plug-in) that subclasses ``LlmAdapter`` and
registers via :func:`register_adapter` must pass every test here.

The contract intentionally tests structural and exception-mapping invariants
only — it never makes network calls. Provider-specific HTTP and parsing
behaviour belongs in per-adapter test files (e.g. ``test_llm_adapters.py``,
``test_llm_bedrock_adapter.py``).

If you are adding a new adapter:

1. Register it via ``register_adapter("<connector_type>", YourClass)``.
2. Run this file: ``pytest tests/test_llm_adapter_contract.py``.
3. Every test must pass without modification.

If a test does *not* apply to your adapter, the right answer is to discuss it
in a PR — not to silently skip the contract. The contract is what lets the
gateway dispatch generically.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.services.llm.base import ChatRequest, LlmAdapter, Message
from app.services.llm.exceptions import AuthInvalid, LlmError
from app.services.llm.registry import get_adapter_class, list_connector_types


# ---------------------------------------------------------------------------
# Parametrisation — runs against every registered connector_type.
# ---------------------------------------------------------------------------
def _all_connector_types() -> list[str]:
    """Snapshot the registry at collection time.

    The registry is populated by ``app.services.llm.registry._bootstrap()``
    which eagerly imports the built-in adapters package. Any third-party
    adapter loaded via ``LLM_PLUGIN_DIR`` is also discovered here.
    """
    return list_connector_types()


@pytest.fixture
def malformed_connector():
    """A connector row whose ``credentials`` blob is not valid JSON.

    Every adapter must reject this without crashing, raising :class:`AuthInvalid`
    rather than leaking a ``JSONDecodeError`` or hitting the network.
    """
    return SimpleNamespace(
        connector_type="contract-test",
        credentials="this is not valid json",
        model_hint=None,
        base_url_plain=None,
    )


# ---------------------------------------------------------------------------
# Structural contract — class-level guarantees.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("connector_type", _all_connector_types())
def test_adapter_subclasses_llm_adapter(connector_type: str):
    """Every registered adapter must subclass the ``LlmAdapter`` ABC."""
    cls = get_adapter_class(connector_type)
    assert issubclass(cls, LlmAdapter), (
        f"{cls.__name__} is registered as {connector_type!r} but does not subclass LlmAdapter"
    )


@pytest.mark.parametrize("connector_type", _all_connector_types())
def test_adapter_declares_connector_type(connector_type: str):
    """Each adapter class must declare a non-empty ``connector_type`` attr.

    The registry uses this string to dispatch; an empty value would shadow
    every other adapter or fail in surprising ways.
    """
    cls = get_adapter_class(connector_type)
    assert getattr(cls, "connector_type", ""), (
        f"{cls.__name__} must set a class-level connector_type attribute"
    )
    # The class attribute must match the registration key. Otherwise an admin
    # toggling per-DJ MRU lookup will pull the wrong adapter for the row.
    assert cls.connector_type == connector_type, (
        f"{cls.__name__}.connector_type is {cls.connector_type!r} but "
        f"registered as {connector_type!r}"
    )


@pytest.mark.parametrize("connector_type", _all_connector_types())
def test_adapter_defines_chat_and_health_check(connector_type: str):
    """Both abstract methods must be implemented as async callables."""
    cls = get_adapter_class(connector_type)
    chat = getattr(cls, "chat", None)
    health = getattr(cls, "health_check", None)
    assert callable(chat), f"{cls.__name__}.chat must be defined"
    assert callable(health), f"{cls.__name__}.health_check must be defined"
    assert inspect.iscoroutinefunction(chat), (
        f"{cls.__name__}.chat must be `async def` — the gateway awaits it"
    )
    assert inspect.iscoroutinefunction(health), f"{cls.__name__}.health_check must be `async def`"


@pytest.mark.parametrize("connector_type", _all_connector_types())
def test_adapter_constructor_accepts_connector(connector_type: str):
    """Adapters are instantiated as ``cls(connector)`` by the gateway."""
    cls = get_adapter_class(connector_type)
    connector = SimpleNamespace(
        connector_type=connector_type,
        credentials="{}",
        model_hint=None,
        base_url_plain=None,
    )
    # Must not raise — credential decoding is deferred until chat()/health().
    instance = cls(connector)
    assert instance.connector is connector


# ---------------------------------------------------------------------------
# Exception contract — typed errors only, no provider leakage.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("connector_type", _all_connector_types())
async def test_adapter_raises_typed_error_on_malformed_credentials(
    connector_type: str, malformed_connector
):
    """An adapter handed a malformed credential blob must raise a typed
    :class:`LlmError` (specifically :class:`AuthInvalid`) — never a bare
    :class:`json.JSONDecodeError`, :class:`KeyError`, or a network exception.

    This is the boundary that keeps provider internals from leaking into
    API error responses.
    """
    cls = get_adapter_class(connector_type)
    adapter = cls(malformed_connector)
    request = ChatRequest(
        messages=[Message(role="user", content="ping")],
        max_tokens=1,
    )

    # We expect AuthInvalid (the most specific subtype). Some adapters with
    # additional credential fields might raise a different LlmError subclass —
    # accept any of them, but never a non-LlmError. The pytest.raises(LlmError)
    # context manager is the only assertion needed: a non-LlmError exception
    # would propagate out and fail the test.
    with pytest.raises(LlmError):
        await adapter.chat(request)


# ---------------------------------------------------------------------------
# Registry contract — third-party adapters reach the gateway via this path.
# ---------------------------------------------------------------------------
def test_registry_returns_classes_not_instances():
    """``get_adapter_class`` must return a *class*, not an instance.

    The gateway calls ``cls(connector)`` per dispatch; returning an instance
    here would silently share state across DJs.
    """
    for connector_type in _all_connector_types():
        cls = get_adapter_class(connector_type)
        assert inspect.isclass(cls), (
            f"Registry returned a non-class for {connector_type!r}: {cls!r}"
        )


def test_registry_lookup_raises_keyerror_for_unknown():
    """Unknown ``connector_type`` lookups raise :class:`KeyError`.

    The gateway relies on this to surface ``NoLlmConfigured`` cleanly.
    """
    with pytest.raises(KeyError):
        get_adapter_class("definitely-not-a-real-connector-type")


# ---------------------------------------------------------------------------
# Skeleton contract — proves the documented reference adapter satisfies the
# same surface as the built-in providers.
# ---------------------------------------------------------------------------
def _import_echo_adapter():
    """Import the docs-tree skeleton adapter as a regular module.

    The skeleton lives outside the ``app`` package (``docs/examples/``), so we
    register a one-off path entry to import it. We do this *inside* the test
    rather than at module load time so the registry stays clean for parametrised
    runs above (the skeleton is also asserted to register cleanly on import).
    """
    import importlib
    import os
    import sys

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return importlib.import_module("docs.examples.echo_adapter")


def test_skeleton_echo_adapter_satisfies_contract():
    """The documented skeleton must pass the same structural contract above.

    This is what guarantees the ``docs/LLM-PLUGIN.md`` "quick start" actually
    works — a third-party author copying the skeleton gets a registered,
    contract-compliant adapter without modifying any core file.
    """
    module = _import_echo_adapter()
    echo_cls = module.EchoAdapter

    # Same structural checks the parametrised tests above run, applied directly
    # so this test still fires when the skeleton is not pre-registered.
    assert issubclass(echo_cls, LlmAdapter)
    assert echo_cls.connector_type == "echo"
    assert inspect.iscoroutinefunction(echo_cls.chat)
    assert inspect.iscoroutinefunction(echo_cls.health_check)

    # Registry hit via the public surface.
    assert get_adapter_class("echo") is echo_cls


async def test_skeleton_echo_adapter_round_trip():
    """Smoke-test the echo skeleton end-to-end through ``chat()``.

    Importantly this avoids any network call — proving that the skeleton can
    be used as a deterministic stand-in for gateway tests.
    """
    module = _import_echo_adapter()
    connector = SimpleNamespace(
        connector_type="echo",
        credentials="{}",
        model_hint="echo-1",
        base_url_plain=None,
    )
    adapter = module.EchoAdapter(connector)
    request = ChatRequest(
        messages=[Message(role="user", content="hello world")],
        max_tokens=8,
    )
    response = await adapter.chat(request)
    assert response.text == "hello world"
    assert response.stop_reason == "end_turn"
    assert response.model == "echo-1"


async def test_skeleton_echo_adapter_health_check_validates_credentials():
    """``health_check()`` must raise :class:`AuthInvalid` for malformed creds."""
    module = _import_echo_adapter()
    connector = SimpleNamespace(
        connector_type="echo",
        credentials="not-json",
        model_hint=None,
        base_url_plain=None,
    )
    adapter = module.EchoAdapter(connector)
    with pytest.raises(AuthInvalid):
        await adapter.health_check()

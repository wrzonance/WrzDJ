"""Adapter registry — maps connector_type strings to adapter classes.

Importing the adapters package via ``from app.services.llm.adapters import *``
auto-registers each adapter via ``register_adapter``.
"""

from __future__ import annotations

from app.services.llm.base import LlmAdapter

_REGISTRY: dict[str, type[LlmAdapter]] = {}


def register_adapter(connector_type: str, cls: type[LlmAdapter]) -> None:
    """Register an adapter class for a connector_type.

    Re-registering the *same* class is a no-op (safe for re-imports during
    tests). Registering a *different* class for an already-bound
    ``connector_type`` raises :class:`ValueError` — silently overwriting
    adapters would make behavior depend on import order and hide collisions.
    """
    if not connector_type:
        raise ValueError("connector_type must be non-empty")
    if not issubclass(cls, LlmAdapter):
        raise TypeError("Adapter must subclass LlmAdapter")
    existing = _REGISTRY.get(connector_type)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"connector_type {connector_type!r} already registered by "
            f"{existing.__name__}; refusing to overwrite with {cls.__name__}"
        )
    _REGISTRY[connector_type] = cls


def get_adapter_class(connector_type: str) -> type[LlmAdapter]:
    """Return the adapter class for a connector_type or raise KeyError."""
    if connector_type not in _REGISTRY:
        raise KeyError(f"No adapter registered for connector_type={connector_type!r}")
    return _REGISTRY[connector_type]


def list_connector_types() -> list[str]:
    """Return all registered connector_type names (sorted, stable order)."""
    return sorted(_REGISTRY.keys())


def is_registered(connector_type: str) -> bool:
    """Cheap membership check, used by callers that wish to soft-validate."""
    return connector_type in _REGISTRY


# Eagerly import adapters to populate the registry. This avoids callers needing
# to remember an explicit "register" step.
def _bootstrap() -> None:
    # Local imports keep the registry module dependency-free at import time.
    from app.services.llm.adapters import (  # noqa: F401
        anthropic_apikey,
        azure_openai,
        openai_apikey,
        openai_compatible,
    )


_bootstrap()

"""Echo adapter — minimal reference implementation of ``LlmAdapter``.

This skeleton is the canonical "blank slate" for third-party LLM provider
plug-ins. It implements the full :class:`~app.services.llm.base.LlmAdapter`
contract without making any network calls — every request is echoed back as
the assistant message body.

Usage in tests::

    # Self-test against the contract — no production import.
    from docs.examples import echo_adapter  # noqa: F401  (side-effect: register)
    from app.services.llm.registry import get_adapter_class

    cls = get_adapter_class("echo")
    response = await cls(connector).chat(request)

Usage in production (third-party plug-ins)::

    # 1. Copy this file under any module path you control.
    # 2. Customize ``connector_type`` and the body of ``chat()``.
    # 3. Either:
    #    a) drop the .py file into the directory pointed to by ``LLM_PLUGIN_DIR``,
    #       or
    #    b) import the module from your own bootstrap code at startup.
    # 4. The :func:`register_adapter` call at the bottom binds the class to the
    #    registry the moment the module is imported.

See ``docs/LLM-PLUGIN.md`` for the full extension contract.

Security note: this skeleton intentionally does not validate or sanitise the
input it echoes. Real adapters must:
- Treat ``connector.credentials`` as untrusted (the encrypted blob can be
  malformed; raise :class:`AuthInvalid` rather than letting :class:`json.JSONDecodeError`
  bubble up).
- Translate upstream HTTP/SDK errors into the typed exception hierarchy
  (``AuthInvalid`` / ``RateLimited`` / ``QuotaExceeded`` / ``ProviderUnavailable``
  / ``ToolTranslationError``). Raw provider errors must not reach the caller.
- Never log secrets, full prompts, or completion bodies (the gateway only
  logs counts).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.llm.base import (
    ChatRequest,
    ChatResponse,
    ContentBlock,
    LlmAdapter,
    Message,
    TokenUsage,
)
from app.services.llm.exceptions import AuthInvalid
from app.services.llm.registry import register_adapter

logger = logging.getLogger(__name__)


class EchoAdapter(LlmAdapter):
    """An adapter that echoes the last user message back as the assistant reply.

    Useful for:
    - Wiring tests for the gateway / connector storage layer end-to-end
      without depending on a live provider.
    - Showing third-party plug-in authors the minimum required surface.
    """

    # The registry key for this adapter. Plug-in authors must change this to a
    # unique string before publishing — the registry refuses to register two
    # different classes under the same ``connector_type``.
    connector_type = "echo"

    # ------------------------------------------------------------------
    # Credential handling
    # ------------------------------------------------------------------
    def _read_credentials(self) -> dict[str, Any]:
        """Parse the encrypted credential blob, raising AuthInvalid on failure.

        The :class:`~app.models.llm_connector.LlmConnector` row stores
        credentials as an encrypted JSON string. Accessing ``self.connector.credentials``
        triggers decryption transparently via the ``EncryptedText`` column
        type. After that, parsing is the adapter's responsibility — and every
        failure mode here must surface as :class:`AuthInvalid` so the gateway
        can mark the connector and emit a clean audit event.
        """
        raw = self.connector.credentials or ""
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthInvalid("Connector credentials are malformed") from exc
        if not isinstance(blob, dict):
            raise AuthInvalid("Connector credentials shape is invalid")
        return blob

    # ------------------------------------------------------------------
    # LlmAdapter — required methods
    # ------------------------------------------------------------------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Echo the most recent user message back as the assistant reply.

        Real adapters should:
        - Translate ``request.messages`` to the provider's native message shape.
        - Call ``to_<provider>_tools(request.tools, request.force_tool)`` from
          ``app.services.llm.tool_translation`` to translate tools.
        - Call ``parse_<provider>_response(...)`` from that same module to
          translate the response back to ``ChatResponse``.
        - Map provider HTTP / SDK errors to the typed exception hierarchy.
        """
        # We deliberately read credentials before doing any echoing — that way
        # this skeleton exercises the same boundary (malformed creds raise
        # AuthInvalid) that real adapters depend on.
        self._read_credentials()

        last_user = next(
            (m for m in reversed(request.messages) if m.role == "user"),
            None,
        )
        if last_user is None:
            text = ""
        else:
            text = _flatten_message_text(last_user)

        return ChatResponse(
            text=text,
            tool_calls=[],
            stop_reason="end_turn",
            usage=TokenUsage(prompt=len(text.split()), completion=len(text.split())),
            # Surface the resolved model name (request override → connector hint
            # → adapter default) so call logs and recommendation telemetry stay
            # accurate. Real adapters should set this to the *provider-reported*
            # model id from the response payload, not the requested model.
            model=request.model or self.connector.model_hint or "echo-1",
        )

    async def health_check(self) -> None:
        """Validate the credential without exercising the (nonexistent) provider.

        Real adapters should issue a cheap, low-token call (e.g. ``max_tokens=1``)
        and raise the same typed exceptions as :meth:`chat`.
        """
        # No provider to ping — the credential parse step is enough proof that
        # the connector is wired correctly.
        self._read_credentials()


def _flatten_message_text(msg: Message) -> str:
    """Collapse a possibly-multi-block message to plain text.

    Real provider adapters typically keep the block structure; this skeleton
    flattens because a string return matches the simplest possible echo.
    """
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, ContentBlock):
            parts.append(block.text)
        elif isinstance(block, dict):
            parts.append(block.get("text") or "")
    return "".join(parts)


# The registry call here is what makes the skeleton "live" — importing this
# module registers the adapter under the ``connector_type`` declared above.
#
# Third-party plug-ins follow the same pattern. The registry refuses to bind
# the same ``connector_type`` to two different classes, so plug-in authors
# must pick a unique value (the ``LlmConnector.connector_type`` column is 40
# chars; keep it short, lowercase, snake-case, e.g. ``mistral_apikey``).
register_adapter(EchoAdapter.connector_type, EchoAdapter)

# LLM Adapter Plug-in Guide

The WrzDJ backend dispatches every LLM call through the **LLM Gateway**, which
selects a connector for the calling user and routes the request through a
provider-specific **adapter**. The set of adapters is open: forks and
third-party deployments can add new providers without modifying any file
under `server/app/services/llm/`.

This document is the contract that third-party plug-ins write against.

> Companion guide: [`docs/PLUGIN-ARCHITECTURE.md`](PLUGIN-ARCHITECTURE.md)
> describes the bridge-side equipment plug-in system. The LLM plug-in surface
> follows the same shape: a small ABC, a registry, and a strict typed-error
> contract.

## Architecture Overview

```
Caller (recommendation engine, agentic feature)
        │
        ▼
Gateway.dispatch(db, actor, request, *, purpose)
        │   1. Resolve LlmConnector (per-DJ MRU → org default)
        │   2. registry.get_adapter_class(connector_type)
        │   3. adapter = cls(connector); await adapter.chat(request)
        │   4. Log call + handle fallback policy
        ▼
LlmAdapter (your plug-in)
        │   1. Parse connector.credentials (encrypted JSON blob)
        │   2. Translate ChatRequest → provider-native request
        │   3. Translate provider response → ChatResponse
        │   4. Map provider errors → typed LlmError subclasses
        ▼
Provider HTTP endpoint / SDK
```

| Layer | File | Responsibility |
|-------|------|----------------|
| Adapter | `app/services/llm/adapters/*.py` (built-in) <br> `LLM_PLUGIN_DIR/*.py` (third-party) | Convert between canonical and provider-native shapes; map errors |
| Registry | `app/services/llm/registry.py` | `connector_type` → adapter class lookup |
| Tool translation | `app/services/llm/tool_translation.py` | JSON-Schema `ToolSpec` ↔ provider tool/function shape |
| Gateway | `app/services/llm/gateway.py` | Resolve connector, call adapter, log, handle fallback |
| Models | `app/models/llm_connector.py` | `LlmConnector` row (encrypted credentials), call log, audit log |
| Exceptions | `app/services/llm/exceptions.py` | Typed error hierarchy adapters must raise |

The connector row stores credentials as **encrypted JSON** via the
`EncryptedText` SQLAlchemy column type — accessing
`connector.credentials` returns the decrypted plaintext blob. Your adapter is
responsible for parsing that blob.

## The `LlmAdapter` ABC

Defined in [`app/services/llm/base.py`](../server/app/services/llm/base.py).

```python
class LlmAdapter(ABC):
    connector_type: str = ""  # set on the subclass — registry key

    def __init__(self, connector) -> None:
        self.connector = connector

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    @abstractmethod
    async def health_check(self) -> None: ...
```

### Required Class Attribute: `connector_type`

A short, lowercase, snake-case string. The DB column that stores it is 40
characters; pick something unique and stable (e.g. `mistral_apikey`,
`groq_apikey`, `local_vllm`). The registry **refuses to bind the same
`connector_type` to two different classes** — that prevents silent shadowing
of built-in adapters.

### Required Method: `chat()`

| Property | Contract |
|----------|----------|
| Coroutine | Yes — `async def`. The gateway always awaits. |
| Input | A canonical `ChatRequest`. |
| Output | A canonical `ChatResponse`. |
| Errors | One of the typed `LlmError` subclasses (see below). Never a raw HTTP / SDK exception. |
| Side effects | None other than the upstream network call. Do **not** mutate the connector row. |
| Logging | Do not log full prompts, completions, or any credential material. |

### Required Method: `health_check()`

Validate the credential against the provider. The gateway calls this from the
admin "Test connector" path. Returns `None` on success; raises the same typed
exceptions as `chat()` on failure.

Pattern: issue the cheapest possible call (e.g. `max_tokens=1`). The shared
helper `build_healthcheck_request()` in
`app/services/llm/adapters/_httpx_openai.py` is reusable for OpenAI-shaped
endpoints.

## Canonical Types

Defined in [`app/services/llm/base.py`](../server/app/services/llm/base.py).
These are **stable** Pydantic models — fields may be added in a minor release
but never renamed or removed without a major-version bump.

### `ChatRequest`

| Field | Type | Notes |
|-------|------|-------|
| `messages` | `list[Message]` | Required. `role ∈ {"system", "user", "assistant", "tool"}`. Tool messages carry `tool_call_id`. |
| `tools` | `list[ToolSpec] \| None` | JSON-Schema shape. Translate via `tool_translation.to_*_tools()`. |
| `force_tool` | `str \| None` | Forces a specific tool name; raise `ToolTranslationError` if not in `tools`. |
| `max_tokens` | `int \| None` | Adapters supply a default if `None`. |
| `temperature` | `float \| None` | Pass through verbatim when not `None`. |
| `model` | `str \| None` | Overrides `connector.model_hint`. |
| `timeout_seconds` | `float \| None` | Adapters MAY clamp to a max. |
| `system` | `str \| None` | Provider-native system prompt. Map to the right surface (OpenAI: first system message; Anthropic: top-level `system`). |
| `fallback_policy` | `Literal["none", "org_default", "retry_then_org_default"]` | Handled by the gateway, not the adapter. Ignore. |

### `ChatResponse`

| Field | Type | Notes |
|-------|------|-------|
| `text` | `str` | The textual assistant reply. Empty string if the model only emitted tool calls. |
| `tool_calls` | `list[ToolCall]` | Empty list when no tools were called. |
| `stop_reason` | `Literal["end_turn", "tool_use", "max_tokens", "error"]` | Required. Map from the provider's native stop reason. |
| `usage` | `TokenUsage \| None` | Counts only — never prompt content. Optional. |
| `model` | `str \| None` | Provider-reported model id (for telemetry). Recommended. |

### `ToolSpec`, `ToolCall`, `Message`

See the source. `ToolSpec.input_schema` is a JSON-Schema dict;
`tool_translation.py` knows how to translate it for OpenAI / Anthropic /
Bedrock and parse the response back into canonical `ToolCall` objects.
Reuse those helpers rather than reimplementing them per adapter.

## Exception Contract

Defined in [`app/services/llm/exceptions.py`](../server/app/services/llm/exceptions.py).
Every error from the adapter must be one of these. The gateway translates
them into telemetry, audit events, and HTTP response codes; raw provider
errors **must not** reach the caller (they often contain bearer tokens in
error messages — a credential-leak vector).

| Exception | When to raise | Status hint |
|-----------|---------------|-------------|
| `AuthInvalid` | Credentials are malformed, missing, or rejected (`401`/`403`). Includes "failed to parse the credential JSON". | Marks connector `status="auth_invalid"`; writes audit event. |
| `RateLimited(retry_after_seconds=...)` | Provider returned `429`. Pass through `Retry-After` if present. | Gateway logs and surfaces as `429` to the caller. |
| `QuotaExceeded` | Billing failure (`402`) or provider-specific quota error. | Logged, surfaced as `402` to caller. |
| `ProviderUnavailable` | `5xx`, network failure, timeout, generic SDK error. | Logged, surfaced as `502`. Eligible for fallback. |
| `ToolTranslationError` | Unable to translate input tools or parse the response. | Logged, surfaced as `502`. **Not** a fallback trigger. |
| `NoLlmConfigured` | **Gateway-only.** Adapters should not raise this. | – |

### Mapping example (OpenAI HTTP shape)

```python
status = response.status_code
if status in (401, 403):
    raise AuthInvalid(f"Auth failed (HTTP {status})")
if status == 402:
    raise QuotaExceeded("Quota or billing failure")
if status == 429:
    retry = response.headers.get("retry-after")
    raise RateLimited("Rate limited", retry_after_seconds=int(float(retry)) if retry else None)
if 500 <= status < 600:
    raise ProviderUnavailable(f"Upstream error (HTTP {status})")
# 4xx other than the above → almost certainly a translation problem.
raise ToolTranslationError(f"Upstream rejected request (HTTP {status})")
```

## Tool Translation

The canonical `ToolSpec` is JSON-Schema. Adapters should delegate to
[`app/services/llm/tool_translation.py`](../server/app/services/llm/tool_translation.py)
rather than re-implementing the conversion. The module exposes:

| Helper | Direction |
|--------|-----------|
| `to_openai_tools(tools, force)` | Canonical → OpenAI `tools` + `tool_choice` |
| `parse_openai_response(payload)` | OpenAI body → `ChatResponse` |
| `to_anthropic_tools(tools, force)` | Canonical → Anthropic `tools` + `tool_choice` |
| `parse_anthropic_response(message)` | Anthropic SDK message → `ChatResponse` |
| `to_bedrock_tools(tools, force)` | Canonical → Bedrock Converse `toolConfig` |
| `parse_bedrock_response(payload)` | Bedrock body → `ChatResponse` |

Adding a new translation pair for a provider whose tool shape genuinely
differs is allowed — open a PR adding helpers under the same naming
convention. Until then, do not silently re-shape tools inside your adapter.

## Registration

Register the adapter as the **last statement** of your module:

```python
register_adapter(MyAdapter.connector_type, MyAdapter)
```

That call:

- Validates the class subclasses `LlmAdapter`.
- Rejects empty `connector_type`.
- Rejects double-binding (a different class trying to take an already-bound
  key — surfaced as `ValueError` at startup).

Re-registering the *same* class is a no-op (safe for test re-imports).

## Loading Third-Party Plug-ins

There are two supported mechanisms:

1. **Import from your own code.** Add the file to your fork of the backend
   and ensure it gets imported at startup (e.g. add it to the
   `app/services/llm/registry.py::_bootstrap` block, or import it from
   `app/main.py`). This is the recommended path for forks.

2. **`LLM_PLUGIN_DIR` env var.** Set the environment variable to a directory
   path. At startup the loader
   ([`app/services/llm/plugin_loader.py`](../server/app/services/llm/plugin_loader.py))
   imports every `*.py` file in that directory (non-recursive; files starting
   with `_` are skipped). Each plug-in is responsible for calling
   `register_adapter()` on import. A broken plug-in is logged with a full
   stack trace and skipped — it does **not** prevent the rest of the directory
   or the backend itself from starting.

### Security posture for `LLM_PLUGIN_DIR`

Loading a plug-in grants it the **full privileges of the backend process**.
There is no sandbox; this is the same trust boundary as `pip install`.
Operators must:

- Treat the plug-in directory as a privileged path. Only the backend's
  service account should have write access to it.
- Audit every plug-in's source the same way they would audit a third-party
  Python dependency.
- Never set `LLM_PLUGIN_DIR` to a world-writable or multi-tenant path.

In production we recommend leaving `LLM_PLUGIN_DIR` unset and packaging
trusted plug-ins as ordinary Python modules. The env-var loader exists to
make local experimentation and forks ergonomic.

## Stable vs Internal API

The plug-in surface is **the surface listed in this document**. Everything
else under `app/services/llm/` is internal — including helper modules,
private functions, and adapter base-class internals not enumerated above.

| Surface | Stability |
|---------|-----------|
| `LlmAdapter` ABC method signatures (`chat`, `health_check`, `connector_type`) | **Stable.** Breaking change → major version bump. |
| `ChatRequest`, `ChatResponse`, `Message`, `ToolSpec`, `ToolCall`, `TokenUsage` field names + types | **Stable.** Field additions in minor versions; never renames/removals without a major bump. |
| Exception types and their constructor signatures | **Stable.** |
| `register_adapter`, `get_adapter_class`, `list_connector_types`, `is_registered` | **Stable.** |
| `tool_translation.to_*_tools` / `parse_*_response` | **Stable** for the providers documented above. |
| `_httpx_openai`, `url_validator`, `connector_storage` | **Internal.** Reuse at your own risk; may change without notice. |
| `gateway.dispatch` internals (fallback, logging, audit) | **Internal.** Callers must use the public `Gateway.dispatch` entrypoint. |
| `LlmConnector` ORM model | **Internal.** Adapters touch only `connector.credentials`, `connector.model_hint`, and `connector.base_url_plain`. |

Schema changes to the `LlmConnector` storage shape (encrypted JSON blob keys)
are versioned by `connector_type`. Each provider chooses its own blob keys
in its own migration; the only invariant is that **the blob is a JSON object**.

## Test Matrix

Every registered adapter — built-in or third-party — must pass the
parametrised contract tests in
[`server/tests/test_llm_adapter_contract.py`](../server/tests/test_llm_adapter_contract.py).
The contract covers:

1. The class subclasses `LlmAdapter`.
2. `connector_type` is non-empty and matches the registration key.
3. `chat` and `health_check` are async callables.
4. The constructor accepts a connector row without raising.
5. `chat()` raises `AuthInvalid` (or another `LlmError`) for malformed
   credential blobs — never a raw `JSONDecodeError`, `KeyError`, or HTTP
   exception.
6. The registry returns classes (not instances) and raises `KeyError` on
   unknown lookups.

Adapter-specific HTTP and parsing behaviour belongs in a separate test file
(see the built-in adapters' tests in `test_llm_adapters.py` for the pattern).

Run the contract test against your adapter:

```bash
cd server
.venv/bin/pytest tests/test_llm_adapter_contract.py
```

If a contract test fails on your adapter, **fix the adapter** — do not
modify the contract. The contract is what lets the gateway dispatch
generically.

## Reference Skeleton

The minimum working adapter lives at
[`docs/examples/echo_adapter.py`](examples/echo_adapter.py). It is exercised
by `test_skeleton_echo_adapter_*` in the contract test file, so any change
that breaks the documented surface fails CI immediately.

## Adding a Plug-in in 5 Minutes

```bash
# 1. Copy the skeleton.
cp docs/examples/echo_adapter.py /opt/wrzdj/llm_plugins/mistral_apikey.py

# 2. Edit it:
#    - Change `connector_type` to a unique value (e.g. "mistral_apikey").
#    - Replace the echo body with your provider call.
#    - Map provider errors to the typed exceptions.

# 3. Point the backend at the plug-in directory.
export LLM_PLUGIN_DIR=/opt/wrzdj/llm_plugins
uvicorn app.main:app

# 4. Verify the registry sees it.
python -c "from app.services.llm.registry import list_connector_types; print(list_connector_types())"

# 5. Run the contract tests.
cd server && .venv/bin/pytest tests/test_llm_adapter_contract.py
```

Once your adapter is registered, DJs can create a connector row via
`POST /api/llm/connectors` with `connector_type="mistral_apikey"` and the
gateway will route their requests through your adapter automatically.

# Admin AI OAuth & Provider-Agnostic LLM Gateway — Design Spec

- **Date:** 2026-05-24
- **Author:** thewrz
- **Status:** Final, project created in Github, ready for implementation.
- **Branch:** `worktree-feat+admin-ai-oauth`
- **Related memory:** `[[llm-oauth-gateway]]`, `[[feedback-litellm-avoid]]`
- **Replaces:** hardcoded `ANTHROPIC_API_KEY` env-var pathway in `server/app/services/recommendation/llm_client.py`

---

## 1. Overview

WrzDJ today routes all LLM calls through a single hardcoded Anthropic API key set via the `ANTHROPIC_API_KEY` env var. Only the recommendation engine (`services/recommendation/llm_client.py`) consumes it. This spec expands LLM access to:

1. Multiple provider types behind a provider-agnostic dispatch gateway
2. Per-DJ credentials (each DJ connects their own accounts)
3. Admin org policy controls (which connector types are allowed, org default)
4. Encrypted-at-rest credential storage following the existing Beatport/Tidal OAuth pattern

The spec defines the MVP that ships v1, and lists deferred work to be tracked via GitHub issues under a new milestone and Kanban project.

## 2. Goals & Non-Goals

### Goals

- Provider-agnostic dispatch usable by current and future agentic features (recommendation engine, set-builder, etc.) without hardcoding any vendor
- Three working connector types in MVP: OpenAI API key, Anthropic API key, Custom OpenAI-compatible endpoint URL
- Per-DJ self-service connect/disconnect/test UI
- Admin policy UI: enable/disable connector types, set org default, force-revoke any DJ's connector, view usage
- Recommendation engine migrated to the gateway with zero observable behavior change for existing Anthropic users
- DJs who want to use their ChatGPT Plus/Pro subscription are routed to a Hermes-Agent onboarding path (custom-URL connector + DJ runs Hermes locally)
- Security-forward defaults: encrypted-at-rest creds, sanitized errors, audit trail, validated URLs, rate-limited mutation endpoints

### Non-Goals (MVP)

- Server-side ChatGPT-subscription OAuth (no public OpenAI client-registration program exists; reusing Hermes' client_id is a ToS violation — see Decision Log §3.1)
- Server-side Claude.ai web-subscription OAuth (banned by Anthropic per Feb 2026 ToS update)
- Streaming responses (gateway returns complete `ChatResponse` only)
- Auto-fallback between connectors when one fails (caller decides)
- Cost / quota caps per DJ
- Additional providers beyond the three MVP types (Gemini, xAI Grok, Bedrock, Azure OpenAI, OpenRouter, Groq, Together, etc.)
- LLM call retry policies in the gateway
- Per-feature connector preference (e.g., recommendation always uses connector X)
- Browser-based OAuth redirect flow for any provider
- LLM-provider plug-in SDK for third-party adapters

Deferred items are enumerated in §10 as GH issue mini-specs.

## 3. Decision Log

### 3.1 Server-side ChatGPT-subscription OAuth dropped from MVP

OpenAI's ChatGPT-subscription OAuth flow is implemented in Hermes Agent using hardcoded `CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"` and token endpoint `https://auth.openai.com/oauth/token`, with inference at `https://chatgpt.com/backend-api/codex`. Verified via [hermes-agent/hermes_cli/auth.py](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/auth.py) lines 112-114.

OpenAI does not publish a public OAuth-app registration program for ChatGPT-subscription quota access. Replicating the flow in WrzDJ requires reusing Hermes' client_id, which (a) impersonates another OAuth app, (b) lets OpenAI revoke our DJs' inference access at any time, (c) likely violates OpenAI's ToS in spirit. The risk applies to DJs (account bans), not just to WrzDJ as an org.

**Decision:** drop the server-side connector. Provide a Hermes onboarding path via the Custom-URL connector instead — the DJ runs Hermes locally, WrzDJ never touches OpenAI's OAuth chain.

### 3.2 Approach A: per-provider adapter classes

Picked over (B) single dispatch with conditionals or (C) LiteLLM wrapper. Reasons:

- Pattern parity with `services/sync/` and `bridge/src/plugins/`
- Each adapter unit-testable in isolation
- Headline complex code (subscription-OAuth, if ever revisited) lives in one file
- No heavy new dep (CLAUDE.md CVE-vigilance rule)
- LiteLLM banned per `[[feedback-litellm-avoid]]` (supply-chain compromise; broad coverage = broad attack surface)

### 3.3 Per-DJ dispatch (not system-wide single connector)

Each LLM call resolves to the actor DJ's most-recently-used active connector; falls back to the admin-set org default; raises `NoLlmConfigured` if neither. Matches ChatGPT-subscription economics (a $20/mo Plus account is one user's), and is the model DJs intuitively expect.

### 3.4 Migrate recommendation engine in MVP

Building connectors without migrating any consumer ships dark code; the gateway interface won't be exercised until later, risking interface flaws discovered under deadline. The recommendation engine port adds modest scope and validates the design end-to-end.

### 3.5 Provider-native tool-use with translation

Recommendation engine uses Anthropic's forced `tool_use` for structured-output JSON. Stripping this for "text-only" loses the strict-schema enforcement that prevents malformed recommendations. Canonical `ToolSpec` (JSON Schema) → per-provider translation preserves the property.

### 3.6 No new heavy deps

`httpx` (already in tree) is sufficient for OpenAI and OpenAI-compatible adapters. The existing `anthropic` SDK stays for the Anthropic adapter. No `openai` SDK, no `litellm`.

## 4. Architecture

### 4.1 Module layout

```
server/app/services/llm/
├── __init__.py
├── gateway.py              # Entry: Gateway.dispatch(db, actor, request, *, purpose) -> ChatResponse
├── base.py                 # LlmAdapter ABC + ChatRequest / ChatResponse / ToolSpec types
├── registry.py             # connector_type -> adapter class lookup
├── tool_translation.py     # canonical JSON-Schema tools <-> per-provider format
├── connector_storage.py    # SQLAlchemy CRUD helpers for LlmConnector
├── exceptions.py           # AuthInvalid, ProviderUnavailable, RateLimited, etc.
└── adapters/
    ├── __init__.py
    ├── openai_apikey.py            # OpenAI Platform API key
    ├── openai_compatible.py        # Custom base URL + optional bearer (Hermes / LiteLLM / Ollama / vLLM / LMStudio)
    └── anthropic_apikey.py         # Anthropic API key (replaces hardcoded env var)

server/app/models/
└── llm_connector.py        # LlmConnector + LlmCallLog + LlmAuditEvent

server/app/api/
├── llm.py                  # /api/llm/connectors  CRUD (per-DJ self-service)
├── admin_llm.py            # /api/admin/llm/*     org policy, force-revoke, usage
└── (oauth route file intentionally omitted — no OAuth flows in MVP)

dashboard/app/
├── settings/ai/page.tsx    # Per-DJ: connect / disconnect / test
└── admin/ai/page.tsx       # Admin: enable connector types, ToS disclosure, usage, revoke

server/alembic/versions/
└── XXX_admin_ai_oauth.py   # llm_connectors + llm_call_log + llm_audit_event + system_settings additions + ANTHROPIC_API_KEY data migration
```

### 4.2 Data model

```python
# server/app/models/llm_connector.py

class LlmConnector(Base):
    __tablename__ = "llm_connectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connector_type: Mapped[str] = mapped_column(String(40), index=True)
    # "openai_apikey" | "openai_compatible" | "anthropic_apikey"

    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="active")
    # "active" | "auth_invalid" | "disabled"

    credentials: Mapped[str] = mapped_column(EncryptedText)
    # apikey:     {"api_key": "..."}
    # compatible: {"base_url": "...", "bearer": "..." | null}

    base_url_plain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_hint: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "connector_type", "display_name", name="uq_dj_connector_label"),
        Index("ix_user_active", "user_id", "status"),
    )


class LlmCallLog(Base):
    """Per-call telemetry. Counts only — never prompt/completion content."""
    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("llm_connectors.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20))
    # "ok" | "auth_invalid" | "rate_limited" | "quota_exceeded" | "provider_unavailable" | "tool_translation_error"
    latency_ms: Mapped[int]
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class LlmAuditEvent(Base):
    """Security-relevant credential lifecycle events."""
    __tablename__ = "llm_audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_connector_id: Mapped[int | None] = mapped_column(ForeignKey("llm_connectors.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    # "connector_created" | "connector_credentials_rotated" | "connector_deleted"
    # | "connector_revoked_by_admin" | "auth_invalid_observed" | "policy_changed"
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

`SystemSettings` additions:

```python
llm_apikey_connectors_enabled: bool = True
llm_compatible_connector_enabled: bool = True
llm_default_connector_id: int | None = None  # FK to LlmConnector
```

Alembic migration creates the three tables, adds the three `system_settings` columns, and runs a data migration that converts `ANTHROPIC_API_KEY` env var into an `anthropic_apikey` connector owned by the first admin user, then sets it as `llm_default_connector_id`. The migration uses `op.get_bind()` + ORM session + the `LlmConnector` model so `EncryptedText`'s TypeDecorator runs on insert.

### 4.3 Gateway dispatch

```python
# services/llm/gateway.py
class Gateway:
    @staticmethod
    async def dispatch(
        db: Session,
        actor: User | None,          # the DJ on whose behalf we call; None = system context
        request: ChatRequest,
        *,
        purpose: str,                # "recommendation" | "set_builder" | "admin_test" | ...
    ) -> ChatResponse:
        connector = _resolve_connector(db, actor)
        adapter = registry.get(connector.connector_type)(connector)
        started = monotonic()
        try:
            resp = await adapter.chat(request)
        except AuthInvalid:
            connector.status = "auth_invalid"
            db.commit()
            _log_call(db, connector, purpose, "auth_invalid", monotonic() - started, None, None, "401")
            _audit(db, actor, connector, "auth_invalid_observed")
            raise
        except RateLimited as e:
            _log_call(db, connector, purpose, "rate_limited", monotonic() - started, None, None, str(e.retry_after_seconds))
            raise
        except ProviderUnavailable as e:
            _log_call(db, connector, purpose, "provider_unavailable", monotonic() - started, None, None, str(e))
            raise
        connector.last_used_at = func.now()
        db.commit()
        _log_call(db, connector, purpose, "ok", monotonic() - started, resp.usage.prompt, resp.usage.completion, None)
        return resp
```

Resolution order in `_resolve_connector`:

1. If `actor` is not `None`: `SELECT * FROM llm_connectors WHERE user_id=actor.id AND status='active' ORDER BY last_used_at DESC NULLS LAST LIMIT 1` → return if found
2. `SystemSettings.llm_default_connector_id` if set and status=`active` → return
3. Raise `NoLlmConfigured`

### 4.4 Canonical types

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentBlock]
    tool_call_id: str | None = None     # for role="tool" replies

class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict                  # JSON Schema (canonical)

class ChatRequest(BaseModel):
    messages: list[Message]
    tools: list[ToolSpec] | None = None
    force_tool: str | None = None       # name of a tool to force-call
    max_tokens: int | None = None
    temperature: float | None = None
    model: str | None = None            # overrides connector.model_hint

class ToolCall(BaseModel):
    id: str
    name: str
    input: dict

class ChatResponse(BaseModel):
    text: str
    tool_calls: list[ToolCall] = []
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "error"]
    usage: TokenUsage | None = None

class TokenUsage(BaseModel):
    prompt: int
    completion: int
```

### 4.5 Tool translation

```python
# services/llm/tool_translation.py

def to_openai(tools: list[ToolSpec], force: str | None) -> tuple[list, dict | None]:
    fns = [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
        for t in tools
    ]
    choice = {"type": "function", "function": {"name": force}} if force else None
    return fns, choice


def to_anthropic(tools: list[ToolSpec], force: str | None) -> tuple[list, dict | None]:
    anthropic_tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
    choice = {"type": "tool", "name": force} if force else None
    return anthropic_tools, choice
```

Each adapter holds its own parser that converts the provider's response shape back to canonical `ChatResponse` (including `tool_calls`).

### 4.6 Typed exceptions

```python
class LlmError(Exception): ...
class NoLlmConfigured(LlmError): ...        # no active connector + no system default
class AuthInvalid(LlmError): ...            # 401 — connector marked auth_invalid
class RateLimited(LlmError):
    retry_after_seconds: int | None
class QuotaExceeded(LlmError): ...          # 402 / billing failure
class ProviderUnavailable(LlmError): ...    # 5xx / network — transient
class ToolTranslationError(LlmError): ...   # canonical schema couldn't be translated or parsed back
```

### 4.7 Custom-URL connector + Hermes onboarding

The OpenAI-compatible adapter is the most flexible MVP connector — it works with any tool exposing an OpenAI-format `/chat/completions` endpoint. DJs who want to use their ChatGPT Plus/Pro subscription run [Hermes Agent](https://github.com/NousResearch/hermes-agent) locally and paste the proxy URL into Settings → AI.

URL validation (`validate_compatible_base_url`):

- Scheme: only `http` or `https`
- `http`: only loopback (127.0.0.1, ::1, localhost) and RFC1918 ranges (10.x, 172.16-31.x, 192.168.x)
- `https`: any host
- Reject embedded creds (`user:pass@host`)
- Accept optional path prefix (e.g., `/v1`) since some OpenAI-compatible servers expect it; preserve it on the stored base URL. The adapter appends `/chat/completions` (and other endpoints) to whatever is stored. Reject query and fragment — strip and warn at validation time.

UI copy when DJ picks `openai_compatible`:

> **Want to use your ChatGPT Plus / Pro subscription?**
> Install [Hermes Agent](https://github.com/NousResearch/hermes-agent), run `hermes proxy`, and paste the URL it prints below. Your ChatGPT account never leaves your machine — WrzDJ only talks to your local Hermes proxy.

No WrzDJ-bundled binary, no install automation. Pure docs link.

## 5. UI Surfaces

### 5.1 Per-DJ: `/settings/ai`

Auth: `get_current_active_user` (any DJ, not pending).

- **Connected** list: card per connector with `display_name`, type badge, status badge, `last_used_at`, `model_hint`. Actions: Test, Edit, Rotate credentials, Delete.
- **Add connector** button → modal:
  - Type select (filtered by `SystemSettings.llm_*_enabled` flags)
  - Fields per type:
    - `openai_apikey`: API key (password input), model_hint (default `gpt-5-mini`)
    - `anthropic_apikey`: API key, model_hint (default `claude-opus-4-7`)
    - `openai_compatible`: base_url, bearer (optional, password input), model_hint
  - "Save & test" — runs health check before persisting; rejects on failure with sanitized error
- **Use ChatGPT subscription?** collapsible (only when `openai_compatible` enabled): Hermes onboarding copy from §4.7

### 5.2 Admin: `/admin/ai`

Auth: `get_current_admin`. Sidebar entry under existing admin nav.

Four cards:

1. **Connector policy** — checkboxes:
   - "Allow API-key connectors (OpenAI, Anthropic)" → `llm_apikey_connectors_enabled`
   - "Allow custom OpenAI-compatible endpoints" → `llm_compatible_connector_enabled`
2. **Org default connector** — dropdown of all active connectors across all DJs (label: `dj_username — display_name (type)`). Used when a system-context call has no DJ actor.
3. **Per-DJ connectors** — table: dj_username, type, display_name, status, last_used, [Force-revoke]. Force-revoke sets `status="disabled"` and writes an audit event.
4. **Usage** — last 30 days. Bar chart by purpose. Table: connector_id, total_calls, total_tokens_in, total_tokens_out, error_rate. CSV export.

### 5.3 Backend routes

```
# Per-DJ self-service — server/app/api/llm.py
GET    /api/llm/connectors                   # list mine
POST   /api/llm/connectors                   # create (rate-limited 5/min)
PATCH  /api/llm/connectors/{id}              # rename, model_hint (no creds rotation)
PUT    /api/llm/connectors/{id}/credentials  # rotate creds (rate-limited 5/min, audited)
POST   /api/llm/connectors/{id}/test         # health check (rate-limited 10/min)
DELETE /api/llm/connectors/{id}              # own only

# Admin — server/app/api/admin_llm.py
GET    /api/admin/llm/policy
PATCH  /api/admin/llm/policy
GET    /api/admin/llm/connectors             # all DJs
POST   /api/admin/llm/connectors/{id}/revoke
GET    /api/admin/llm/usage?days=30
```

All per-DJ endpoints return `404` for connector IDs the DJ doesn't own. No 403/404 leak. Admin endpoints bypass ownership scoping.

### 5.4 Frontend API client

`dashboard/lib/api.ts` adds: `listLlmConnectors()`, `createLlmConnector()`, `updateLlmConnector()`, `rotateLlmConnectorCredentials()`, `testLlmConnector()`, `deleteLlmConnector()`, `getAdminLlmPolicy()`, `updateAdminLlmPolicy()`, `listAllLlmConnectors()`, `revokeAdminLlmConnector()`, `getAdminLlmUsage(days)`. All use `this.fetch()` (auth required).

## 6. Security Posture

### 6.1 Credentials at rest

`LlmConnector.credentials` uses the existing `EncryptedText` TypeDecorator (Fernet AES-128-CBC + HMAC) — same path as Beatport/Tidal OAuth tokens. `TOKEN_ENCRYPTION_KEY` is already a required env var in production. No new encryption scheme. Bearer field inside the `credentials` JSON is encrypted as part of the blob, never separated. `base_url_plain` is the only plaintext URL column and exists only to render an admin list without decrypting; it contains no credentials.

### 6.2 Credentials in transit

OpenAI Platform and Anthropic endpoints are always HTTPS. The custom-URL connector enforces scheme/host validation: `http://` allowed only for loopback and RFC1918. URLs with embedded credentials are rejected (bearer goes in the encrypted blob, never the URL).

### 6.3 Input validation

- API key regex: `^sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}$` (OpenAI — covers user, project, service-account, and admin key prefixes), `^sk-ant-[A-Za-z0-9_-]{30,}$` (Anthropic). Format check only — backend `health_check` validates against the upstream.
- `display_name`: max 80 chars, no control characters
- `model_hint`: max 80 chars, `[A-Za-z0-9._-]`
- Pydantic schemas use `StrictStr` / constrained types

### 6.4 Error message sanitization

`health_check` and `Gateway.dispatch` return typed enums / exceptions only. Upstream error bodies, stack traces, and bearer values never reach the response. Frontend maps enums to human copy via a whitelist.

### 6.5 Multi-tenant isolation

- All per-DJ endpoints scope queries by `user_id = current_user.id` server-side
- No client-supplied `user_id` accepted
- Force-revoke is admin-only and audited
- DJ's connector list never includes other DJs' rows

### 6.6 Prompt injection from LLM responses

- `ChatResponse.text` is never rendered as HTML / executable
- `tool_calls[].input` validated against the canonical JSON Schema before passing to a tool executor
- LLM-returned URLs treated as untrusted (per CLAUDE.md "fetched untrusted content" rule)

### 6.7 Audit logging

- `llm_call_log`: counts only — no prompt/completion content. 30-day retention. Daily cleanup job.
- `llm_audit_event`: credential lifecycle events for security investigation. Indefinite retention.

### 6.8 Rate limiting

Slowapi (existing pattern):

- `POST /api/llm/connectors`: `5/minute`
- `POST /api/llm/connectors/{id}/test`: `10/minute`
- `PUT /api/llm/connectors/{id}/credentials`: `5/minute`

Per-DJ + per-IP keys. Upstream provider rate limits propagated as typed `RateLimited` with `retry_after_seconds`; gateway never auto-retries.

### 6.9 Dependency posture

- No new external packages
- `httpx`: already in tree
- `anthropic`: already in tree (used by `anthropic_apikey` adapter)
- No `openai` SDK — `openai_apikey` and `openai_compatible` share an httpx-based code path
- No `litellm` — banned per `[[feedback-litellm-avoid]]`
- `pip-audit` clean required before merge

### 6.10 Bandit / ruff exceptions

- `Authorization: Bearer {token}` header construction triggers `B106` — suppress with `# nosec B106`
- No `eval`, no `exec`, no `subprocess` shell strings

### 6.11 Disclosure copy

Admin policy panel footnote:

> WrzDJ stores your provider credentials encrypted at rest. Calls to LLM providers consume your account's quota or API billing directly. WrzDJ never shares credentials between DJs.

No grey-area ToS disclosure is required because server-side ChatGPT-subscription OAuth was dropped (§3.1).

## 7. Recommendation-Engine Migration

`services/recommendation/llm_client.py` is the only existing consumer of the env-var Anthropic key. Migration replaces direct `anthropic.Client` calls with `Gateway.dispatch(db, actor=event.owner, request, purpose="recommendation")`. The forced `tool_use` semantics carry through:

- `ChatRequest(force_tool="rank_recommendations", tools=[ToolSpec(name="rank_recommendations", ...)])`
- Anthropic adapter: passes through nearly identically
- OpenAI adapter: translates to `tool_choice={"type": "function", "function": {"name": "rank_recommendations"}}`

Behavior after migration must be identical for an existing Anthropic-using event. The regression test `test_recommendation_via_gateway.py` asserts identical output on fixture data.

### Env-var deprecation

Alembic migration runs a one-shot ORM data migration: read `ANTHROPIC_API_KEY` env var, if present, create an `anthropic_apikey` connector owned by the first admin user (default `display_name="Org Default (migrated from env var)"`), set as `llm_default_connector_id`. Idempotent — skips if a connector with that name exists.

After the migration ships, `ANTHROPIC_API_KEY` env var is marked deprecated in `.env.example` (with a comment). A follow-up release removes env-var reads from code (tracked as a GH issue per §10).

## 8. Testing Strategy

### Backend

- `server/tests/services/llm/test_gateway.py`: resolution order, `last_used_at` updates, exception types
- `server/tests/services/llm/test_adapter_*.py`: each adapter mocked with `httpx_mock`. Happy path + 401 → AuthInvalid, 429 → RateLimited, 5xx → ProviderUnavailable, timeout → ProviderUnavailable, malformed JSON → ToolTranslationError
- `server/tests/services/llm/test_tool_translation.py`: ToolSpec → OpenAI/Anthropic round-trip; force_tool semantics; ChatResponse parse for both
- `server/tests/services/llm/test_compatible_url_validator.py`: HTTPS, http loopback, http public rejected, embedded creds rejected
- `server/tests/api/test_llm_connectors.py`: CRUD, ownership scoping (404 on others'), credentials rotation audit, rate limits
- `server/tests/api/test_admin_llm.py`: role-gated, force-revoke audit, usage rollup
- `server/tests/recommendation/test_recommendation_via_gateway.py`: regression — identical output via gateway vs legacy path

### Frontend

- `dashboard/app/settings/ai/page.test.tsx`: form respects policy, "Save & test" surfaces health enum, delete confirmation
- `dashboard/app/admin/ai/page.test.tsx`: policy PATCH (optimistic + rollback), force-revoke audit surfaced, CSV export contains no PII

### CI

- `alembic upgrade head && alembic check` — passes
- `pip-audit` — clean
- Coverage: backend 85% (per existing threshold), frontend per existing
- `ruff check / ruff format --check / bandit` — clean

## 9. Acceptance Criteria

MVP ships when all hold:

1. All 3 connector types CRUD + test + delete work end-to-end (per-DJ + admin views)
2. Admin policy toggles take effect immediately (no restart)
3. Recommendation engine produces identical fixtures-output via the gateway as it did via the env-var path
4. `ANTHROPIC_API_KEY` env var data-migrated into a connector on first deploy; subsequent code never reads the env var
5. `pip-audit` clean, `alembic check` clean, 85% backend coverage, 0 ruff/bandit errors
6. Manual test: DJ runs `hermes proxy` locally, pastes URL into Settings → AI → Custom OpenAI-compatible endpoint, "Test" reports OK, recommendation engine produces output via that connector
7. Audit events written for every credential lifecycle event (create, rotate, delete, admin-revoke, auth-invalid)

## 10. Implementation Directive

This spec is the work-order for an implementation agent (likely via `superpowers:executing-plans` + `superpowers:subagent-driven-development`).

### 10.1 Phase 1: Build the MVP

The implementer agent must:

1. Read this spec in full before touching code
2. Confirm it is working on branch `worktree-feat+admin-ai-oauth` (or equivalent feature branch — never `main`)
3. Read `CLAUDE.md` (project root) for branch strategy, commit format, CI checks, deploy workflow
4. Read related memory: `[[llm-oauth-gateway]]`, `[[feedback-litellm-avoid]]`
5. Use `superpowers:writing-plans` to produce a phased implementation plan from this spec
6. Use `superpowers:subagent-driven-development` for the build itself, dispatching parallel sub-agents where the work is independent:
   - Sub-agent A: data model + Alembic migration + env-var data migration
   - Sub-agent B: gateway + base types + tool_translation + registry + exceptions
   - Sub-agent C: each adapter (per-provider; can fan out further)
   - Sub-agent D: backend API routes (`api/llm.py` + `api/admin_llm.py`)
   - Sub-agent E: frontend pages + API client
   - Sub-agent F: recommendation-engine migration + regression test
   - Sub-agent G: documentation updates (`CLAUDE.md` adds new env vars / new endpoints; `docs/` may need a new HUMAN-VERIFICATION-style doc for LLM connectors)
7. Each sub-agent prompt must include the branch-safety template from `~/.claude/rules/agents.md` (read CLAUDE.md, never commit to main, branch name)
8. After all sub-agents finish, run full local CI (the "push to testing" workflow from MEMORY.md) and only then push + open PR
9. Honor all acceptance criteria in §9 before marking the MVP complete

### 10.2 Phase 2: File deferred items as GitHub issues

The implementer agent must, **before opening the MVP PR**:

1. Create a new GitHub milestone titled exactly **`AI Engine Back-end Redesign`** (description: this spec's URL + a sentence summary)
2. Create a new GitHub Project (org-level or repo-level, whichever matches existing project conventions) using a Kanban template. Required columns:
   - `Backlog`
   - `Ready to Implement`
   - `In Progress`
   - `In Review`
   - `Complete`
3. Wire the milestone to the project so issues auto-appear
4. File one GitHub issue per deferred item in §11 below. Each issue:
   - Title format: `[AI Engine] <short feature title>`
   - Labels: `enhancement`, `ai-engine`
   - Milestone: `AI Engine Back-end Redesign`
   - Body: the mini-spec from §11 (purpose, scope, acceptance criteria, dependencies on other issues)
5. Move all freshly-filed issues into the `Backlog` column
6. Move the MVP-PR's own tracking issue (created by the implementer for the MVP) into `In Progress`

The implementer can use `gh issue create`, `gh project`, and `gh api` for all of this. Use HEREDOCs for issue bodies to preserve markdown formatting (existing CLAUDE.md convention).

## 11. Deferred Items — GitHub Issue Mini-Specs

Each item below is one GitHub issue, milestone `AI Engine Back-end Redesign`.

### 11.1 Issue: Add Gemini provider adapter

**Purpose:** Let DJs connect Google Gemini (API key path) alongside OpenAI/Anthropic.

**Scope:** New `adapters/gemini_apikey.py` implementing the `LlmAdapter` ABC. Tool translation for Gemini's `function_declarations` schema. Validation regex for Gemini API key format. Update connector-type filter on frontend.

**Acceptance criteria:** Adapter passes the same test matrix as OpenAI/Anthropic adapters. Recommendation engine works against Gemini when chosen. Admin policy gains `llm_gemini_apikey_enabled` flag.

**Depends on:** MVP merged.

---

### 11.2 Issue: Add xAI Grok provider adapter

**Purpose:** Support xAI Grok via API key (and possibly subscription OAuth if/when xAI publishes a registration program).

**Scope:** `adapters/xai_apikey.py`. xAI uses an OpenAI-compatible chat-completions surface, so this may largely subclass `OpenAICompatibleAdapter` with a fixed `base_url` and provider-specific error mapping.

**Acceptance criteria:** Connector CRUD + test + dispatch works. Tool-use translation validated.

**Depends on:** MVP merged.

---

### 11.3 Issue: Add OpenRouter provider adapter

**Purpose:** OpenRouter is a meta-provider routing to many models with one API key. Useful for DJs who want broad model access with a single connection.

**Scope:** OpenRouter is OpenAI-compatible — can be implemented as a thin specialization of `OpenAICompatibleAdapter` with `base_url="https://openrouter.ai/api/v1"`. Add `openrouter_apikey` connector type for clearer UX (DJs may not realize they could use the compatible adapter).

**Acceptance criteria:** Connector saved with OpenRouter-specific model_hint dropdown. Cost-of-call mapping documented.

**Depends on:** MVP merged.

---

### 11.4 Issue: Add Azure OpenAI provider adapter

**Purpose:** Enterprise DJs / venues with Azure subscriptions.

**Scope:** Azure OpenAI uses a different URL scheme (per-deployment endpoint) and a different auth header (`api-key` not `Authorization: Bearer`). Cannot share the OpenAI compatible code path directly. New `adapters/azure_openai.py`.

**Acceptance criteria:** Adapter works against an Azure OpenAI test deployment. Deployment-name field added to connector schema.

**Depends on:** MVP merged.

---

### 11.5 Issue: Add Bedrock provider adapter

**Purpose:** AWS Bedrock access for users with AWS-billed inference.

**Scope:** AWS SigV4 auth (not bearer). Likely needs `boto3` dep (CLAUDE.md CVE check required). Decide whether to add it or stay httpx-only with manual SigV4. New `adapters/bedrock.py`.

**Acceptance criteria:** Adapter validated against Bedrock Claude/Anthropic and Bedrock Llama. Region field added to connector schema.

**Depends on:** MVP merged.

---

### 11.6 Issue: Add streaming response support to gateway

**Purpose:** Long-running LLM calls (set-builder, long recommendation lists) benefit from streamed responses for better UX.

**Scope:** Add `Gateway.stream(...)` returning `AsyncIterator[ChatResponseChunk]`. Each adapter implements streaming variant. Frontend consumer (recommendation UI, set-builder UI) updates to consume SSE.

**Acceptance criteria:** Streaming works for OpenAI, Anthropic, and OpenAI-compatible adapters. Tool-use mid-stream handled correctly. Cancellation propagates upstream.

**Depends on:** MVP merged.

---

### 11.7 Issue: Per-DJ explicit default connector toggle

**Purpose:** MVP uses "most-recently-used active connector wins". Some DJs want explicit pinning (e.g., always use OpenAI for recommendations, Anthropic for set-builder).

**Scope:** Add `is_default: bool` column to `LlmConnector` (per-DJ unique). UI toggle on the per-DJ page. Gateway resolution updated.

**Acceptance criteria:** Setting a default sticks; unsetting falls back to MRU; only one default per DJ.

**Depends on:** MVP merged.

---

### 11.8 Issue: Per-feature connector preference

**Purpose:** Same as 11.7 but at feature granularity (recommendation always uses connector X, set-builder always uses connector Y).

**Scope:** New `LlmFeaturePreference` model (`user_id`, `feature`, `connector_id`). Gateway resolution checks feature preference before MRU. UI adds a "Per-feature defaults" section.

**Acceptance criteria:** DJ can pin a connector per feature. Falls back to per-DJ default → MRU → org default → error.

**Depends on:** 11.7 merged.

---

### 11.9 Issue: Auto-fallback policy in gateway

**Purpose:** If a DJ's chosen connector fails mid-event (rate limited, auth expired), optionally fall back to the org default automatically.

**Scope:** `ChatRequest.fallback_policy: Literal["none", "org_default", "retry_then_org_default"]`. Gateway implements the fallback chain. Audit event records the fallback.

**Acceptance criteria:** Tested with a connector that returns 429 → falls back to org default. Audit event written. Caller can opt out.

**Depends on:** MVP merged.

---

### 11.10 Issue: Cost / quota caps per DJ

**Purpose:** Admin can set monthly token caps per DJ; gateway refuses calls that would exceed the cap.

**Scope:** Add `monthly_token_cap` to `LlmConnector`. Daily/monthly aggregation in `llm_call_log`. Gateway checks cap before dispatch; raises `QuotaCapReached`. Admin UI shows usage vs cap.

**Acceptance criteria:** Cap enforced; DJ sees clear error; admin sees usage gauge.

**Depends on:** MVP merged.

---

### 11.11 Issue: Background connector health monitor

**Purpose:** Catch expired / revoked connectors before a DJ tries to use them in the middle of an event.

**Scope:** Scheduled task (every N hours) hits each active connector's `health_check`. On failure, sets `status=auth_invalid` and notifies the DJ (email or in-app banner).

**Acceptance criteria:** Stale connector detected within N hours. DJ notified.

**Depends on:** MVP merged.

---

### 11.12 Issue: Audit-trail admin UI tab

**Purpose:** MVP ships the `llm_audit_event` table but no UI. This issue adds the admin tab to browse events.

**Scope:** Admin page tab "Audit" with filterable table (event type, actor, target). CSV export.

**Acceptance criteria:** Admin can view all events in the past N days. Filter by event type works.

**Depends on:** MVP merged.

---

### 11.13 Issue: Configurable `llm_call_log` retention

**Purpose:** MVP hardcodes 30-day retention. Org may want longer or shorter.

**Scope:** Add `llm_call_log_retention_days` to `SystemSettings`. Admin UI control. Daily cleanup job reads from settings.

**Acceptance criteria:** Admin can change retention; cleanup honors it.

**Depends on:** MVP merged.

---

### 11.14 Issue: Remove deprecated `ANTHROPIC_API_KEY` env-var reads

**Purpose:** Follow-up cleanup after the MVP data migration. Remove env-var fallback from `settings.py`, `recommendation/llm_client.py`, `.env.example`, and CLAUDE.md.

**Scope:** Single PR. Grep for `ANTHROPIC_API_KEY`, delete fallback paths, update docs.

**Acceptance criteria:** No code reads `ANTHROPIC_API_KEY`. CI green. Deployment unaffected (connector data already migrated).

**Depends on:** MVP merged + ≥ 1 production deploy that runs the data migration.

---

### 11.15 Issue: LLM-provider plug-in SDK for third-party adapters

**Purpose:** Let community / forks add new providers without modifying core. Mirrors `bridge/src/plugins/` extensibility.

**Scope:** Document the `LlmAdapter` ABC + `registry` API as a public extension surface. Add an example skeleton adapter under `docs/`. Optional: load adapters from a configurable path on startup.

**Acceptance criteria:** Docs published. Skeleton adapter compiles and registers.

**Depends on:** MVP merged + at least 2 production adapters added post-MVP (validates the abstraction).

---

### 11.16 Issue: Browser-redirect OAuth flow when any provider publishes a public registration program

**Purpose:** If OpenAI, Anthropic, Google, or any other provider publishes a public OAuth-app registration program for subscription-quota access, WrzDJ can ship a native "Connect ChatGPT" / "Connect Claude" button.

**Scope:** Add OAuth-redirect adapter pattern (state cookie, callback route, encrypted refresh token storage). Reuse existing Beatport PKCE machinery as a template. New `adapters/<provider>_oauth.py` per provider.

**Acceptance criteria:** Spec gates implementation start until a public registration program exists. Tracking only until then.

**Depends on:** External — public provider registration program.

---

### 11.17 Issue: Surface connector "Test" health-check results in admin "Per-DJ connectors" table

**Purpose:** MVP admin table shows last_used_at but not last_health_check. Useful for triage.

**Scope:** Add `last_health_check_at` and `last_health_check_status` columns. Update admin table.

**Acceptance criteria:** Admin can see when each connector was last verified and the result.

**Depends on:** MVP merged.

---

## 12. Open Questions

None at spec close. All scoping forks resolved in §3 Decision Log.

## 13. References

- [Hermes Agent v0.14.0 release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.5.16)
- [hermes-agent/hermes_cli/auth.py](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/auth.py) — source of the OpenAI Codex OAuth constants referenced in §3.1
- WrzDJ existing patterns: `services/sync/` (plugin/adapter), `models/base.py` (EncryptedText), `api/admin.py` (admin auth), `services/system_settings.py` (DB-backed settings singleton)
- `[[llm-oauth-gateway]]` — cross-worktree work commitment to provider-agnostic dispatch
- `[[feedback-litellm-avoid]]` — supply-chain compromise; do not add LiteLLM as a dep

# Remove deprecated ANTHROPIC_API_KEY env-var reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the now-dead legacy `ANTHROPIC_API_KEY` env-var fallback path in the recommendation engine, since the LLM Gateway connector system has been the source of truth for credentials since the MVP.

**Architecture:** Every production caller of `call_llm` / `generate_llm_suggestions` passes `db` + `actor`, so the gateway path always runs and the `_legacy_call` direct-Anthropic fallback (and its `anthropic_api_key` / `anthropic_max_tokens` / `anthropic_timeout_seconds` config reads) is dead code. We delete that fallback, the unused config fields, and refresh the legacy unit test to drive the gateway path instead. We deliberately KEEP `config.anthropic_api_key` and `config.anthropic_model` because the admin AI-settings/model-listing endpoints and the recommendation response `llm_model` default still read them — removing those is a cross-cutting frontend+API-contract change out of scope for this backend cleanup.

**Tech Stack:** Python 3.11+, FastAPI, pydantic-settings, pytest.

---

## Design decisions (scope reconciliation)

The issue's literal grep target is the **uppercase env-var name** `ANTHROPIC_API_KEY`. In non-test code that string appears only in:
- `server/alembic/versions/046_admin_ai_oauth.py` — historical one-shot data migration. **MUST stay** (allowable exception).
- `server/app/services/recommendation/llm_hooks.py:78` — a docstring mention of the dead fallback. **Removed** here.

The actual env-var *reads* go through the pydantic-settings attribute `config.anthropic_api_key` (lowercase). Mapping every read:

| Location | What it does | Decision |
|---|---|---|
| `llm_client._legacy_call` | direct-Anthropic fallback when `db is None` | **REMOVE** — dead; all callers pass `db` |
| `llm_client._resolve_max_tokens` | reads `anthropic_max_tokens` for gateway `ChatRequest.max_tokens` | **KEEP the cap, drop the config dependency** — inline the `1024` default |
| `llm_hooks.is_llm_available` final fallback | `bool(get_settings().anthropic_api_key)` | **REMOVE** — gateway connector check is authoritative |
| `admin._list_anthropic_models` / `/ai/settings` | live admin observability of the legacy key | **KEEP** — powers admin UI + API contract + frontend tests; out of scope |
| `events.py:986` | `result.llm_model or get_settings().anthropic_model` display default | **KEEP** — `anthropic_model` is a model-name default, not a credential fallback |

Config fields:
- `anthropic_max_tokens`, `anthropic_timeout_seconds` → **REMOVE** (only the deleted `_legacy_call` / `_resolve_max_tokens` used them).
- `anthropic_api_key`, `anthropic_model` → **KEEP** (still read by admin + events display).

---

## File Structure

- `server/app/services/recommendation/llm_client.py` — delete `_legacy_call`, the `AsyncAnthropic` import, the `db is None` branch; inline max-tokens default.
- `server/app/services/recommendation/llm_hooks.py` — drop the `db is None` env-var fallback and the docstring `ANTHROPIC_API_KEY` mention; tighten `is_llm_available` to require `db`.
- `server/app/core/config.py` — remove `anthropic_max_tokens`, `anthropic_timeout_seconds`.
- `server/tests/test_llm_client.py` — replace the `AsyncAnthropic`-patching legacy tests with gateway-path tests.
- `server/tests/test_llm_hooks.py` — drop the env-var-availability assertions.
- `.env.example` — drop the deprecated `ANTHROPIC_*` lines (keep nothing that's dead).
- `CLAUDE.md` — update the Environment section + LLM Gateway note.

---

### Task 1: Remove the dead `_legacy_call` fallback in `llm_client.py`

**Files:**
- Modify: `server/app/services/recommendation/llm_client.py`
- Test: `server/tests/test_llm_client.py`

- [ ] **Step 1: Rewrite `TestCallLLM` to drive the gateway path**

Replace the two `AsyncAnthropic`-patching tests with tests that pass a fake `db` and patch `Gateway.dispatch`, asserting the parse + trim behavior.

- [ ] **Step 2: Run to verify they fail** (`call_llm` still has the `db is None` branch / `Gateway` not yet the sole path)

Run: `.venv/bin/pytest tests/test_llm_client.py -q`

- [ ] **Step 3: Edit `llm_client.py`**
  - Remove `from anthropic import AsyncAnthropic`.
  - Remove the `if db is None: result = await _legacy_call(...)` branch — make the gateway path unconditional; raise/parse via gateway always.
  - Delete `_legacy_call`.
  - Replace `_resolve_max_tokens()` body to return a module constant default (`DEFAULT_MAX_TOKENS = 1024`) instead of `get_settings().anthropic_max_tokens`.
  - Remove the now-unused `get_settings` import if nothing else uses it.

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_llm_client.py -q` → PASS

- [ ] **Step 5: Commit**

### Task 2: Tighten `is_llm_available` in `llm_hooks.py`

**Files:**
- Modify: `server/app/services/recommendation/llm_hooks.py`
- Test: `server/tests/test_llm_hooks.py`

- [ ] **Step 1: Update `test_llm_hooks.py`** — remove the two assertions that `is_llm_available()` (no db) keys off `anthropic_api_key`; keep/adjust the db-based connector tests. `is_llm_available()` with no db now returns `False`.
- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Edit `llm_hooks.py`** — drop the final `bool(get_settings().anthropic_api_key)` fallback (both the `db is not None` tail and the no-db return → `False`); remove the `ANTHROPIC_API_KEY` docstring bullet and the `db is None` env-var sentence in `generate_llm_suggestions`; remove the now-unused `get_settings` import.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit.**

### Task 3: Remove dead config fields

**Files:**
- Modify: `server/app/core/config.py`

- [ ] **Step 1: Remove `anthropic_max_tokens` and `anthropic_timeout_seconds`** from the `Settings` class. Keep `anthropic_api_key` and `anthropic_model` (still used by admin + events).
- [ ] **Step 2: Grep** `grep -rn "anthropic_max_tokens\|anthropic_timeout" server/app` → zero hits.
- [ ] **Step 3: Commit.**

### Task 4: Docs + env example

**Files:**
- Modify: `.env.example`, `CLAUDE.md`

- [ ] **Step 1: `.env.example`** — remove the deprecated `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_MAX_TOKENS` / `ANTHROPIC_TIMEOUT_SECONDS` lines and rewrite the surrounding comment to state credentials are connector-only.
- [ ] **Step 2: `CLAUDE.md`** — update the Anthropic env-var line in the Environment section and the LLM Gateway note (legacy fallback removed).
- [ ] **Step 3: Commit.**

### Task 5: Full backend CI + acceptance grep

- [ ] `cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q`
- [ ] `grep -rn "ANTHROPIC_API_KEY" server/ | grep -v /tests/` → only the alembic migration hits remain.
- [ ] `.venv/bin/alembic upgrade head && .venv/bin/alembic check` (config field removal must not drift).

# Admin AI Policy: Org Connector + Legacy Surface Removal

**Date:** 2026-06-09
**Author:** thewrz (design session with Claude)
**Branch:** `feat/org-llm-connector`
**Status:** Approved design, pending implementation plan

## Problem

Testing feedback surfaced two intertwined problems on `/admin/ai`:

1. **Legacy Anthropic env-var surface.** The "API Key Status" panel reads
   `bool(config.anthropic_api_key)` (`server/app/api/admin.py:388-406`) — an
   env var with **zero runtime role** since #343. The recommendation engine
   resolves credentials exclusively through LLM connectors. The panel is
   Anthropic-only, reports the status of a credential nothing uses, and sits
   next to the connector policy that actually matters. The companion
   model-listing endpoint (`GET /api/admin/ai/models`,
   `server/app/api/admin.py:351-385`) is equally Anthropic-only, and
   `SystemSettings.llm_model` / `ANTHROPIC_MODEL` survive only as display
   labels (the gateway uses each connector's `model_hint`).

2. **Billing-identity gap in the org default.** `_resolve_connector`
   (`server/app/services/llm/gateway.py:423-472`) falls back to
   `SystemSettings.llm_default_connector_id` for **any DJ without an active
   connector** — and that setting can point at any DJ's *personal* connector.
   A DJ with no connector silently burns another DJ's API credits, and audit
   attribution lands on the connector owner (`_system_actor_id`,
   `gateway.py:485-492`). Separately, the global `llm_enabled` toggle
   (`SystemSettings.llm_enabled`, enforced in `is_llm_available`,
   `server/app/services/recommendation/llm_hooks.py:67-113`) blocks LLM
   recommendations for **all** DJs — including DJs paying with their own
   tokens.

## Decisions

| Question | Decision |
|---|---|
| Who can be the org-wide fallback connector? | **Dedicated org connector** — owned by the organization itself, never a DJ account |
| Schema shape | **Same table + `scope` column** — `llm_connectors.scope ∈ {'user','org'}`, `user_id` nullable, CHECK `(scope='org') = (user_id IS NULL)` |
| Fate of global `llm_enabled` | **Rescoped to org fallback only** — gates whether connector-less DJs (and system-context calls) may use the org connector; BYO DJs are never blocked |
| Legacy env-var surface | **Removed entirely** — panel, models endpoint, `api_key_*` fields, `llm_model` setting, `ANTHROPIC_MODEL` response-label fallback |

## 1. Data model & migration

- `llm_connectors`:
  - Add `scope: Mapped[str]` — `String(10)`, NOT NULL, server default `'user'`.
  - `user_id` becomes nullable (`NULL` ⇔ org-scoped row).
  - CHECK constraint: `(scope = 'org') = (user_id IS NULL)`.
- `system_settings`:
  - Drop `llm_model` column (display-only; nothing at runtime consults it).
  - `llm_enabled` column **keeps its name**; its enforced meaning becomes
    "org-connector fallback allowed". UI copy carries the semantics.
  - `llm_default_connector_id` stays, but is only valid pointing at an
    active `scope='org'` connector (validated at API layer + gateway).
- `llm_audit_event.actor_user_id` widens to **nullable** (it is
  `nullable=False` today — `server/app/models/llm_connector.py:222`) so
  system-context org-connector calls can record a NULL actor.
- **One Alembic migration** (next after current head `055`):
  - Schema changes above.
  - Data backfill, two cases for `llm_default_connector_id`:
    1. Points at the migration-047-seeded connector (identified by
       `display_name = "Org Default (migrated from env var)"`): **convert
       that connector to `scope='org', user_id=NULL`** — it was the house
       env-var key all along, so org semantics are preserved exactly.
    2. Points at any other user-scoped connector (a DJ's personal key):
       **clear to NULL** — the admin creates a proper org connector.
  - Must pass `alembic upgrade head && alembic check` (model/migration drift
    gate in CI).

## 2. Gateway resolution

Order unchanged: feature pin → DJ pinned default → DJ MRU → org fallback.

- All per-DJ queries in `_resolve_connector` add an explicit
  `scope == 'user'` filter (defense-in-depth; `user_id == actor.id` already
  excludes org rows, but the filter makes intent testable and grep-able).
- `_resolve_org_default` returns a connector only when it is `scope='org'`,
  `status='active'`, **and `SystemSettings.llm_enabled` is true**. The
  `llm_enabled` gate moves out of `is_llm_available`'s global short-circuit
  and into the fallback path.
- `is_llm_available(db, actor)` new logic: DJ has an active own connector →
  `True` (regardless of `llm_enabled`); otherwise `True` iff the gated org
  fallback resolves; else `False`.
- System-context calls (`actor=None`) resolve through the same gated org
  fallback. With no org connector or `llm_enabled=False`, they raise
  `NoLlmConfigured` as today.
- Audit attribution: org-connector calls record the **dispatching DJ** as
  actor when present, `NULL` actor for true system calls. The
  `_system_actor_id` fallback (attributing to the connector owner) is
  removed; `llm_audit_event.actor_user_id` becomes nullable (see §1).

## 3. Admin API

**Added** — org connector CRUD, admin-only (`get_current_admin`), under
`/api/admin/llm/org-connectors`:
- `GET` (list), `POST` (create), `POST /{id}/test`, `POST /{id}/rotate`,
  `DELETE /{id}` — thin wrappers over the existing `connector_storage`
  helpers with `user=None, scope='org'`. Same encryption (`EncryptedText`),
  same adapters, same call/audit logging. Rate-limited like the DJ
  endpoints. Credential lifecycle events audit-logged as today.

**Changed**:
- `PATCH /api/admin/llm/policy` rejects `llm_default_connector_id` that is
  not an active `scope='org'` connector (400).
- AI settings response (`AISettingsOut`) loses `api_key_configured`,
  `api_key_masked`, `llm_model`. `llm_enabled` and
  `llm_rate_limit_per_minute` remain.

**Removed**:
- `GET /api/admin/ai/models` and `_list_anthropic_models()` +
  `FALLBACK_MODELS` (`admin.py`).
- `ANTHROPIC_MODEL` fallback label at `server/app/api/events.py:1007` — the
  recommendation response's `llm_model` comes solely from the gateway
  response (empty string when absent).
- `anthropic_api_key` is deleted from `server/app/core/config.py` — its
  only consumers are the panel/endpoint removed above (migration 047 reads
  `os.environ` directly). `anthropic_model` **stays**: migration
  `047_admin_ai_oauth.py:223-225` imports `get_settings().anthropic_model`,
  and applied migrations are never edited — keep the field with a
  "migration-047 only" comment. Stale `.env` entries remain harmless.
- Regenerate OpenAPI schema + frontend types (epic-merge lesson: stale
  generated types break the frontend build).

## 4. Admin UI (`/admin/ai`)

- **Delete** the API Key Status card
  (`dashboard/app/admin/ai/page.tsx:478-506`) and the models-list usage.
- **Add** an "Organization connector" section in its place: create / test /
  delete the house connector (reuse the DJ connector form components),
  status badge, model hint display.
- **Policy section**: org-default dropdown lists only org-scoped connectors;
  the `llm_enabled` toggle is recopied to *"Allow DJs without their own
  connector to use the organization connector (house-billed)"*.
- **Per-DJ table**: add an effective-source badge per DJ — `Own connector` /
  `Org fallback` / `None — AI unavailable`. Computed **backend-side** (the
  admin per-DJ listing response gains an `effective_source` field) so the
  frontend never duplicates gateway resolution rules.
- **Usage rollup**: org-connector usage rows labeled "Organization".

## 5. DJ-side visibility (`/settings/ai`)

- The DJ connectors-list response gains `org_fallback_available: bool`
  (true iff an active org connector exists and `llm_enabled` is true).
- A DJ with no connector of their own sees one of two banners:
  - Fallback available: *"You're using the organization's connector — usage
    is billed to the organization."*
  - Otherwise: *"AI features unavailable — connect a provider."*
- Org connector credentials are never exposed to DJ endpoints.

## 6. Behavior matrix

| DJ state | `llm_enabled` | Org connector | Result |
|---|---|---|---|
| Own active connector | any | any | Works — own billing; never blocked |
| No connector | true | active | Works — org-billed, labeled in UI |
| No connector | false | any | 503 / "connect a provider" |
| No connector | true | none/inactive | 503 / "connect a provider" |
| System context (`actor=None`) | true | active | Works — org-billed, NULL audit actor |
| System context | false | any | `NoLlmConfigured` |

## 7. Testing

Backend (pytest):
- **Headline regression**: BYO DJ dispatch succeeds with
  `llm_enabled=False`.
- Org fallback honored/blocked per matrix above (each row pinned).
- `_resolve_connector` never returns an org row for the per-DJ chain, and
  never returns a user row from `_resolve_org_default`.
- Policy PATCH rejects user-scoped connector ids (400) and accepts active
  org-scoped ids.
- Org CRUD requires admin (403 for DJ), encrypts credentials at rest,
  audit-logs lifecycle events.
- Migration: `alembic upgrade head && alembic check`; backfill clears a
  user-scoped default.
- Audit rows with NULL actor accepted for system-context org calls.

Frontend (vitest):
- API Key Status panel gone; Organization connector section renders and
  drives create/test/delete calls.
- Per-DJ effective-source badges for all three states.
- Both DJ banners on `/settings/ai`.

## Rollout

- Single PR on `feat/org-llm-connector`.
- Deployments whose org default is the 047-seeded env-var connector need no
  action — the migration converts it to org scope in place.
- Deployments whose org default was a DJ's personal connector need one admin
  action after deploy: create a proper org connector on `/admin/ai` (the
  migration intentionally clears rather than stealing a DJ's key).

## Out of scope

- TrackVibe `llm_provider` gap (#391) — tracked separately.
- Per-connector model discovery (replacement for the removed Anthropic
  models endpoint).
- Per-DJ quotas/budgets on the org connector.

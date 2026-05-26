# LLM Audit-Trail Admin UI (#341) Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. TDD throughout.

**Goal:** Add an admin-only browse/filter/export UI for the existing `llm_audit_event` table on the `/admin/ai` page.

**Architecture:** New read-only backend endpoints on `admin_llm.py` (`GET /api/admin/llm/audit` paginated JSON + `GET /api/admin/llm/audit.csv` streaming CSV), both joining actor username + target connector display name (never credentials). New Pydantic schemas. New API-client methods + a new "Audit trail" card section on the existing `/admin/ai` page (the page uses cards as sections — no tab component exists).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, slowapi, Pydantic v2, Next.js/React 19 + vanilla CSS, vitest.

**Scope fences:** Edit only `server/app/api/admin_llm.py`, `server/app/schemas/llm.py`, `server/tests/*`, `dashboard/app/admin/ai/page.tsx` (+ `__tests__`), `dashboard/lib/api.ts` (add-only), `dashboard/lib/api-types.ts` (add-only). NO migration. READ-ONLY on `llm_audit_event`.

---

## Task 1: Backend schemas + paginated audit endpoint

**Files:**
- Modify: `server/app/schemas/llm.py` (add `AuditEventRow`, `AdminAuditOut`)
- Modify: `server/app/api/admin_llm.py` (add `GET /audit`)
- Test: `server/tests/test_llm_admin_audit.py`

- [ ] Step 1: Write failing tests covering: basic list (admin), 403 for non-admin, filter by event_type, filter by actor_user_id, filter by target_connector_id, days window, pagination (limit/offset + total), joined actor_username + target_connector_display_name, no credentials leaked.
- [ ] Step 2: Run → FAIL (404 / no endpoint).
- [ ] Step 3: Add schemas + endpoint. Query `LlmAuditEvent` left-joined to User (actor) and LlmConnector (target). Filters all optional. `days` default 30, range 1..3650. limit 1..200 default 50, offset >=0. Return rows newest-first + `total`.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit.

## Task 2: CSV export endpoint

**Files:**
- Modify: `server/app/api/admin_llm.py` (add `GET /audit.csv`)
- Test: `server/tests/test_llm_admin_audit.py`

- [ ] Step 1: Write failing tests: CSV content-type + header row + a data row; honors event_type filter; 403 non-admin; cap rows.
- [ ] Step 2: Run → FAIL.
- [ ] Step 3: Implement StreamingResponse with `csv` module; same filter helper as Task 1; cap at 10000 rows. Columns: timestamp, actor, event_type, target_connector, notes (notes column reserved/empty — schema has no notes field; emit blank to honor issue's column list).
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit.

## Task 3: Frontend API client + types

**Files:**
- Modify: `dashboard/lib/api-types.ts` (add `LlmAdminAudit`, `LlmAuditRow`)
- Modify: `dashboard/lib/api.ts` (add `getAdminLlmAudit`, `getAdminLlmAuditCsvUrl`/download helper)
- Regenerate: `dashboard/lib/api-types.generated.ts` via `npm run types:export && npm run types:generate`

- [ ] Step 1: Regenerate OpenAPI types so new schemas appear.
- [ ] Step 2: Add manual aliases + client methods.
- [ ] Step 3: tsc passes.
- [ ] Step 4: Commit.

## Task 4: Audit trail card on /admin/ai page + tests

**Files:**
- Modify: `dashboard/app/admin/ai/page.tsx`
- Test: `dashboard/app/admin/ai/__tests__/page.test.tsx`

- [ ] Step 1: Write failing test: renders "Audit trail" heading + a seeded row; filter inputs present; export button present.
- [ ] Step 2: Run → FAIL.
- [ ] Step 3: Implement card: filters (event type select, actor, target connector, days), table (timestamp, actor, event type, connector, notes), pagination (prev/next), CSV export button.
- [ ] Step 4: Run → PASS. Full frontend CI.
- [ ] Step 5: Commit.

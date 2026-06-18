# Engine DJ + Lexicon Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Engine DJ and Lexicon as first-class export targets that emit the existing Rekordbox `DJ_PLAYLISTS` XML, plus an ISRC fidelity fix in the shared renderer.

**Architecture:** Neither platform has a proprietary import format — both ingest Rekordbox XML. So we register `enginedj` and `lexicon` as distinct format keys against the existing `render_rekordbox_xml`, widen the schema `Literal`s, regenerate the OpenAPI contract + generated TS types, and flip/add the two ExportModal options. The only renderer change is emitting `track.isrc` via the `Comments` TRACK attribute.

**Tech Stack:** FastAPI + Pydantic (backend), Next.js/React 19 + vanilla CSS (frontend), pytest + vitest.

## Global Constraints

- Backend ruff: line-length 100; rules E, F, I, UP. Coverage gate enforced (`--cov-fail-under`); new code must not drop coverage.
- Frontend: vanilla CSS + inline React styles — NO Tailwind/UI framework.
- Immutability; validate at boundaries; keep existing control-char sanitization (`_clean`) in the XML renderer.
- Commit format: Conventional Commits, body ends with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Branch: `feat/issue-401`. Never commit to main.
- `enginedj` / `lexicon` are DISTINCT format keys (not aliases) — both map to `(render_rekordbox_xml, "application/xml", "xml")`.
- Honest UI copy: label "Engine DJ XML" / "Lexicon", sub describes "imports via Rekordbox XML — relink on import".

---

## File Structure

- `server/app/services/setbuilder/export_files.py` — add ISRC → `Comments` line in `render_rekordbox_xml`. No new renderer functions.
- `server/app/schemas/setbuilder.py` — widen `ExportTarget` + `ExportFileFormat` Literals.
- `server/app/api/setbuilder.py` — add `enginedj` + `lexicon` keys to `_FILE_RENDERERS`.
- `server/openapi.json` — regenerated from the schema change.
- `server/tests/test_setbuilder_export_service.py` — ISRC renderer test.
- `server/tests/test_setbuilder_export_api.py` — enginedj/lexicon routing + media-type/ext + no-mutation tests.
- `dashboard/lib/api-types.generated.ts` — regenerated from `openapi.json`.
- `dashboard/app/(dj)/setbuilder/components/ExportModal.tsx` — flip enginedj, add lexicon, wire download + relink note.
- `dashboard/app/(dj)/setbuilder/components/__tests__/ExportModal.test.tsx` — update picker counts + new-option wiring.

---

### Task 1: ISRC fidelity in the Rekordbox XML renderer

**Files:**
- Modify: `server/app/services/setbuilder/export_files.py` (`render_rekordbox_xml`)
- Test: `server/tests/test_setbuilder_export_service.py` (`TestRekordboxXml`)

**Interfaces:**
- Consumes: `ExportTrack.isrc: str | None` (already exists in `export_common.py`).
- Produces: TRACK attribute `Comments="ISRC:<isrc>"` when `track.isrc` is truthy; sanitized via `_clean`; absent otherwise.

- [ ] **Step 1: Write failing tests** — ISRC present emits `Comments="ISRC:..."`; ISRC absent omits `Comments`; control chars in ISRC sanitized.
- [ ] **Step 2: Run → FAIL** (`KeyError: 'Comments'`).
- [ ] **Step 3: Implement** — in `render_rekordbox_xml`, after the genre block: `if track.isrc: attrs["Comments"] = f"ISRC:{_clean(track.isrc)}"`.
- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Commit** `feat(setbuilder): emit ISRC via Comments in Rekordbox XML export`.

### Task 2: Widen export schema Literals

**Files:**
- Modify: `server/app/schemas/setbuilder.py` (`ExportTarget`, `ExportFileFormat`)

**Interfaces:**
- Produces: `ExportTarget = Literal["tidal","rekordbox","m3u","txt","enginedj","lexicon"]`; `ExportFileFormat = Literal["rekordbox","m3u","txt","enginedj","lexicon"]`.

- [ ] **Step 1:** Widen both Literals.
- [ ] **Step 2:** (covered by Task 3 API tests — schema alone has no direct test).
- [ ] **Step 3: Commit** folded into Task 3.

### Task 3: Register enginedj + lexicon renderers at the API boundary

**Files:**
- Modify: `server/app/api/setbuilder.py` (`_FILE_RENDERERS`)
- Test: `server/tests/test_setbuilder_export_api.py` (`TestFileExport`)

**Interfaces:**
- Consumes: `export_files.render_rekordbox_xml`, widened `ExportFileFormat`.
- Produces: `_FILE_RENDERERS["enginedj"]` and `["lexicon"]` → `(render_rekordbox_xml, "application/xml", "xml")`.

- [ ] **Step 1: Write failing tests** — POST `/export/file` with format `enginedj` and `lexicon` returns 200, `content-type` starts `application/xml`, `filename="...xml"`, body contains `DJ_PLAYLISTS`; preflight `target=enginedj` returns 200; export does not mutate set status.
- [ ] **Step 2: Run → FAIL** (422 on unknown enum / KeyError).
- [ ] **Step 3: Implement** — add the two dict entries (Task 2 Literals make them valid enum values).
- [ ] **Step 4: Run → PASS**.
- [ ] **Step 5: Regenerate** `server/openapi.json` via `.venv/bin/python scripts/export_openapi.py`.
- [ ] **Step 6: Commit** `feat(setbuilder): route Engine DJ + Lexicon exports to Rekordbox XML`.

### Task 4: Regenerate frontend types

**Files:**
- Modify: `dashboard/lib/api-types.generated.ts`

- [ ] **Step 1:** From `dashboard/`, `npm run types:generate` (reads `../server/openapi.json`).
- [ ] **Step 2:** Verify `enginedj`/`lexicon` appear in the generated `ExportPreflightIn`/`ExportFileIn` enums.
- [ ] **Step 3: Commit** folded into Task 5 (types + UI land together to keep tsc green at every commit).

### Task 5: ExportModal — flip Engine DJ, add Lexicon

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/ExportModal.tsx`
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/ExportModal.test.tsx`

**Interfaces:**
- Consumes: widened `ExportTarget`/`ExportFileFormat`, `api.exportPreflight`, `api.exportSetFile`.
- Produces: 5 available rows (tidal, rekordbox, m3u, enginedj, lexicon), 3 "Coming soon" (serato, spotify, applemusic). enginedj/lexicon download `.xml` and show a relink note.

- [ ] **Step 1: Update test** — picker now renders 8 rows, 3 "Coming soon"; Engine DJ + Lexicon are enabled; clicking each calls `exportPreflight(id, 'enginedj'|'lexicon')` then shows a Download .xml button that calls `exportSetFile(id, 'enginedj'|'lexicon', false, ...)`.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** — flip `enginedj` to available with honest sub; add `lexicon` row; extend `targetMap`/`extMap`; unify the rekordbox/enginedj/lexicon download block (3 identical XML targets → one block keyed off a constant) + relink note for enginedj/lexicon.
- [ ] **Step 4: Run → PASS**; `npm run lint && npx tsc --noEmit`.
- [ ] **Step 5: Commit** `feat(setbuilder): ship Engine DJ + Lexicon export options in modal`.

### Task 6: Full CI + finish

- [ ] Backend: ruff check, ruff format --check, bandit, pytest (coverage gate), `alembic upgrade head && alembic check`.
- [ ] Frontend: lint, tsc --noEmit, vitest. `git checkout next-env.d.ts` if modified.
- [ ] Finish branch → Push + PR with `Closes #401`, Why/What/Testing, credit Claude Opus 4.8, manual-QA note.

---

## Self-Review

- **Spec coverage:** (1) enginedj/lexicon options → Tasks 2,3,5. (2) in-modal relink note → Task 5. (3) ISRC fix → Task 1. (4) fixture/schema tests → Tasks 1,3,5. ✓
- **Placeholder scan:** none. ✓
- **Type consistency:** `enginedj`/`lexicon` literal spelling identical across schema, `_FILE_RENDERERS`, `targetMap`, `extMap`, tests. ✓

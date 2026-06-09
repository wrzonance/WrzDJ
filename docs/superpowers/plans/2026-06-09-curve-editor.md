# WrzDJSet Energy Curve Editor Implementation Plan (#389)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slot-coupled energy-curve editor for the WrzDJSet builder: per-slot draggable targets, built-in + per-DJ persisted curve templates with an overlay editor, vibe windows, replacement popover on target mismatch, and BPM/Key seam-friction view modes.

**Architecture:** Backend owns templates + piecewise-linear interpolation (`services/setbuilder/curve.py`), a per-DJ `set_curve_templates` table (migration 055), a nullable `target_energy` column on `set_slots`, and additive `/api/setbuilder` routes. Frontend is a set of NEW components under `dashboard/app/(dj)/setbuilder/components/` (SVG canvas, pure-math lib, popover, overlay editor), mounted into the builder page by swapping only the Curve + Timeline placeholder sections (shared-file courtesy with #388/#398).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + pytest; Next.js 16 / React 19, vanilla CSS modules, SVG, vitest.

---

## Design decisions (ambiguities resolved)

1. **Per-slot target persistence** — `SetSlot.target_energy` (Float, nullable). `NULL` means "no explicit target → fall back to track energy on load" (issue: "on load target = track energy"). Added in migration `055_add_curve_templates` (one migration covers the table + the column; slots 053/054 reserved by siblings).
2. **Track metadata gap** — pool/track models land with #388; slots only carry `track_id` today. The `GET /sets/{id}/slots` payload is metadata-free; the frontend maps slots to view models with safe defaults (duration 210s, energy 5) so the curve renders pre-#388. Components are fully prop-driven so #388/#390 can feed real metadata without touching the editor.
3. **Server-side template application** — `POST /sets/{id}/curve/apply-template` accepts optional `slot_midpoints` (client knows durations; server doesn't yet). Missing midpoints → uniform `(i+0.5)/n`. Server interpolates via curve.py and persists `target_energy` per slot (acceptance: "Templates re-target slots").
4. **Vibe windows persistence** — paired `SetCurvePoint` rows (start: `is_slow_window_start=True` + label; end: `is_slow_window_end=True`), `energy=0` (windows don't contribute to the envelope — the curve is derived from slot targets). Replace-all `PUT` semantics.
5. **Replacement-prompt gate** — design's `tweaks.energyMismatchPrompt`: stored client-side in `localStorage` (`wrzdj.curve.suggestReplacements`, default ON) as a toolbar toggle; the builder settings modal is out of scope (#394/#395 own builder settings).
6. **Replace action** — popover ranks pool candidates (props) and emits `onReplace(slotId, trackId)`; actual slot mutation wires up when #388's pool + slot CRUD land. Popover renders the empty-state when the pool is empty.
7. **Friction math source of truth** — mirrors the design bundle exactly: BPM pct = best of direct/half/double delta relative to destination tempo; tiers ≤2 / ≤5 / ≤8 / >8 %. Camelot tiers from wheel distance.
8. **Built-in templates** — the four shapes from the design bundle's `CURVE_PRESETS` (Open-Format, Wedding, Prom, Club Peak) with their slow-window flags.

---

### Task 1: Migration 055 + SetCurveTemplate model + SetSlot.target_energy

**Files:**
- Create: `server/app/models/curve_template.py`
- Modify: `server/app/models/set.py` (add `target_energy` to SetSlot)
- Modify: `server/app/models/__init__.py` (register import, additive)
- Create: `server/alembic/versions/055_add_curve_templates.py` (down_revision="052")
- Test: `server/tests/test_setbuilder_curve_models.py`

Model: `SetCurveTemplate(id, user_id FK users CASCADE indexed, name String(80) not null, points_json Text not null, created_at, updated_at)`.
SetSlot gains `target_energy: Mapped[float | None] = mapped_column(Float, nullable=True)`.

- [ ] Step 1: failing model test (create template row; slot target_energy default None)
- [ ] Step 2: model + migration; `alembic upgrade head && alembic check` clean
- [ ] Step 3: tests pass; commit `feat(setbuilder): curve template model + slot target_energy (055)`

### Task 2: curve.py service — builtins, interpolation, template CRUD, apply, vibe windows

**Files:**
- Create: `server/app/services/setbuilder/curve.py`
- Test: `server/tests/test_setbuilder_curve_service.py`

Contents:
- `BUILTIN_TEMPLATES: dict[str, list[dict]]` — four design-bundle shapes, points `{t, e, label, slow_start?, slow_end?}`.
- `interpolate_energy(points, t) -> float` — piecewise linear, clamps t to [0,1], flat extension beyond endpoint t's.
- `targets_at_midpoints(points, midpoints) -> list[float]` — rounded to 0.1.
- `uniform_midpoints(n) -> list[float]` — `(i+0.5)/n`.
- Template CRUD (owner-scoped): `list_templates`, `get_owned_template`, `create_template`, `update_template`, `delete_template` (points stored as JSON string).
- `apply_points_to_slots(db, set_obj, points, midpoints|None) -> list[tuple[slot_id, target]]` — orders slots by position, validates midpoint count, persists `target_energy`.
- `set_slot_target(db, slot, value|None)`.
- `windows_from_points(points) -> list[{t0, t1, label}]` — pairs slow_start/slow_end flags (used by apply response so the client can rebuild windows).
- `get_vibe_windows(db, set_id)` / `replace_vibe_windows(db, set_obj, windows)` — paired SetCurvePoint rows as per design decision 4.

- [ ] TDD: interpolation endpoints/midpoints/rounding tests; builtin shape sanity (4 names, endpoints at t=0/1); apply with uniform + explicit midpoints; midpoint count mismatch raises ValueError; vibe window round-trip; commit `feat(setbuilder): curve service — templates, interpolation, vibe windows`

### Task 3: Schemas (additive) + API routes (additive)

**Files:**
- Modify: `server/app/schemas/setbuilder.py` (append new classes only)
- Modify: `server/app/api/setbuilder.py` (append new routes only)
- Test: `server/tests/test_setbuilder_curve_api.py`

Schemas: `CurvePointModel{t: 0..1, e: 0..10, label?: <=50, slow_start, slow_end}`, points-list validator (2..32 points, non-decreasing t, first t=0, last t=1); `CurveTemplateCreate{name 1..80, points}`, `CurveTemplateUpdate` (same), `BuiltinTemplateOut{name, points}`, `CurveTemplateOut{id, name, points, updated_at}`, `CurveTemplatesResponse{builtin, user}`, `SlotOut{id, position, track_id, locked, target_energy, notes}`, `SlotTargetUpdate{target_energy: float|None 0..10}`, `SlotTargetOut{slot_id, target_energy}`, `ApplyTemplateRequest{builtin?|template_id? (exactly one), slot_midpoints?: list[0..1] non-decreasing}`, `ApplyTemplateResponse{targets, windows}`, `VibeWindowModel{t0_sec>=0, t1_sec>t0_sec, label 1..50}`, `VibeWindowsPut{windows max 30}`, `VibeWindowsResponse{windows}`.

Routes (all `get_current_active_user`, rate-limited, owner-scoped 404):
- `GET /curve-templates` (60/min), `POST /curve-templates` (30/min, 201), `PUT /curve-templates/{id}` (30/min), `DELETE /curve-templates/{id}` (30/min, 204)
- `GET /sets/{set_id}/slots` (60/min)
- `PATCH /sets/{set_id}/slots/{slot_id}/target` (60/min)
- `POST /sets/{set_id}/curve/apply-template` (30/min)
- `GET /sets/{set_id}/vibe-windows` (60/min), `PUT /sets/{set_id}/vibe-windows` (30/min)

- [ ] TDD: auth gating (401/403-pending), owner isolation (404 on foreign set/template), template CRUD happy paths + validation 422s (bad t order, endpoint t, >32 points), apply-template persists targets (uniform + explicit midpoints; builtin + user template; 422 on both/neither id; 400 on midpoint count mismatch), slot target patch + null reset, vibe-windows put/get round-trip + 422 on t1<=t0. Commit `feat(setbuilder): curve template + slot target + vibe window endpoints`

### Task 4: OpenAPI regeneration + frontend API client

**Files:**
- Regenerate: `server/openapi.json`, `dashboard/lib/api-types.generated.ts` (`npm run types:export && npm run types:generate`)
- Modify: `dashboard/lib/api-types.ts` (additive exports)
- Modify: `dashboard/lib/api.ts` (additive methods: `getCurveTemplates`, `createCurveTemplate`, `updateCurveTemplate`, `deleteCurveTemplate`, `getSetSlots`, `updateSlotTarget`, `applyCurveTemplate`, `getVibeWindows`, `putVibeWindows`)

- [ ] Regenerate, export types from generated schemas, add client methods, commit `feat(setbuilder): curve API client + regenerated types`

### Task 5: curveMath.ts — pure frontend math + presets

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/curveMath.ts`
- Create: `dashboard/app/(dj)/setbuilder/components/types.ts`
- Test: `dashboard/app/(dj)/setbuilder/__tests__/curveMath.test.ts`

Port from the design bundle: `interpolateEnergy`, `parseCamelot`, `bpmPercentDelta` (% of destination tempo, half/double detection, tiers match/good/stretch/clash at 2/5/8%), `camelotMixTier` (perfect/good/ok/clash + labels), `bpmCompat`, `camelotCompat`, `rankReplacementCandidates(target, prevTrack, pool, inSetIds)` (0.55 energy + 0.25 bpm + 0.20 key, ±2.5 energy filter, top 5), `BPM_TIER_COLORS`, `KEY_TIER_COLORS`, `VIBE_PRESETS` (15), `slotBlocksFromSlots` geometry helper, `fmtTime`.

- [ ] TDD all math (esp. percentage thresholds + half/double-time, acceptance #3); commit `feat(setbuilder): curve math lib + vibe presets`

### Task 6: CurveEditor SVG component

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/CurveEditor.tsx`
- Create: `dashboard/app/(dj)/setbuilder/components/curve.module.css`
- Test: `dashboard/app/(dj)/setbuilder/__tests__/CurveEditor.test.tsx`

Port of design `curve-editor.jsx` minus pairings/playhead/pool-drop (other issues): slot blocks (x=duration share, y=energy), derived target polyline through slot midpoints, per-slot drag handles (pointer events, vertical-only) with live value chip, mismatch visuals (amber hatch `mismatchPattern` above block when target > energy+0.5; dashed amber line when target < energy−0.5), seam friction bands in bpm/key view (band sized to shorter neighbor, hover chip with exact pct/label), vibe windows (header-bar move drag, edge resize, right-click delete, double-click → preset pick callback), hover sync props (`hoveredIdx`, `onHover`, `onBlockClick`).

- [ ] Render tests with fixture slots: block count, mismatch hatch presence, seam tier colors, window labels, drag-end callback firing (pointer events). Commit `feat(setbuilder): slot-coupled SVG curve editor`

### Task 7: CurveTemplateEditorOverlay + ReplacePopover + CurveToolbar

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/CurveTemplateEditorOverlay.tsx`
- Create: `dashboard/app/(dj)/setbuilder/components/ReplacePopover.tsx`
- Create: `dashboard/app/(dj)/setbuilder/components/CurveToolbar.tsx`
- Test: `dashboard/app/(dj)/setbuilder/__tests__/CurveTemplateEditor.test.tsx`, `__tests__/ReplacePopover.test.tsx`

Overlay: draggable SVG canvas (double-click add point, endpoints locked at t=0/1, delete key), point list sidebar (label, t %, energy slider, delete), Save changes (user templates) / Save as new / Delete; built-ins open read-only original → save-as-copy only.
ReplacePopover: header (current energy → target), top-5 candidate rows (title/artist/bpm/key/energy/fit score), empty state, "Keep anyway" + Cancel.
Toolbar: Normal/BPM/Key segmented view switch, template dropdown (built-in + My templates + Create new + per-row edit), Add-vibe-window dropdown (15 presets), suggest-replacements toggle (localStorage).

- [ ] Tests: overlay add/remove/save-as flows; popover ranking display + gate. Commit `feat(setbuilder): template overlay editor, replace popover, curve toolbar`

### Task 8: CurvePanel + TimelinePanel + BuilderWorkspace wiring

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/CurvePanel.tsx`
- Create: `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx`
- Create: `dashboard/app/(dj)/setbuilder/components/BuilderWorkspace.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` — replace ONLY the Curve + Timeline placeholder sections with `<BuilderWorkspace setId=…/>`
- Test: `dashboard/app/(dj)/setbuilder/__tests__/BuilderWorkspace.test.tsx`

CurvePanel: loads slots + windows + templates, maps to SlotView (defaults for missing metadata), local target state, PATCH on drag-end, mismatch ≥0.8 → ReplacePopover (gated by toggle), apply-template → POST + rebuild windows from response, template save/save-as/delete → API, windows drag/delete → debounced PUT.
TimelinePanel: ordered slot rows (position, title/artist, BPM/key/energy badges, target chip), hover-sync both directions, `scrollIntoView({block:'nearest'})` on curve-block click only when out of view.
BuilderWorkspace: owns shared hover state + slot data, renders both panels in their grid areas.

- [ ] Tests: workspace fetch + hover sync + drag-end PATCH (mock api). Commit `feat(setbuilder): mount curve + timeline panels in builder workspace`

### Task 9: Full CI + finish

- [ ] Backend: ruff check/format, bandit, pytest (coverage ≥85), alembic upgrade+check
- [ ] Frontend: lint, tsc --noEmit, vitest --run
- [ ] `git checkout next-env.d.ts` if dirty; push; PR with `Closes #389` + Design decisions section

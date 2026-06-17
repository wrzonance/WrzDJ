# Design — #438 Mobile-reorder view (touch ▲/▼ move controls)

**Issue:** #438 (`feat(setbuilder): mobile-reorder view for the set timeline`)
**Phase:** v1.1 (Polish). Builds on #437 (desktop hand-drag reorder, merged).
**Date:** 2026-06-17
**Branch:** `feat/issue-438`

## Why

DJs reviewing or tweaking a set on a phone need a usable reorder experience. #437 added desktop
hand-drag reordering, but native HTML5 drag **does not fire on touch devices** — mobile browsers
don't emit `dragstart` from a touch gesture. So the mobile path needs a different input mechanism.

## Decisions (resolved during brainstorming)

1. **Input mechanism: explicit ▲/▼ move controls** (not long-press touch-drag). Deterministic,
   accessible (keyboard + screen reader), trivially reuses the #437 reorder engine for each ±1 move,
   and respects locked slots by disabling at illegal boundaries. Long-press touch-drag is deferred.
2. **Controls are always visible** (desktop *and* mobile), coexisting with desktop drag. Cheaper than
   viewport-conditional rendering, an a11y win on desktop, and deterministically testable.
3. **Tight scope:** the touch-reorder affordance + a usable single-column timeline collapse on narrow
   viewports. The full mobile builder shell (curve/chat as tabs/sheets, broad field-collapsing) is
   deferred to a follow-up issue.
4. **Mobile presentation via pure CSS `@media`** (mobile-first), no JS viewport hook — avoids
   SSR/hydration mismatch in Next.js.

## What we reuse from #437 (no backend change)

- Backend `apply_slot_order` + `PUT /sets/{id}/slots/order` + `api.reorderSlots(setId, slotIds)`.
- The `commit()` path in `useSetDocumentHistory` → undo/redo/autosave/beforeunload-guard for free.
- The locked-slot invariant already enforced by `buildReorderedIds` (a locked slot must keep its
  index). `buildMovedIds` reuses the same predicate.

A ▲/▼ move is simply a reorder of ±1 position, so the entire persistence + rescore path is identical
to a drag — only the *input* differs.

## Boundaries (frontend only — reuses #437's backend + commit path entirely)

- **Create** `dashboard/app/(dj)/setbuilder/components/reorderMath.ts` — pure `buildMovedIds`.
- **Modify** `BuilderWorkspace.tsx` — `handleMoveSlot` + pass `onMoveSlot` down.
- **Modify** `TimelinePanel.tsx` — thread the `onMoveSlot` prop to rows.
- **Modify** `TimelineRow.tsx` — ▲/▼ controls + self-computed disabled state.
- **Modify** `curve.module.css` (and `setbuilder.module.css` if the grid needs it) — control styling +
  the `@media (max-width: 640px)` single-column collapse.
- **Create** tests: `reorderMath.test.ts`, extend `TimelineRow.test.tsx`, extend `BuilderWorkspace`
  reorder tests (move-commit).

No backend, schema, migration, or `api.ts` changes — #437 already shipped `api.reorderSlots`.

## Architecture (frontend only)

### `reorderMath.ts` (new pure module)
- **`buildMovedIds(slots, slotId, direction): number[] | null`** — the single source of truth for both
  *performing* a move and *deciding if the control is enabled*:
  - `fromIdx = slots.findIndex(s => s.id === slotId)`; return `null` if not found.
  - `targetIdx = direction === 'up' ? fromIdx - 1 : fromIdx + 1`; return `null` if out of `[0, len-1]`.
  - Build the new id order: remove `slotId`, insert it at `targetIdx`.
  - Return `null` if the result would displace a **locked** slot (same invariant as `buildReorderedIds`:
    any locked slot whose index changed). Else return the new id array.
- Lives in its own module (not in `BuilderWorkspace.tsx`) so both the handler and the row can import it
  without a row→workspace dependency.

### `BuilderWorkspace.tsx`
- **New handler** `handleMoveSlot(slotId, direction)`: `const ids = buildMovedIds(slots, slotId, direction);
  if (!ids) return;` then `commit('Move slot', () => api.reorderSlots(setId, ids))` → `loadSlots()`,
  with `loadSlots()` in the catch (mirrors `handleSlotReorder`).
- Pass `onMoveSlot={handleMoveSlot}` to `<TimelinePanel>`.

### `TimelinePanel.tsx`
- Add prop `onMoveSlot?: (slotId: number, direction: 'up' | 'down') => void | Promise<void>` and thread
  it unchanged to each `TimelineRow`. No can-move computation here. The drag path (#437) is untouched.

### `TimelineRow.tsx`
- Render a ▲/▼ control pair for **unlocked** slots (locked rows render no move controls — they can't
  move). The row already receives `slots` and `slot` as props, so it computes its own disabled state —
  no booleans threaded through the panel. Each button:
  - `aria-label` "Move {title} up/down", tap target ≥ 44px on mobile.
  - `disabled = buildMovedIds(slots, slot.id, dir) === null` (boundary or would cross a lock) — the
    **same** function the handler uses, so the button can never be enabled for a move the handler rejects.
  - `onClick` → `event.stopPropagation()` then `onMoveSlot(slot.id, 'up' | 'down')` (stopPropagation so a
    click doesn't also start a drag).

### CSS (`curve.module.css`, and `setbuilder.module.css` if the grid needs it)
- Move-control styling (dark theme, `#ededed` on `#1a1a1a`, visible focus ring).
- `@media (max-width: 640px)`: collapse the timeline row to a comfortable single column, enlarge tap
  targets, hide non-essential badges (e.g. target chip) to focus on order + lock + the move controls.
  Desktop layout and the drag affordance are unchanged.

## Data flow

```
tap ▲/▼  →  onMoveSlot(slotId, dir)
  →  handleMoveSlot: buildMovedIds(slots, slotId, dir)  (null → no-op: button was disabled anyway)
  →  commit('Move slot', () => api.reorderSlots(setId, ids))
       →  PUT /slots/order  →  apply_slot_order: validate → reassign positions → recompute scores
  →  loadSlots()  (refresh timeline + curve)
```

Undo/redo, autosave, and the unsaved-changes guard are inherited from `commit()`.

## Error handling

- `handleMoveSlot` wraps the commit in `try/catch`; on failure `loadSlots()` re-syncs from the server
  (mirrors `handleSlotReorder`). A disabled button can't fire, so an illegal move never reaches the API;
  the backend's permutation/locked 400 remains as defense-in-depth.

## Testing (vitest, TDD — RED first)

- **`buildMovedIds`** (pure): move up; move down; at-top ▲ → null; at-bottom ▼ → null; unknown id →
  null; a move that would displace a locked slot → null; a legal move adjacent to (but not crossing) a
  locked slot → new order.
- **`TimelineRow`**: unlocked row renders both ▲/▼; locked row renders neither; ▲ disabled at top, ▼
  disabled at bottom; clicking a control calls `onMoveSlot` with the right direction and does not start
  a drag.
- **`BuilderWorkspace`**: `handleMoveSlot` commits via `api.reorderSlots` with the moved order and
  refreshes; an illegal move is a no-op (no API call).

Backend reorder behavior is already covered by #437's `test_setbuilder_reorder*` suites — no new
backend tests.

## Out of scope (follow-up issue)

- Full mobile builder shell: curve/chat panels as tabs or bottom-sheets; broad non-essential field
  collapsing beyond the timeline.
- Long-press / Pointer-Events touch-drag reordering.

## Acceptance criteria (from the issue)

- [ ] On a narrow viewport, slots can be reordered by touch (▲/▼ controls, ≥44px targets).
- [ ] Locked slots are not movable (no controls; adjacent moves that would displace them are disabled).
- [ ] Reorder persists + participates in undo/redo (via `commit()` → `api.reorderSlots`).
- [ ] Shares the reorder/persistence path with desktop drag (same engine; only the input differs).

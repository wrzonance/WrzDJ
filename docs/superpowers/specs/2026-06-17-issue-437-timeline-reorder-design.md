# Design — #437 Hand-drag reordering of timeline slots

**Issue:** #437 (`feat(setbuilder): hand-drag reordering of timeline slots`)
**Phase:** v1.1 (Polish). Foundation for #438 (mobile-reorder view).
**Date:** 2026-06-17
**Branch:** `feat/issue-437`

## Why

The WrzDJSet mockup specifies that DJs can drag slot rows to reorder a set by hand. The shipped
timeline renders rows with `draggable={false}` — today reordering only happens via the deterministic
Pass-1 builder and the agent's mutation tools. DJs need direct manual control to override the
algorithm and place tracks exactly where they want.

This issue lands the **reusable reorder engine** (backend reorder+rescore endpoint, frontend reorder
commit path, drag payload) plus the **desktop native-drag UI** on top. #438 (mobile-reorder view)
then becomes a thin touch presentation that reuses this engine rather than forking it.

## Key constraints discovered in the codebase

- **DnD is native HTML5 drag.** Pool→timeline drops use `dataTransfer` with a custom MIME type via
  `dnd.ts` (`writePoolTrackDragPayload` / `readPoolTrackDragPayload`). Reorder extends this pattern
  with a second payload type rather than introducing a DnD library.
- **The PUT `/document` endpoint does not rescore.** `document_snapshot.restore_snapshot` persists
  `position`, `transition_score`, and `transition_warnings` from the payload verbatim. The insert
  flow sets the new slot's `transition_score` to `null`. So reorder cannot get correct scores from a
  document PUT — it must hit a path that recomputes them.
- **The agent already reorders + rescores.** `pass2_agent._tool_reorder_slot` moves a slot (with
  locked-slot guards), and `chat_with_agent` then calls
  `pass1_deterministic.recompute_transition_scores(db, set_obj, slots)` ("honoring current order").
  Reorder reuses `recompute_transition_scores` so DJ drags and agent moves score identically.
- **Virtualization is already solved.** `TimelinePanel.insertIndexFromPointer` converts a pointer Y
  into an insert index through the virtualized window (only visible rows mounted). Reorder reuses it
  — no new drag math.
- **Persistence/undo/redo/autosave is already solved.** `useSetDocumentHistory.commit(label, action)`
  snapshots before/after, manages undo+redo stacks, autosave, and the `beforeunload` guard. Reorder
  routes through `commit()` and inherits all of it.

## Decisions (resolved during brainstorming)

1. **Scope:** #437 ships the reusable engine + desktop drag UI in one PR. (Est. ~300–450 LOC.)
2. **API granularity:** full-order PUT — the client submits the complete desired slot order.
3. **Locked-slot semantics:** strict — locked slots are immovable anchors that keep their absolute
   index and act as barriers, partitioning the timeline into independently-reorderable regions.

## Architecture

### Backend (`server/`)

**Schema** — `app/schemas/setbuilder.py`
- `SlotOrderRequest { slot_ids: list[int] }` — the complete desired order of the set's slots.
- Response reuses the existing transition-score-out shape used by other setbuilder mutations.

**Service** — `app/services/setbuilder/` (alongside `pass1_deterministic` / `pass2_agent`)
- `apply_slot_order(db, set_obj, ordered_ids) -> list[TransitionScore]`:
  1. Validate `ordered_ids` is a permutation of the set's current slot ids (same multiset). Else
     raise a 400-mapped error.
  2. Validate every **locked** slot's index in `ordered_ids` equals its current `position`. Else
     raise "Reorder would move a locked slot" (400).
  3. Reassign each slot's `position` per `ordered_ids`.
  4. Call `recompute_transition_scores(db, set_obj, slots)` (reuse Pass-1; honors the new order).
  5. `db.commit()`; return the recomputed scores.
- **DRY refactor (preferred):** `_tool_reorder_slot` computes the target order list, then delegates
  position-reassignment to a shared helper so both the agent move and the DJ full-order PUT share one
  source of truth. **Fallback:** if the refactor proves invasive during TDD, share only
  `recompute_transition_scores` and leave `_tool_reorder_slot` untouched. The PR notes which path was
  taken.

**Endpoint** — `app/api/setbuilder.py`, mirroring `put_document_snapshot`
- `PUT /sets/{set_id}/slots/order`, `response_model` = transition-scores out.
- `Depends(get_current_active_user)` (DJ auth — NOT `get_current_user`, which allows pending).
- `_get_owned_or_404(db, set_id, current_user)` for ownership.
- `@limiter.limit("30/minute")` (mutation rate limit, matching sibling endpoints).
- Maps the service's permutation/locked errors to HTTP 400 with non-leaky messages.

### Frontend (`dashboard/app/(dj)/setbuilder/`)

**`components/dnd.ts`**
- `SLOT_REORDER_DND_TYPE = 'application/x-wrzdj-slot-reorder'`.
- `writeSlotReorderDragPayload(dataTransfer, { slotId })` — sets `effectAllowed='move'`.
- `readSlotReorderDragPayload(dataTransfer)` — parses + validates (integer `slotId`), returns `null`
  on malformed input (mirrors `readPoolTrackDragPayload`).

**`components/TimelineRow.tsx`**
- `draggable={!slot.locked}` (locked rows stay non-draggable).
- `onDragStart` writes the reorder payload; drag-handle cursor affordance via existing CSS module.
- Locked rows render unchanged.

**`components/TimelinePanel.tsx`**
- The existing `onDragOver` / `onDrop` handlers detect which payload type is present:
  - Pool-track payload → existing copy-insert behavior (unchanged).
  - Slot-reorder payload → compute target index via `insertIndexFromPointer`; reuse the `dropIdx`
    indicator; block the drop (`dropEffect='none'`) if it would cross or displace a locked slot.
- New prop `onSlotReorder(slotId: number, toIdx: number) => void | Promise<void>`.

**`components/BuilderWorkspace.tsx`**
- `handleSlotReorder(slotId, toIdx)`: build the new ordered-id array by moving `slotId` to `toIdx`
  among the current `slots` (respecting locked anchors), guard client-side, then
  `commit('Reorder slot', () => api.reorderSlots(setId, orderedIds))` followed by `loadSlots()`.
  Mirrors the existing `handlePoolTrackDrop`.

**`lib/api.ts`**
- `reorderSlots(setId: number, slotIds: number[])` → `PUT /api/setbuilder/sets/${setId}/slots/order`.

## Data flow

```
dragstart (write {slotId})
  → dragover: insertIndexFromPointer → dropIdx indicator; block if it crosses a lock
  → drop: handleSlotReorder(slotId, toIdx)
      → build new ordered-id array
      → commit('Reorder slot', () => api.reorderSlots(setId, orderedIds))
          → PUT /slots/order → apply_slot_order: validate → reassign positions → recompute scores
      → loadSlots()  (refresh timeline + curve view-models)
```

Undo/redo, autosave, and the unsaved-changes `beforeunload` guard are inherited from `commit()`.

## Error handling

- **Backend:** permutation mismatch and locked-slot displacement both return HTTP 400 with a clear,
  non-leaky message. No stack traces leak (per SECURITY.md). Parameterized ORM only.
- **Frontend:** `handleSlotReorder` wraps the commit in `try/catch`; on failure the visible timeline
  is left unchanged and `loadSlots()` re-syncs (mirrors `handlePoolTrackDrop`). `commit()` already
  surfaces `saveError`.

## Testing (TDD — RED first)

**Backend (`server/tests/`, pytest, ≥85% coverage gate):**
- `apply_slot_order` rejects a non-permutation payload (400).
- `apply_slot_order` rejects when a locked slot's index changes (400).
- Positions are reassigned to match `slot_ids`.
- Transition scores are recomputed for the **new** adjacencies — assert a concrete score change for a
  reorder that alters neighbors.
- Endpoint auth: pending user is rejected; another DJ's set returns 404.

**Frontend (`dashboard/.../__tests__/`, vitest):**
- `dnd.ts`: reorder payload round-trips; malformed input returns `null`.
- `TimelineRow`: `draggable` is true iff the slot is unlocked; `onDragStart` writes the payload.
- `TimelinePanel`: a reorder drop computes the correct target index; a drop that would cross a locked
  slot is blocked.
- `BuilderWorkspace`: a reorder commits via `api.reorderSlots` and refreshes; undo restores the prior
  order.

## Out of scope (tracked in #438)

- Touch / long-press reorder.
- Mobile single-column reorder view.
- Multi-row / batch selection drag (the full-order PUT supports it server-side, but no UI ships here).

## Acceptance criteria (from the issue)

- [ ] Drag a slot to a new index; order persists across reload.
- [ ] Locked slots cannot be moved or displaced.
- [ ] Transition scores recompute after reorder.
- [ ] Undo/redo restores prior order.
- [ ] Works with a large (virtualized) set.

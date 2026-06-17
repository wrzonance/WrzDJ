# Mobile-reorder view (#438) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add touch-friendly ▲/▼ move controls (always visible, desktop + mobile) that reorder timeline slots by reusing #437's reorder engine, plus a single-column timeline collapse on narrow viewports.

**Architecture:** A new pure `buildMovedIds(slots, slotId, direction)` (self-contained — computes a ±1 move and rejects illegal/locked-crossing moves) drives both the row's disabled state and `BuilderWorkspace.handleMoveSlot`, which commits via the existing `api.reorderSlots` + `commit()` path. Frontend-only; no backend changes.

**Tech Stack:** Next.js/React 19, vanilla CSS modules (no Tailwind), Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-17-issue-438-mobile-reorder-design.md`
**Branch:** `feat/issue-438` (already created off `origin/main`, which includes merged #437).

---

## File Structure

- **Create** `dashboard/app/(dj)/setbuilder/components/reorderMath.ts` — pure `buildMovedIds`.
- **Create** `dashboard/app/(dj)/setbuilder/components/__tests__/reorderMath.test.ts`.
- **Modify** `dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx` — ▲/▼ controls + `onMoveSlot` prop.
- **Modify** `dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx` — control tests.
- **Modify** `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx` — thread `onMoveSlot` prop.
- **Modify** `dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx` — threading test.
- **Modify** `dashboard/app/(dj)/setbuilder/components/BuilderWorkspace.tsx` — `handleMoveSlot` + wire prop.
- **Modify** `dashboard/app/(dj)/setbuilder/components/curve.module.css` — control styling + `@media` collapse.

Run all frontend commands from `dashboard/`. Single test file: `npm test -- --run "<path>"` (quote the parens in the path).

---

## Task 0: `reorderMath.ts` — `buildMovedIds` (pure)

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/reorderMath.ts`
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/reorderMath.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `dashboard/app/(dj)/setbuilder/components/__tests__/reorderMath.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { buildMovedIds } from '../reorderMath';
import type { SlotView } from '../types';

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

describe('buildMovedIds', () => {
  const slots = [slot(1), slot(2), slot(3)];

  it('moves a slot up one position', () => {
    expect(buildMovedIds(slots, 2, 'up')).toEqual([2, 1, 3]);
  });

  it('moves a slot down one position', () => {
    expect(buildMovedIds(slots, 2, 'down')).toEqual([1, 3, 2]);
  });

  it('returns null moving the first slot up (boundary)', () => {
    expect(buildMovedIds(slots, 1, 'up')).toBeNull();
  });

  it('returns null moving the last slot down (boundary)', () => {
    expect(buildMovedIds(slots, 3, 'down')).toBeNull();
  });

  it('returns null for an unknown slot id', () => {
    expect(buildMovedIds(slots, 999, 'up')).toBeNull();
  });

  it('returns null when the move would displace a locked slot', () => {
    const s = [slot(1), slot(2, true), slot(3)]; // lock at idx 1
    // Moving slot 3 up would push it into the locked slot's index.
    expect(buildMovedIds(s, 3, 'up')).toBeNull();
    // Moving slot 1 down would push it into the locked slot's index.
    expect(buildMovedIds(s, 1, 'down')).toBeNull();
  });

  it('allows a move that does not cross a locked slot', () => {
    const s = [slot(1), slot(2), slot(3, true), slot(4)]; // lock at idx 2
    expect(buildMovedIds(s, 1, 'down')).toEqual([2, 1, 3, 4]); // within [0,1], lock untouched
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run "app/(dj)/setbuilder/components/__tests__/reorderMath.test.ts"`
Expected: FAIL — `buildMovedIds` not exported.

- [ ] **Step 3: Implement**

Create `dashboard/app/(dj)/setbuilder/components/reorderMath.ts`:

```typescript
import type { SlotView } from './types';

export type MoveDirection = 'up' | 'down';

/**
 * Compute the new slot-id order for moving `slotId` one position in `direction`.
 * Returns null when the move is illegal: out of bounds, unknown slot, or it would
 * displace a locked slot (locked slots are immovable anchors — same invariant as
 * the desktop drag's buildReorderedIds). Used both to perform a move and to decide
 * whether a move control is enabled, so the two can never disagree.
 */
export function buildMovedIds(
  slots: SlotView[],
  slotId: number,
  direction: MoveDirection,
): number[] | null {
  const fromIdx = slots.findIndex((s) => s.id === slotId);
  if (fromIdx < 0) return null;
  const targetIdx = direction === 'up' ? fromIdx - 1 : fromIdx + 1;
  if (targetIdx < 0 || targetIdx > slots.length - 1) return null;
  const ids = slots.map((s) => s.id);
  const without = ids.filter((id) => id !== slotId);
  without.splice(targetIdx, 0, slotId);
  // Locked slots are immovable anchors — reject any move that shifts one.
  if (slots.some((s, idx) => s.locked && without[idx] !== s.id)) return null;
  return without;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- --run "app/(dj)/setbuilder/components/__tests__/reorderMath.test.ts"`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + tsc + commit**

```bash
cd dashboard && npm run lint && npx tsc --noEmit && cd ..
git add "dashboard/app/(dj)/setbuilder/components/reorderMath.ts" "dashboard/app/(dj)/setbuilder/components/__tests__/reorderMath.test.ts"
git commit -m "feat(setbuilder): add buildMovedIds reorder-by-direction helper (#438)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: `TimelineRow` ▲/▼ move controls

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx`
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx`

`TimelineRow` already receives `slot`, `idx`, `slots`. Add an `onMoveSlot` prop and render a ▲/▼ pair for unlocked slots, just before the existing lock-toggle button (`styles.timelineLockToggle`, ~line 261). Disabled state comes from `buildMovedIds`.

- [ ] **Step 1: Write the failing tests**

Append to `dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx` (the `slot()` helper already exists at the top of the file):

```typescript
function renderRowAt(slots: SlotView[], idx: number, onMoveSlot = vi.fn()) {
  render(
    <TimelineRow
      slot={slots[idx]} prevSlot={idx > 0 ? slots[idx - 1] : null}
      nextSlot={idx < slots.length - 1 ? slots[idx + 1] : null}
      idx={idx} slots={slots}
      hoveredIdx={null} currentIdx={-1} positionSec={0} playing={false}
      selected={false} dropIdx={null} setDropIdx={vi.fn()} onHover={vi.fn()}
      onSelectedChange={vi.fn()} setMenu={vi.fn()} onMoveSlot={onMoveSlot}
    />,
  );
  return onMoveSlot;
}

describe('TimelineRow move controls', () => {
  it('renders up/down controls for an unlocked slot', () => {
    renderRowAt([slot(1), slot(2), slot(3)], 1);
    expect(screen.getByTestId('timeline-move-up-1')).toBeTruthy();
    expect(screen.getByTestId('timeline-move-down-1')).toBeTruthy();
  });

  it('renders no move controls for a locked slot', () => {
    renderRowAt([slot(1), slot(2, true), slot(3)], 1);
    expect(screen.queryByTestId('timeline-move-up-1')).toBeNull();
    expect(screen.queryByTestId('timeline-move-down-1')).toBeNull();
  });

  it('disables up on the first slot and down on the last slot', () => {
    const slots = [slot(1), slot(2), slot(3)];
    renderRowAt(slots, 0);
    expect(screen.getByTestId('timeline-move-up-0').hasAttribute('disabled')).toBe(true);
    expect(screen.getByTestId('timeline-move-down-0').hasAttribute('disabled')).toBe(false);
  });

  it('calls onMoveSlot with the slot id and direction on click', () => {
    const onMoveSlot = renderRowAt([slot(1), slot(2), slot(3)], 1);
    fireEvent.click(screen.getByTestId('timeline-move-down-1'));
    expect(onMoveSlot).toHaveBeenCalledWith(2, 'down');
  });

  it('disables a move that would displace a locked slot', () => {
    const slots = [slot(1), slot(2, true), slot(3)]; // lock at idx 1
    renderRowAt(slots, 2); // slot 3; moving up would cross the locked slot
    expect(screen.getByTestId('timeline-move-up-2').hasAttribute('disabled')).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run "app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx"`
Expected: FAIL — controls/`onMoveSlot` not implemented.

- [ ] **Step 3: Implement**

In `TimelineRow.tsx`:

1. Add the import: `import { buildMovedIds } from './reorderMath';`
2. Add `onMoveSlot?: (slotId: number, direction: 'up' | 'down') => void | Promise<void>;` to `TimelineRowProps` (near `onToggleLock`), and add `onMoveSlot` to the destructured params.
3. Just before the lock-toggle `<button>` (the one with `className={styles.timelineLockToggle}`, ~line 261), insert the move controls:

```tsx
        {!slot.locked && (
          <span className={styles.timelineMoveControls}>
            <button
              type="button"
              className={styles.timelineMoveBtn}
              aria-label={`Move ${slot.track.title} up`}
              title="Move up"
              disabled={buildMovedIds(slots, slot.id, 'up') === null}
              onClick={(event) => {
                event.stopPropagation();
                void onMoveSlot?.(slot.id, 'up');
              }}
              data-testid={`timeline-move-up-${idx}`}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor"
                  strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
            </button>
            <button
              type="button"
              className={styles.timelineMoveBtn}
              aria-label={`Move ${slot.track.title} down`}
              title="Move down"
              disabled={buildMovedIds(slots, slot.id, 'down') === null}
              onClick={(event) => {
                event.stopPropagation();
                void onMoveSlot?.(slot.id, 'down');
              }}
              data-testid={`timeline-move-down-${idx}`}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 5v14M5 12l7 7 7-7" fill="none" stroke="currentColor"
                  strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
            </button>
          </span>
        )}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- --run "app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx"`
Expected: PASS (existing drag tests + 5 new move-control tests).

- [ ] **Step 5: Lint + tsc + commit**

```bash
cd dashboard && npm run lint && npx tsc --noEmit && cd ..
git add "dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx" "dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx"
git commit -m "feat(setbuilder): add up/down move controls to timeline rows (#438)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Thread `onMoveSlot` through `TimelinePanel` + `BuilderWorkspace.handleMoveSlot`

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/components/BuilderWorkspace.tsx`
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx` (it already mocks `useMeasuredVirtualList` and has a `slot()` helper + `renderPanel`). Extend `renderPanel` calls with `onMoveSlot`, or add a dedicated test:

```typescript
describe('TimelinePanel move controls', () => {
  it('threads onMoveSlot to rows so a control click reports slot id + direction', () => {
    const slots = [slot(1), slot(2), slot(3)];
    const onMoveSlot = vi.fn();
    render(
      <TimelinePanel
        slots={slots} hoveredIdx={null} currentIdx={-1} positionSec={0}
        playing={false} onHover={vi.fn()} scrollRequest={null}
        onMoveSlot={onMoveSlot}
      />,
    );
    fireEvent.click(screen.getByTestId('timeline-move-down-0'));
    expect(onMoveSlot).toHaveBeenCalledWith(1, 'down');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run "app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx"`
Expected: FAIL — `onMoveSlot` prop not on `TimelinePanel` / not threaded to rows.

- [ ] **Step 3: Implement TimelinePanel threading**

In `TimelinePanel.tsx`:
1. Add to `TimelinePanelProps`: `onMoveSlot?: (slotId: number, direction: 'up' | 'down') => void | Promise<void>;`
2. Destructure `onMoveSlot` in the component params.
3. On the `<TimelineRow ... />` element (where `onSlotReorder`/`onToggleLock` are passed), add: `onMoveSlot={onMoveSlot}`.

- [ ] **Step 4: Implement BuilderWorkspace handler + wiring**

In `BuilderWorkspace.tsx`:
1. Add import: `import { buildMovedIds } from './reorderMath';`
2. Add the handler after `handleSlotReorder` (~line 427), mirroring it:

```tsx
  const handleMoveSlot = useCallback(
    async (slotId: number, direction: 'up' | 'down') => {
      const orderedIds = buildMovedIds(slots, slotId, direction);
      if (!orderedIds) return;
      const save = async () => api.reorderSlots(setId, orderedIds);
      try {
        const run = commit ? commit('Move slot', save) : save();
        await run;
        await loadSlots();
      } catch {
        await loadSlots();
      }
    },
    [commit, loadSlots, setId, slots],
  );
```

3. Pass it to `<TimelinePanel>` (where `onSlotReorder={handleSlotReorder}` is, ~line 529): `onMoveSlot={handleMoveSlot}`.

- [ ] **Step 5: Run to verify pass + full components suite**

```bash
cd dashboard
npm test -- --run "app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx"
npm test -- --run "app/(dj)/setbuilder/components/__tests__"
npx tsc --noEmit
```
Expected: TimelinePanel test passes; full components suite passes; tsc clean (tsc proves `onMoveSlot={handleMoveSlot}` matches the prop type and `api.reorderSlots` arg types). No separate BuilderWorkspace render test — the move logic is covered by `reorderMath.test.ts` and the wiring by tsc + the TimelinePanel/TimelineRow tests (same rationale as #437's BuilderWorkspace wiring).

- [ ] **Step 6: Commit**

```bash
cd ..
git add "dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx" "dashboard/app/(dj)/setbuilder/components/BuilderWorkspace.tsx" "dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx"
git commit -m "feat(setbuilder): wire move controls through panel to reorder commit (#438)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Move-control styling + single-column mobile collapse (CSS)

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/curve.module.css`

CSS-only; verified by build + manual/screenshot (no unit test — CSS module class presence is exercised by the component tests above via `styles.timelineMoveControls` / `styles.timelineMoveBtn`). Follow the dark theme (`#ededed` on `#1a1a1a`) and match the existing `timelineLockToggle` button styling.

- [ ] **Step 1: Add control + responsive styles**

Append to `dashboard/app/(dj)/setbuilder/components/curve.module.css` (match the existing `.timelineLockToggle` rule's look — size, color, hover, focus-visible ring):

```css
.timelineMoveControls {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
}

.timelineMoveBtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 18px;
  padding: 0;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  background: #161616;
  color: #ededed;
  cursor: pointer;
}

.timelineMoveBtn:hover:not(:disabled) {
  background: #222;
}

.timelineMoveBtn:disabled {
  opacity: 0.3;
  cursor: default;
}

.timelineMoveBtn:focus-visible {
  outline: 2px solid #4a9eff;
  outline-offset: 1px;
}

/* Single-column, touch-friendly timeline on narrow viewports. */
@media (max-width: 640px) {
  .timelineRow {
    flex-wrap: wrap;
    row-gap: 4px;
    padding-top: 8px;
    padding-bottom: 8px;
  }

  .timelineMoveBtn {
    width: 44px;
    height: 44px;
  }

  /* De-emphasize non-essential metadata so order + lock + move stay primary. */
  .timelineTarget {
    display: none;
  }
}
```

> NOTE: if `.timelineRow` is not `display: flex` in this file (verify by reading it first), adapt the
> `@media` block to whatever the row's layout primitive is (grid/flex) — keep the goal: a comfortable
> single-column row with ≥44px move targets. Read the existing `.timelineRow` / `.timelineTarget` rules
> before editing and match their selectors exactly.

- [ ] **Step 2: Verify build + suite still green**

```bash
cd dashboard
npm run lint && npx tsc --noEmit
npm test -- --run "app/(dj)/setbuilder/components/__tests__"
```
Expected: all green (CSS module class additions don't break tests; the component tests reference the new classes).

- [ ] **Step 3: Commit**

```bash
cd ..
git add "dashboard/app/(dj)/setbuilder/components/curve.module.css"
git commit -m "feat(setbuilder): style move controls + single-column timeline on mobile (#438)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final: Full local CI + PR

- [ ] **Step 1: Full local gate**

```bash
cd dashboard
npm run lint && npx tsc --noEmit && npm test -- --run
git checkout next-env.d.ts 2>/dev/null || true
cd ..
```
Expected: eslint clean, tsc clean, full vitest green. (No backend changes — backend CI unaffected; but the remote CI will still run it.)

- [ ] **Step 2: Push + PR**

```bash
git push -u origin feat/issue-438
gh pr create --base main --title "feat(setbuilder): mobile-reorder view for the set timeline (#438)" --body "$(cat <<'EOF'
## Why
Native HTML5 drag (the #437 desktop reorder) does not fire on touch devices, so DJs can't reorder a set on a phone. This adds a touch-friendly, accessible reorder path.

## What
- ▲/▼ move controls on each unlocked timeline row (always visible — desktop a11y + mobile touch), each disabled when the move is illegal (boundary or would displace a locked slot).
- A new pure `buildMovedIds(slots, slotId, direction)` is the single source of truth for both the control's disabled state and the move itself, so they can't disagree.
- Moves reuse #437's engine end to end: `api.reorderSlots` through the `commit()` history path (undo/redo/autosave free). No backend changes.
- `@media (max-width: 640px)` collapses the timeline to a comfortable single column with ≥44px tap targets.

Full mobile builder shell (curve/chat as tabs/sheets) and long-press touch-drag are deferred to a follow-up.

## Testing
- [ ] `buildMovedIds` unit tests (up/down/boundary/unknown/locked-cross)
- [ ] `TimelineRow` control tests (render/locked/disabled/click)
- [ ] `TimelinePanel` threading test; `tsc` proves the wiring
- [ ] Frontend lint + tsc + vitest green; CI green
- [ ] Manual: on a narrow viewport, reorder slots via ▲/▼; locked slots have no controls; undo restores order

🤖 Co-authored by Claude Opus 4.8. Closes #438.
EOF
)"
```

- [ ] **Step 3: Drive to green** via the `review-remote-pr` loop (CI + CodeRabbit) until all checks pass and threads resolve.

---

## Self-Review (against the spec)

- **Spec coverage:** `buildMovedIds` in `reorderMath.ts` (T0) ✓; ▲/▼ controls, unlocked-only, disabled-from-`buildMovedIds`, stopPropagation+`onMoveSlot` (T1) ✓; panel threading (T2) ✓; `handleMoveSlot` via `commit`+`reorderSlots`+`loadSlots` (T2) ✓; single-column `@media` collapse + control styling (T3) ✓; reuse of #437 engine, no backend change ✓; all four acceptance criteria covered by T0–T3 + manual.
- **Placeholders:** the T3 `@media` block has a verify-the-`.timelineRow`-primitive note (read before editing) — that's a real instruction, not a TODO; the styling goal is explicit.
- **Type/name consistency:** `buildMovedIds`, `MoveDirection`, `onMoveSlot(slotId, direction)`, `timeline-move-up/down-${idx}`, `timelineMoveControls`/`timelineMoveBtn` used identically across T0–T3.

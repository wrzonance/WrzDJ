# Timeline Hand-Drag Reorder (#437) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let DJs reorder WrzDJSet timeline slots by hand-dragging rows, persisting the new order and recomputing transition scores, while respecting locked slots and undo/redo.

**Architecture:** A reusable backend reorder engine — `apply_slot_order` service (permutation + locked-invariant validation, position reassignment, Pass-1 rescore) behind a `PUT /sets/{id}/slots/order` endpoint — plus a frontend slice that extends the existing native-HTML5-DnD pattern: draggable rows, a slot-reorder `dataTransfer` payload, the existing virtualization-aware `insertIndexFromPointer`, and the `useSetDocumentHistory.commit()` path (which gives undo/redo/autosave for free).

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend); pytest. Next.js/React 19 + vanilla CSS (frontend); Vitest + Testing Library. OpenAPI→TS type generation via `openapi-typescript`.

**Spec:** `docs/superpowers/specs/2026-06-17-issue-437-timeline-reorder-design.md`
**Branch:** `feat/issue-437` (already created off `origin/main`).

---

## File Structure

**Backend (`server/`)**
- Create `app/services/setbuilder/reorder.py` — `ReorderError` + `apply_slot_order(db, set_obj, ordered_ids)`. Reuses `pass1_deterministic.recompute_transition_scores`.
- Modify `app/schemas/setbuilder.py` — add `SlotOrderRequest`.
- Modify `app/api/setbuilder.py` — add `PUT /sets/{set_id}/slots/order` (imports `reorder`, `SlotOrderRequest`).
- Create `tests/test_setbuilder_reorder.py` — service unit tests.
- Create `tests/test_setbuilder_reorder_api.py` — endpoint tests.

**Frontend (`dashboard/`)**
- Modify `app/(dj)/setbuilder/components/dnd.ts` — slot-reorder payload helpers.
- Modify `lib/api.ts` — `reorderSlots`.
- Regenerate `lib/api-types.generated.ts` (via `npm run types:export && npm run types:generate`).
- Modify `app/(dj)/setbuilder/components/TimelineRow.tsx` — draggable-when-unlocked + dragstart payload.
- Modify `app/(dj)/setbuilder/components/TimelinePanel.tsx` — reorder drop handling + cross-lock block + `onSlotReorder` prop.
- Modify `app/(dj)/setbuilder/components/BuilderWorkspace.tsx` — `handleSlotReorder` via `commit()`.
- Create `__tests__/dnd.test.ts`, `__tests__/TimelineRow.test.tsx`, `__tests__/TimelinePanel.test.tsx`, `__tests__/BuilderWorkspace.reorder.test.tsx`.

**Optional (preferred DRY, last):**
- Modify `app/services/setbuilder/pass2_agent.py` — `_tool_reorder_slot` delegates position-reassignment to `reorder.apply_slot_order`.

---

## Task 0: Backend — `apply_slot_order` service

**Files:**
- Create: `server/app/services/setbuilder/reorder.py`
- Test: `server/tests/test_setbuilder_reorder.py`

Run all backend commands from `server/` with the venv: `.venv/bin/pytest`, `.venv/bin/ruff`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_setbuilder_reorder.py`:

```python
"""Tests for DJ-driven full-order slot reordering (#437)."""

import pytest
from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.reorder import ReorderError, apply_slot_order


def _set_with_slots(db: Session, user: User, n: int, locked_idx: int | None = None) -> Set:
    set_obj = Set(owner_id=user.id, name="Friday", target_duration_sec=14 * 60)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    src = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.refresh(src)
    for i in range(n):
        db.add(
            SetPoolTrack(
                set_id=set_obj.id, source_id=src.id, track_id=f"tidal:{i}",
                title=f"T{i}", artist=f"A{i}", bpm=120.0 + i, key="8A", camelot="8A",
                energy=5, duration_sec=210, dedupe_sig=f"sig-{i}",
            )
        )
        db.add(
            SetSlot(
                set_id=set_obj.id, position=i, track_id=f"tidal:{i}",
                locked=(i == locked_idx),
            )
        )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _ids_in_order(set_obj: Set) -> list[int]:
    return [s.id for s in sorted(set_obj.slots, key=lambda s: s.position)]


def test_apply_slot_order_reassigns_positions(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3)
    ids = _ids_in_order(set_obj)
    new_order = [ids[2], ids[0], ids[1]]

    apply_slot_order(db, set_obj, new_order)
    db.refresh(set_obj)

    assert _ids_in_order(set_obj) == new_order
    assert sorted(s.position for s in set_obj.slots) == [0, 1, 2]


def test_apply_slot_order_recomputes_transition_scores(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3)
    ids = _ids_in_order(set_obj)

    scores = apply_slot_order(db, set_obj, [ids[2], ids[0], ids[1]])

    # First slot in the new order scores 100; scores are keyed to new positions.
    by_pos = {s.position: s for s in scores}
    assert by_pos[0].score == 100.0
    assert {s.slot_id for s in scores} == set(ids)


def test_apply_slot_order_rejects_non_permutation(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3)
    ids = _ids_in_order(set_obj)
    with pytest.raises(ReorderError, match="permutation"):
        apply_slot_order(db, set_obj, [ids[0], ids[1]])  # missing one
    with pytest.raises(ReorderError, match="permutation"):
        apply_slot_order(db, set_obj, [ids[0], ids[1], 99999])  # unknown id


def test_apply_slot_order_rejects_moving_locked_slot(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3, locked_idx=1)
    ids = _ids_in_order(set_obj)
    # Moving the locked middle slot to the front must fail.
    with pytest.raises(ReorderError, match="locked"):
        apply_slot_order(db, set_obj, [ids[1], ids[0], ids[2]])


def test_apply_slot_order_allows_reorder_that_keeps_locked_position(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3, locked_idx=1)
    ids = _ids_in_order(set_obj)
    # Swapping the two unlocked ends keeps the locked slot at index 1 — allowed.
    apply_slot_order(db, set_obj, [ids[2], ids[1], ids[0]])
    db.refresh(set_obj)
    assert _ids_in_order(set_obj) == [ids[2], ids[1], ids[0]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_setbuilder_reorder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.setbuilder.reorder'`.

- [ ] **Step 3: Write the minimal implementation**

Create `server/app/services/setbuilder/reorder.py`:

```python
"""DJ-driven full-order slot reordering for WrzDJSet (#437).

Reuses Pass-1 transition scoring so a hand-drag reorder scores identically to
the agent's ``reorder_slot`` tool.
"""

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.pass1_deterministic import (
    TransitionScore,
    recompute_transition_scores,
)


class ReorderError(ValueError):
    """Requested order is not a permutation, or would move a locked slot."""


def apply_slot_order(
    db: Session, set_obj: Set, ordered_ids: list[int], *, commit: bool = True
) -> list[TransitionScore]:
    """Reassign slot positions to match ``ordered_ids`` and rescore transitions.

    * ``ordered_ids`` must be a permutation of the set's current slot ids.
    * Every locked slot must keep its current position (immovable anchor).
    """
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    if sorted(ordered_ids) != sorted(s.id for s in slots):
        raise ReorderError("slot_ids must be a permutation of the set's slots")

    by_id = {s.id: s for s in slots}
    for new_position, slot_id in enumerate(ordered_ids):
        slot = by_id[slot_id]
        if slot.locked and slot.position != new_position:
            raise ReorderError("Reorder would move a locked slot")

    reordered = [by_id[slot_id] for slot_id in ordered_ids]
    for new_position, slot in enumerate(reordered):
        slot.position = new_position
    db.flush()
    return recompute_transition_scores(db, set_obj, reordered, commit=commit)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_setbuilder_reorder.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd server
.venv/bin/ruff check --fix app/services/setbuilder/reorder.py tests/test_setbuilder_reorder.py
.venv/bin/ruff format app/services/setbuilder/reorder.py tests/test_setbuilder_reorder.py
cd ..
git add server/app/services/setbuilder/reorder.py server/tests/test_setbuilder_reorder.py
git commit -m "feat(setbuilder): add apply_slot_order reorder+rescore service (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: Backend — `SlotOrderRequest` schema + `PUT /slots/order` endpoint

**Files:**
- Modify: `server/app/schemas/setbuilder.py` (add `SlotOrderRequest` after `BuildSetResponse`, ~line 453)
- Modify: `server/app/api/setbuilder.py` (add endpoint after `update_slot_target`, ~line 530; extend two imports)
- Test: `server/tests/test_setbuilder_reorder_api.py`

- [ ] **Step 1: Write the failing endpoint tests**

Create `server/tests/test_setbuilder_reorder_api.py`:

```python
"""Endpoint tests for hand-drag slot reorder (#437)."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User


def _make_set_with_slots(db: Session, owner: User, n: int, locked_idx: int | None = None) -> Set:
    set_obj = Set(owner_id=owner.id, name="Friday", target_duration_sec=14 * 60)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    src = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.refresh(src)
    for i in range(n):
        db.add(
            SetPoolTrack(
                set_id=set_obj.id, source_id=src.id, track_id=f"tidal:{i}",
                title=f"T{i}", artist=f"A{i}", bpm=120.0 + i, key="8A", camelot="8A",
                energy=5, duration_sec=210, dedupe_sig=f"sig-{i}",
            )
        )
        db.add(SetSlot(set_id=set_obj.id, position=i, track_id=f"tidal:{i}", locked=(i == locked_idx)))
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _ordered_ids(client, set_id: int, headers) -> list[int]:
    rows = client.get(f"/api/setbuilder/sets/{set_id}/slots", headers=headers).json()
    return [r["id"] for r in sorted(rows, key=lambda r: r["position"])]


def test_reorder_slots_persists_new_order(client, db: Session, test_user: User, auth_headers):
    set_obj = _make_set_with_slots(db, test_user, 3)
    ids = _ordered_ids(client, set_obj.id, auth_headers)
    new_order = [ids[2], ids[0], ids[1]]

    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": new_order},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert _ordered_ids(client, set_obj.id, auth_headers) == new_order
    # Response carries recomputed scores keyed to new positions.
    scores = {s["position"]: s for s in resp.json()}
    assert scores[0]["score"] == 100.0


def test_reorder_rejects_non_permutation(client, db: Session, test_user: User, auth_headers):
    set_obj = _make_set_with_slots(db, test_user, 3)
    ids = _ordered_ids(client, set_obj.id, auth_headers)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": ids[:2]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_reorder_rejects_moving_locked_slot(client, db: Session, test_user: User, auth_headers):
    set_obj = _make_set_with_slots(db, test_user, 3, locked_idx=1)
    ids = _ordered_ids(client, set_obj.id, auth_headers)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": [ids[1], ids[0], ids[2]]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_reorder_other_djs_set_is_404(client, db: Session, admin_user: User, test_user: User, auth_headers):
    # admin_user owns the set; test_user (auth_headers) must not reach it.
    set_obj = _make_set_with_slots(db, admin_user, 3)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": [s.id for s in set_obj.slots]},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_reorder_requires_active_user(client, db: Session, test_user: User, pending_headers):
    set_obj = _make_set_with_slots(db, test_user, 3)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": [s.id for s in set_obj.slots]},
        headers=pending_headers,
    )
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_setbuilder_reorder_api.py -v`
Expected: FAIL — 404/422 because the route does not exist yet.

- [ ] **Step 3: Add the schema**

In `server/app/schemas/setbuilder.py`, after `class BuildSetResponse` (~line 453), add:

```python
class SlotOrderRequest(BaseModel):
    """Full desired slot order for a set (hand-drag reorder, #437)."""

    slot_ids: list[int] = Field(..., min_length=1, max_length=500)
```

- [ ] **Step 4: Add the endpoint**

In `server/app/api/setbuilder.py`:

1. Add `SlotOrderRequest` to the `from app.schemas.setbuilder import (...)` block (line 24).
2. Add `reorder` to the `from app.services.setbuilder import (...)` block (line 93).
3. Insert after `update_slot_target` (after line 529):

```python
@router.put("/sets/{set_id}/slots/order", response_model=list[TransitionScoreOut])
@limiter.limit("30/minute")
def reorder_slots(
    set_id: int,
    payload: SlotOrderRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[TransitionScoreOut]:
    """Reassign the set's slot order by hand and recompute transition scores (#437)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    try:
        scores = reorder.apply_slot_order(db, set_obj, payload.slot_ids)
    except reorder.ReorderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _transition_scores_out(scores)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_setbuilder_reorder_api.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Full backend gate + commit**

```bash
cd server
.venv/bin/ruff check --fix app tests && .venv/bin/ruff format app tests
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
.venv/bin/alembic upgrade head && .venv/bin/alembic check
cd ..
git add server/app/schemas/setbuilder.py server/app/api/setbuilder.py server/tests/test_setbuilder_reorder_api.py
git commit -m "feat(setbuilder): add PUT /sets/{id}/slots/order reorder endpoint (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: pytest passes with coverage ≥ 85%; `alembic check` reports no drift (no model change here).

---

## Task 2: Frontend — regenerate types + `api.reorderSlots`

**Files:**
- Regenerate: `dashboard/lib/api-types.generated.ts`
- Modify: `dashboard/lib/api.ts` (add method near `putSetDocument`, ~line 717; ensure `TransitionScore` is imported)

- [ ] **Step 1: Regenerate the OpenAPI types**

```bash
cd dashboard
npm run types:export      # writes ../server/openapi.json from FastAPI
npm run types:generate    # regenerates lib/api-types.generated.ts
git checkout next-env.d.ts 2>/dev/null || true
```

Verify `SlotOrderRequest` now appears: `grep -n "SlotOrderRequest" lib/api-types.generated.ts` → expect a hit.

- [ ] **Step 2: Add the api client method**

In `dashboard/lib/api.ts`, confirm `TransitionScore` is imported from `@/lib/api-types` (add it to the import if missing). Add after `putSetDocument` (~line 717):

```typescript
  async reorderSlots(setId: number, slotIds: number[]): Promise<TransitionScore[]> {
    return this.fetch(`/api/setbuilder/sets/${setId}/slots/order`, {
      method: 'PUT',
      body: JSON.stringify({ slot_ids: slotIds }),
    });
  }
```

- [ ] **Step 3: Verify types + lint**

```bash
cd dashboard
npx tsc --noEmit
npm run lint
```

Expected: no errors; no api-types drift (the generated file is up to date with the backend).

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/api.ts dashboard/lib/api-types.generated.ts
git commit -m "feat(setbuilder): add reorderSlots api client + regenerate types (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Frontend — `dnd.ts` slot-reorder payload (TDD)

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/dnd.ts`
- Test: Create `dashboard/app/(dj)/setbuilder/components/__tests__/dnd.test.ts`

Run frontend tests from `dashboard/`: `npm test -- --run <path>`.

- [ ] **Step 1: Write the failing tests**

Create `dashboard/app/(dj)/setbuilder/components/__tests__/dnd.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import {
  SLOT_REORDER_DND_TYPE,
  writeSlotReorderDragPayload,
  readSlotReorderDragPayload,
} from '../dnd';

function fakeDataTransfer(): DataTransfer {
  const store: Record<string, string> = {};
  return {
    effectAllowed: 'none',
    dropEffect: 'none',
    setData: (type: string, val: string) => {
      store[type] = val;
    },
    getData: (type: string) => store[type] ?? '',
  } as unknown as DataTransfer;
}

describe('slot reorder drag payload', () => {
  it('round-trips a slot id', () => {
    const dt = fakeDataTransfer();
    writeSlotReorderDragPayload(dt, 42);
    expect(dt.effectAllowed).toBe('move');
    expect(readSlotReorderDragPayload(dt)).toEqual({ slotId: 42 });
  });

  it('returns null for a missing payload', () => {
    expect(readSlotReorderDragPayload(fakeDataTransfer())).toBeNull();
  });

  it('returns null for a malformed payload', () => {
    const dt = fakeDataTransfer();
    dt.setData(SLOT_REORDER_DND_TYPE, '{"slotId":"nope"}');
    expect(readSlotReorderDragPayload(dt)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/dnd.test.ts`
Expected: FAIL — exports not defined.

- [ ] **Step 3: Implement**

Append to `dashboard/app/(dj)/setbuilder/components/dnd.ts`:

```typescript
export const SLOT_REORDER_DND_TYPE = 'application/x-wrzdj-slot-reorder';

export interface SlotReorderDragPayload {
  slotId: number;
}

export function writeSlotReorderDragPayload(dataTransfer: DataTransfer, slotId: number): void {
  dataTransfer.effectAllowed = 'move';
  dataTransfer.setData(SLOT_REORDER_DND_TYPE, JSON.stringify({ slotId }));
  dataTransfer.setData('text/plain', String(slotId));
}

export function readSlotReorderDragPayload(
  dataTransfer: DataTransfer,
): SlotReorderDragPayload | null {
  const raw = dataTransfer.getData(SLOT_REORDER_DND_TYPE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { slotId?: unknown };
    return typeof parsed.slotId === 'number' && Number.isInteger(parsed.slotId)
      ? { slotId: parsed.slotId }
      : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/dnd.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/(dj)/setbuilder/components/dnd.ts" "dashboard/app/(dj)/setbuilder/components/__tests__/dnd.test.ts"
git commit -m "feat(setbuilder): add slot-reorder drag payload helpers (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend — `TimelineRow` draggable when unlocked (TDD)

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx` (the row `<div>` at line 150–174: `draggable={false}` → conditional; add `onDragStart`)
- Test: Create `dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TimelineRow from '../TimelineRow';
import type { SlotView } from '../types';
import { readSlotReorderDragPayload } from '../dnd';

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

function renderRow(s: SlotView) {
  const slots = [s];
  return render(
    <TimelineRow
      slot={s} prevSlot={null} nextSlot={null} idx={0} slots={slots}
      hoveredIdx={null} currentIdx={-1} positionSec={0} playing={false}
      selected={false} dropIdx={null} setDropIdx={vi.fn()} onHover={vi.fn()}
      onSelectedChange={vi.fn()} setMenu={vi.fn()}
    />,
  );
}

function fakeDataTransfer(): DataTransfer {
  const store: Record<string, string> = {};
  return {
    effectAllowed: 'none',
    setData: (t: string, v: string) => { store[t] = v; },
    getData: (t: string) => store[t] ?? '',
  } as unknown as DataTransfer;
}

describe('TimelineRow drag source', () => {
  it('is draggable when the slot is unlocked', () => {
    renderRow(slot(1, false));
    expect(screen.getByTestId('timeline-row-0').getAttribute('draggable')).toBe('true');
  });

  it('is not draggable when the slot is locked', () => {
    renderRow(slot(1, true));
    expect(screen.getByTestId('timeline-row-0').getAttribute('draggable')).toBe('false');
  });

  it('writes the slot id on drag start', () => {
    renderRow(slot(7, false));
    const dt = fakeDataTransfer();
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    expect(readSlotReorderDragPayload(dt)).toEqual({ slotId: 7 });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/TimelineRow.test.tsx`
Expected: FAIL — row is `draggable="false"` always; no dragstart payload.

- [ ] **Step 3: Implement**

In `TimelineRow.tsx`:
1. Add to the imports from `./dnd` (line 5): `writeSlotReorderDragPayload`.
2. On the row `<div>` (line 150), replace `draggable={false}` with:

```tsx
        draggable={!slot.locked}
        onDragStart={(event) => {
          if (slot.locked) {
            event.preventDefault();
            return;
          }
          writeSlotReorderDragPayload(event.dataTransfer, slot.id);
        }}
```

(Leave the existing `onDragOver` / `onDragLeave` / `onDrop` pool-track handlers in place — they coexist.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/TimelineRow.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/(dj)/setbuilder/components/TimelineRow.tsx" "dashboard/app/(dj)/setbuilder/components/__tests__/TimelineRow.test.tsx"
git commit -m "feat(setbuilder): make unlocked timeline rows drag sources (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend — `TimelinePanel` reorder drop + cross-lock block (TDD)

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx`
- Test: Create `dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx`

**Design notes for this task:**
- Add prop `onSlotReorder?: (slotId: number, insertIdx: number) => void | Promise<void>` to `TimelinePanelProps`.
- Track the dragged source via a ref set on the bubbling `onDragStart` of the list container (`dragstart` can read `dataTransfer`; `dragover` cannot read data, only types). Clear it on drop/dragend.
- Cross-lock block uses the agent's range rule: with `from` = source index and `target` = resolved insert index, reject if any locked slot sits in `[min(from,target), max(from,target)]` (excluding the source itself). Index === position because `slots` is position-ordered.
- Reuse `insertIndexFromPointer` for the insert index and the existing `dropIdx` indicator.

- [ ] **Step 1: Write the failing tests**

Create `dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TimelinePanel from '../TimelinePanel';
import type { SlotView } from '../types';
import { writeSlotReorderDragPayload, SLOT_REORDER_DND_TYPE } from '../dnd';

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

function reorderDataTransfer(slotId: number): DataTransfer {
  const store: Record<string, string> = {};
  const dt = {
    effectAllowed: 'none', dropEffect: 'none',
    setData: (t: string, v: string) => { store[t] = v; },
    getData: (t: string) => store[t] ?? '',
    get types() { return Object.keys(store); },
  } as unknown as DataTransfer;
  writeSlotReorderDragPayload(dt, slotId);
  return dt;
}

function renderPanel(slots: SlotView[], onSlotReorder = vi.fn()) {
  render(
    <TimelinePanel
      slots={slots} hoveredIdx={null} currentIdx={-1} positionSec={0}
      playing={false} onHover={vi.fn()} scrollRequest={null}
      onSlotReorder={onSlotReorder}
    />,
  );
  return onSlotReorder;
}

describe('TimelinePanel reorder drop', () => {
  it('calls onSlotReorder with the source slot id and target index', () => {
    const slots = [slot(1), slot(2), slot(3)];
    const onSlotReorder = renderPanel(slots);
    const dt = reorderDataTransfer(1);
    const list = screen.getByTestId('timeline-list');
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireEvent.dragOver(list, { dataTransfer: dt, clientY: 999 }); // far down → end
    fireEvent.drop(list, { dataTransfer: dt, clientY: 999 });
    expect(onSlotReorder).toHaveBeenCalledTimes(1);
    expect(onSlotReorder.mock.calls[0][0]).toBe(1);
  });

  it('does not reorder across a locked slot', () => {
    const slots = [slot(1), slot(2, true), slot(3)]; // slot 2 locked (index 1)
    const onSlotReorder = renderPanel(slots);
    const dt = reorderDataTransfer(1); // dragging index 0 to the end crosses the lock
    const list = screen.getByTestId('timeline-list');
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireEvent.drop(list, { dataTransfer: dt, clientY: 999 });
    expect(onSlotReorder).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/TimelinePanel.test.tsx`
Expected: FAIL — `onSlotReorder` prop unknown / not called.

- [ ] **Step 3: Implement**

In `TimelinePanel.tsx`:

1. Extend the `./dnd` import (line 19): add `readSlotReorderDragPayload, SLOT_REORDER_DND_TYPE`.
2. Add to `TimelinePanelProps`:

```tsx
  onSlotReorder?: (slotId: number, insertIdx: number) => void | Promise<void>;
```

3. Destructure `onSlotReorder` in the component params.
4. Add a source ref near the other refs (after line 77):

```tsx
  const reorderSourceRef = useRef<number | null>(null);
```

5. Add reorder handlers (place near the existing pool handlers, ~line 256):

```tsx
  const dragIsReorder = (event: DragEvent<HTMLElement>) =>
    event.dataTransfer.types.includes(SLOT_REORDER_DND_TYPE);

  const reorderWouldCrossLock = (fromIdx: number, insertIdx: number) => {
    const target = insertIdx > fromIdx ? insertIdx - 1 : insertIdx;
    const lo = Math.min(fromIdx, target);
    const hi = Math.max(fromIdx, target);
    return slots.some((s, i) => s.locked && i !== fromIdx && i >= lo && i <= hi);
  };

  const handleListDragStart = (event: DragEvent<HTMLElement>) => {
    const payload = readSlotReorderDragPayload(event.dataTransfer);
    reorderSourceRef.current = payload ? payload.slotId : null;
  };

  const clearReorderSource = () => {
    reorderSourceRef.current = null;
  };

  const markReorderDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const slotId = reorderSourceRef.current;
    const fromIdx = slotId == null ? -1 : slots.findIndex((s) => s.id === slotId);
    const insertIdx = insertIndexFromPointer(event);
    if (fromIdx < 0 || reorderWouldCrossLock(fromIdx, insertIdx)) {
      event.dataTransfer.dropEffect = 'none';
      setDropIdx(null);
      return;
    }
    event.dataTransfer.dropEffect = 'move';
    setDropIdx(insertIdx);
  };

  const handleReorderDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDropIdx(null);
    const slotId = reorderSourceRef.current;
    clearReorderSource();
    if (slotId == null) return;
    const fromIdx = slots.findIndex((s) => s.id === slotId);
    const insertIdx = insertIndexFromPointer(event);
    if (fromIdx < 0 || reorderWouldCrossLock(fromIdx, insertIdx)) return;
    void onSlotReorder?.(slotId, insertIdx);
  };
```

6. Update the list `<div data-testid="timeline-list">` (line 313) to branch by payload type. Replace its `onDragOver` / `onDrop` and add `onDragStart` / `onDragEnd`:

```tsx
        onDragStart={handleListDragStart}
        onDragEnd={clearReorderSource}
        onDragOver={(event) =>
          dragIsReorder(event) ? markReorderDrop(event) : markPoolTrackDropAtPointer(event)
        }
        onDragLeave={clearDropIfLeaving}
        onDrop={(event) =>
          dragIsReorder(event) ? handleReorderDrop(event) : handlePoolTrackDropAtPointer(event)
        }
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/TimelinePanel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/(dj)/setbuilder/components/TimelinePanel.tsx" "dashboard/app/(dj)/setbuilder/components/__tests__/TimelinePanel.test.tsx"
git commit -m "feat(setbuilder): handle slot-reorder drops in TimelinePanel (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Frontend — `BuilderWorkspace.handleSlotReorder` via `commit()` (TDD)

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/BuilderWorkspace.tsx` (add handler near `handlePoolTrackDrop` ~line 370; pass `onSlotReorder` to `<TimelinePanel>` ~line 480)
- Test: Create `dashboard/app/(dj)/setbuilder/components/__tests__/BuilderWorkspace.reorder.test.tsx`

The handler builds the new ordered-id array, applies the same client-side locked guard, commits through history, then reloads slots. Mirrors `handlePoolTrackDrop`.

- [ ] **Step 1: Write the failing test**

Create `dashboard/app/(dj)/setbuilder/components/__tests__/BuilderWorkspace.reorder.test.tsx`. Mock `@/lib/api` (mirror `PoolPanel.test.tsx`'s `vi.hoisted` + `vi.mock` pattern). Render `BuilderWorkspace`, drive a reorder through the timeline list, and assert `api.reorderSlots` is called with the rebuilt order.

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { writeSlotReorderDragPayload } from '../dnd';

const mockApi = vi.hoisted(() => ({
  getSetSlots: vi.fn(),
  getSetDocument: vi.fn(),
  putSetDocument: vi.fn(),
  reorderSlots: vi.fn(),
  getTransportStatus: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>();
  return { api: mockApi, ApiError: original.ApiError };
});

// NOTE: implementer fills in the minimal BuilderWorkspace props + slot/document
// fixtures (3 slots, none locked) following the component's current prop shape.
// getSetSlots resolves the 3 slots; getSetDocument resolves a snapshot; reorderSlots resolves [].

function reorderDataTransfer(slotId: number): DataTransfer {
  const store: Record<string, string> = {};
  const dt = {
    effectAllowed: 'none', dropEffect: 'none',
    setData: (t: string, v: string) => { store[t] = v; },
    getData: (t: string) => store[t] ?? '',
    get types() { return Object.keys(store); },
  } as unknown as DataTransfer;
  writeSlotReorderDragPayload(dt, slotId);
  return dt;
}

describe('BuilderWorkspace slot reorder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.reorderSlots.mockResolvedValue([]);
  });

  it('commits a reorder via api.reorderSlots with the rebuilt order', async () => {
    // ...render BuilderWorkspace with 3 slots [id1,id2,id3]...
    const dt = reorderDataTransfer(/* id of first slot */ 1);
    const list = await screen.findByTestId('timeline-list');
    fireEvent.dragStart(screen.getByTestId('timeline-row-0'), { dataTransfer: dt });
    fireEvent.drop(list, { dataTransfer: dt, clientY: 999 }); // move first slot to the end
    await waitFor(() => expect(mockApi.reorderSlots).toHaveBeenCalledTimes(1));
    const [, orderedIds] = mockApi.reorderSlots.mock.calls[0];
    expect(orderedIds[orderedIds.length - 1]).toBe(1); // moved slot is now last
  });
});
```

> If wiring a full `BuilderWorkspace` render proves heavy, this behavior may instead be unit-tested by extracting the order-rebuild + guard into a tiny pure helper `buildReorderedIds(slots, slotId, insertIdx)` in `BuilderWorkspace.tsx` (exported) and testing that directly. Prefer the integration test; fall back to the helper test only if the render is intractable. Document the choice in the PR.

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/BuilderWorkspace.reorder.test.tsx`
Expected: FAIL — `onSlotReorder` not wired / `reorderSlots` never called.

- [ ] **Step 3: Implement**

In `BuilderWorkspace.tsx`, add after `handlePoolTrackDrop` (~line 389):

```tsx
  const handleSlotReorder = useCallback(
    async (slotId: number, insertIdx: number) => {
      const fromIdx = slots.findIndex((slot) => slot.id === slotId);
      if (fromIdx < 0) return;
      const target = insertIdx > fromIdx ? insertIdx - 1 : insertIdx;
      if (target === fromIdx) return;
      const ids = slots.map((slot) => slot.id);
      const without = ids.filter((id) => id !== slotId);
      without.splice(target, 0, slotId);
      // Client-side locked-anchor guard (the backend enforces this too).
      if (slots.some((slot, idx) => slot.locked && without[idx] !== slot.id)) return;
      const save = async () => api.reorderSlots(setId, without);
      try {
        const run = commit ? commit('Reorder slot', save) : save();
        await run;
        await loadSlots();
      } catch {
        await loadSlots();
      }
    },
    [commit, loadSlots, setId, slots],
  );
```

Then pass it to `<TimelinePanel>` (~line 480):

```tsx
          onSlotReorder={handleSlotReorder}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- --run app/\(dj\)/setbuilder/components/__tests__/BuilderWorkspace.reorder.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/(dj)/setbuilder/components/BuilderWorkspace.tsx" "dashboard/app/(dj)/setbuilder/components/__tests__/BuilderWorkspace.reorder.test.tsx"
git commit -m "feat(setbuilder): wire hand-drag reorder commit in BuilderWorkspace (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7 (OPTIONAL, preferred DRY): `_tool_reorder_slot` delegates to `apply_slot_order`

Honors the spec's preferred refactor. **Skip and revert this task if the agent test suite regresses** — the fallback (independent implementations sharing only `recompute_transition_scores`) is acceptable and already shipped in Tasks 0–1.

**Files:**
- Modify: `server/app/services/setbuilder/pass2_agent.py` (`_tool_reorder_slot`, lines 270–291)

- [ ] **Step 1: Run the existing agent tests to capture the green baseline**

Run: `.venv/bin/pytest tests/ -k "agent or pass2 or reorder" -q`
Expected: PASS — record the count.

- [ ] **Step 2: Refactor `_tool_reorder_slot` to compute the new order then delegate**

Replace the position-reassignment tail of `_tool_reorder_slot` so it builds `ordered_ids` (move `slot` to `new_position`) and calls `reorder.apply_slot_order(db, set_obj, ordered_ids, commit=False)`, keeping the existing locked-slot guard and the `set(range(low, high + 1))` affected-positions return. Import `from app.services.setbuilder import reorder` (guard against a circular import; if one appears, import inside the function).

- [ ] **Step 3: Run agent tests + new reorder tests**

Run: `.venv/bin/pytest tests/ -k "agent or pass2 or reorder" -q`
Expected: PASS — same count as Step 1 plus the reorder tests.

- [ ] **Step 4: Decide**

If green → commit:

```bash
git add server/app/services/setbuilder/pass2_agent.py
git commit -m "refactor(setbuilder): share apply_slot_order between agent + DJ reorder (#437)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

If any agent test regresses → `git checkout server/app/services/setbuilder/pass2_agent.py` and note in the PR that the fallback path was kept.

---

## Final: Full local CI + PR

- [ ] **Step 1: Run the full local gate**

```bash
# Backend
cd server
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
.venv/bin/alembic upgrade head && .venv/bin/alembic check
# Frontend
cd ../dashboard
npm run lint && npx tsc --noEmit && npm test -- --run
git checkout next-env.d.ts 2>/dev/null || true
cd ..
```

Expected: all green; backend coverage ≥ 85%; no api-types drift.

- [ ] **Step 2: Push + open PR**

```bash
git push -u origin feat/issue-437
gh pr create --title "feat(setbuilder): hand-drag reordering of timeline slots (#437)" --body "$(cat <<'EOF'
## Why
DJs need direct manual control over set order — hand-arranging tracks to override
the deterministic builder and the agent. The shipped timeline rendered rows as
non-draggable.

## What
- Backend: `apply_slot_order` reorder engine (permutation + locked-anchor validation,
  Pass-1 transition rescore) behind `PUT /sets/{id}/slots/order`.
- Frontend: draggable unlocked rows, a slot-reorder drag payload, reorder drop handling
  reusing the virtualization-aware `insertIndexFromPointer`, and a `commit()`-routed
  reorder so undo/redo/autosave come for free.
- Locked slots are immovable anchors (enforced client- and server-side).
- [Note here whether Task 7's agent DRY refactor landed or the fallback was kept.]

Foundation for #438 (mobile-reorder view).

## Testing
- [ ] Backend unit + endpoint tests pass (`pytest`, coverage ≥ 85%)
- [ ] Frontend vitest passes (`dnd`, `TimelineRow`, `TimelinePanel`, `BuilderWorkspace`)
- [ ] Manual: drag a slot to a new index; order persists across reload
- [ ] Manual: locked slots cannot be moved or displaced
- [ ] Manual: transition score chips update after a reorder
- [ ] Manual: Cmd/Ctrl+Z undoes the reorder
- [ ] Manual: reorder works on a large (virtualized) set
- [ ] CI green

🤖 Co-authored by Claude Opus 4.8. Closes #437.
EOF
)"
```

- [ ] **Step 3: Drive the PR to green** — CI + CodeRabbit via the `review-remote-pr` loop until all checks pass and threads resolve.

---

## Self-Review (completed against the spec)

- **Spec coverage:** full-order PUT (Task 1) ✓; `apply_slot_order` permutation + locked-invariant + Pass-1 rescore (Task 0) ✓; DJ auth + ownership + rate limit (Task 1) ✓; native-DnD payload (Task 3) ✓; draggable-when-unlocked (Task 4) ✓; `insertIndexFromPointer` reuse + cross-lock block + `onSlotReorder` (Task 5) ✓; `commit()` path → undo/redo/autosave (Task 6) ✓; DRY refactor with documented fallback (Task 7) ✓; virtualization acceptance covered by reuse + manual PR check ✓; type regeneration (Task 2) ✓.
- **Placeholders:** the only deliberately-open spot is Task 6's `BuilderWorkspace` fixture wiring, with an explicit pure-helper fallback and a rule to document the choice — not a silent TODO.
- **Type/name consistency:** `apply_slot_order` / `ReorderError` / `SlotOrderRequest` / `reorderSlots` / `onSlotReorder` / `SLOT_REORDER_DND_TYPE` used identically across tasks; backend returns `list[TransitionScoreOut]`, frontend consumes `TransitionScore[]`.

# Set-length gating fix (#538) Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD (failing test first). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make set generation gate the produced track count by the set's length target (never by pool size), wiring the orphaned overlap-aware `targeting.py` into the deterministic builder, with a hard fallback cap when no target is set, and surface total pool runtime before generation.

**Architecture:** Replace the inline `round(target/avg)` slot-count math in `pass1_deterministic._slot_count` with a duration-accumulating greedy loop that stops at the overlap-aware target (via `targeting.pass1_slot_budget_from_durations`). When no target is set, cap the generated set at a named fallback constant instead of dumping the whole pool. Compute Σ pool runtime and expose it on `PoolState` + show it in the build-confirmation dialog (frontend computes from the document snapshot it already holds).

**Tech Stack:** FastAPI / SQLAlchemy / Pydantic backend; Next.js 19 / React / vanilla CSS frontend; pytest + vitest.

## Global Constraints

- Backend ruff line-length 100; rules E, F, I, UP. `== None`/`== True` allowed.
- Backend coverage is an ENFORCED hard gate (`--cov-fail-under`). New code must keep it green.
- Frontend: vanilla CSS + inline React styles. NO Tailwind. Dark theme.
- Do NOT disturb #543 energy/mood overlay or #545 genre term in `pass1_deterministic.py`.
- Pool import stays UNCAPPED. No import cap anywhere.
- Conventional Commits; each commit ends with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Hard fallback cap + overlap-aware duration-accumulating slot selection

**Files:**
- Modify: `server/app/services/setbuilder/pass1_deterministic.py` (`build_set`, `_slot_count` → replaced by `_select_chosen` driven by `targeting`; add `DEFAULT_FALLBACK_SET_DURATION_SEC`)
- Modify: `server/tests/test_setbuilder_pass1.py` (update exact-count expectations to overlap-aware values)
- Modify: `server/tests/test_setbuilder_pass1_genre.py` (count assertion in tie-break test)
- Test: `server/tests/test_setbuilder_pass1.py` (new no-target-bound + within-tolerance regression tests)

**Decisions:**
- `DEFAULT_FALLBACK_SET_DURATION_SEC = 3 * 60 * 60` (3 hours) — the largest "named" preset short of marathon; documented as the cap used when `target_duration_sec` is None so an unbounded pool never becomes a 12-hour set.
- Greedy loop unchanged in *how* it picks (best score first); the change is *when it stops*: accumulate each chosen track's real duration and stop once the overlap-aware effective duration reaches the effective target (target = `target_duration_sec` or the fallback). Use `targeting.effective_duration_sec` semantics (matching `pass1_slot_budget_from_durations`).
- Locked-slot invariant preserved: still clamp final slot count up to `max(locked position)+1` and never exceed pool size.

- [ ] **Step 1: Write failing test — no target dumps nothing beyond fallback cap**

```python
def test_build_set_no_target_is_bounded_by_fallback_cap(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=None)
    src = _mk_source(db, set_obj)
    for idx in range(400):
        _mk_track(db, set_obj, src, idx, duration_sec=210)
    result = build_set(db, set_obj)
    # 3h fallback / ~210s overlap-aware ≈ 53 slots, never the whole 400-track pool.
    assert result.slot_count < 400
    assert result.slot_count <= 60
```
(`_mk_set` must accept `duration: int | None`.)

- [ ] **Step 2: Write failing test — engine matches pass1_slot_budget_from_durations**

```python
def test_build_set_matches_overlap_aware_budget(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=14 * 60)
    src = _mk_source(db, set_obj)
    for idx in range(20):
        _mk_track(db, set_obj, src, idx, duration_sec=210)
    result = build_set(db, set_obj)
    from app.services.setbuilder import targeting
    budget = targeting.pass1_slot_budget_from_durations(
        target_duration_sec=14 * 60,
        track_durations_sec=[210] * result.slot_count,
        avg_transition_overlap_sec=set_obj.avg_transition_overlap_sec,
    )
    assert result.slot_count == budget.slot_count
    assert budget.within_overflow_tolerance is True
```

- [ ] **Step 3: Run both — expect FAIL** (`_mk_set` signature / count mismatch).

- [ ] **Step 4: Implement** — add constant, replace `_slot_count` with target-budget + duration-accumulating selection inside `build_set`; keep locked clamps.

- [ ] **Step 5: Update existing exact-count assertions** to the overlap-aware values:
  - `test_build_set_fills_target_duration_deterministically`: `slot_count == 4` → `== 5`.
  - `test_genre_continuity_breaks_tie_toward_matching_genre`: `duration=210 * 2` → `duration=410` so it stays 2 slots; keep `slots[1] == "tidal:techhouse"`.

- [ ] **Step 6: Run full pass1 suites green.**

- [ ] **Step 7: Commit.**

---

### Task 2: Total pool runtime on PoolState + regen types

**Files:**
- Modify: `server/app/services/setbuilder/pool.py` (helper `pool_runtime_sec`)
- Modify: `server/app/schemas/setbuilder.py` (`PoolState.runtime_sec: int`)
- Modify: `server/app/api/setbuilder.py` (`_pool_state` fills `runtime_sec`)
- Modify: `server/openapi.json`, `dashboard/lib/api-types.generated.ts` (regen)
- Test: `server/tests/test_setbuilder_pool_api.py` or `test_setbuilder_pool_service.py`

**Decisions:**
- `runtime_sec` = Σ `duration_sec` with the pass-1 average fallback (`AVG_TRACK_LENGTH_SEC`) for missing/<=0 durations, so it matches what the builder actually budgets against.

- [ ] **Step 1: Write failing test** asserting `get_pool_state(...).runtime_sec` equals the summed durations (with fallback for a None-duration track).
- [ ] **Step 2: Run — FAIL** (no field).
- [ ] **Step 3: Implement** helper + schema field + wire into `_pool_state`.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Regen** `openapi.json` + `api-types.generated.ts`; `alembic check` not needed (no migration).
- [ ] **Step 6: Commit.**

---

### Task 3: Surface pool runtime + projected slot count in the build dialog

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` (`requestBuild` dialog body)
- Create: `dashboard/app/(dj)/setbuilder/components/poolRuntime.ts` (pure helpers: `poolRuntimeSec`, `projectedSlotCount`) + colocated test
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/poolRuntime.test.ts`

**Decisions:**
- The page already loads `history.snapshot.pool.tracks` (each carries `duration_sec`) and `targetSettings`. Compute runtime + a projected slot count client-side (mirroring the backend overlap-aware budget) so the dialog can state: "Pool: N tracks (~M min). Target: T min → will build ~K slots; the remaining N−K stay in the pool." No new fetch needed.
- `projectedSlotCount` mirrors `effectiveDurationSec` from `targetMath.ts` (DRY: reuse it) and the 3h fallback when target is null.

- [ ] **Step 1: Write failing vitest** for `poolRuntimeSec` (sum + fallback) and `projectedSlotCount` (overlap-aware, fallback when null), agreeing with the backend budget.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** helpers using `effectiveDurationSec` + a shared `DEFAULT_FALLBACK_SET_DURATION_SEC`.
- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Wire** the line into the `requestBuild` confirmation dialog body.
- [ ] **Step 6: lint + tsc + vitest green; `git checkout next-env.d.ts` if touched.**
- [ ] **Step 7: Commit.**

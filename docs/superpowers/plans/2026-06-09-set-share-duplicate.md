# WrzDJSet Share Links + Duplicate Set (Issue #398) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DJs can duplicate a set (slots, curve, targets, vibe windows; status reset to draft) and share a read-only tokenized link (revoke/regenerate; no auth required to view; view-only on server and client).

**Architecture:** New nullable `share_token` column on `sets` (CSPRNG, unique, indexed). New router file `server/app/api/setbuilder_share.py` holds owner-scoped share/duplicate routes (`/api/setbuilder/...`) and a public read-only route (`/api/public/setbuilder/shared/{token}`) returning a sanitized projection (no ids, no owner identity). Service logic in new `server/app/services/setbuilder/share_service.py`. Frontend: additive API client methods, share dialog + duplicate action on the set list, actions menu in the builder topbar, and a new public page `/shared/[token]` rendering the view-only projection.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + slowapi; Next.js 16 / React 19, vanilla CSS; pytest + vitest.

**Shared-file courtesy:** changes to `server/app/api/setbuilder.py` (none needed), `server/app/schemas/setbuilder.py`, `dashboard/app/(dj)/setbuilder/page.tsx`, `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` are strictly ADDITIVE. Bulk of logic lives in new files.

**Design decisions (document in PR):**
- `share_token` lives on `Set` (nullable String(64), unique+indexed). NULL = not shared. Regenerate = overwrite, revoke = NULL. Generated via `secrets.token_urlsafe(32)` (43 chars).
- Public token lookup validates format (`[A-Za-z0-9_-]{20,64}`) before querying; bad format → 404 (same as unknown token; no oracle).
- Public projection (`SharedSetView`) exposes: set name, status, vibe/targets/key-strictness, slots (position, track_id, locked, notes, transition_score) and curve points (position_sec, energy, label, slow-window flags). It does NOT expose: any DB ids, owner identity, event link, collaborators, tidal playlist id, share token echo.
- Duplicate copies: name + " (copy)" (truncated to 120), event_id, vibe_theme, targets, bpm floor/ceiling, key_strictness, all slots, all curve points (incl. slow-window flags = "vibe windows"). Resets: status="draft", sharing_mode="private", share_token=None, tidal_playlist_id=None, exported_at=None.
- "Brand menu" from the design mock doesn't exist in the Phase 0 shell — Duplicate/Share land in a new `SetActionsMenu` component mounted in the builder topbar (replaces the spacer span), plus row actions on the set list.
- Frontend public page route: `/shared/[token]` (outside the `(dj)` group; no auth hooks).
- `SetSummary` schema (backend + TS) gains `share_token` — owner-only endpoints, so returning the token there is safe and lets the list page surface share state + build the URL without extra calls.

---

### Task 1: Model column + Alembic migration 054

**Files:**
- Modify: `server/app/models/set.py` (add `share_token` column after `sharing_mode`)
- Create: `server/alembic/versions/054_add_set_share_token.py`

- [ ] **Step 1: Add column to model**

```python
    # CSPRNG read-only share token; NULL = not shared (issue #398)
    share_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
```

- [ ] **Step 2: Write migration** (down_revision = "052"; sibling PR #388 holds slot 053 — second to merge re-anchors)

```python
"""Add share_token to sets (issue #398).

Revision ID: 054
Revises: 052
Create Date: 2026-06-09

Nullable CSPRNG token enabling read-only public sharing of a set.
NULL means not shared; revoke nulls it, regenerate overwrites it.
Unique index gives O(log n) constant-pattern lookup on the public route.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "054"
down_revision: str | None = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sets", sa.Column("share_token", sa.String(length=64), nullable=True))
    op.create_index("ix_sets_share_token", "sets", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sets_share_token", table_name="sets")
    op.drop_column("sets", "share_token")
```

- [ ] **Step 3: Verify migration + drift**

Run: `docker compose up -d db && cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check`
Expected: upgrade applies 054, `alembic check` reports no new upgrade operations.

- [ ] **Step 4: Commit** — `feat(setbuilder): add share_token column to sets (migration 054)`

### Task 2: Share + duplicate service (`share_service.py`) with API-boundary TDD

**Files:**
- Create: `server/app/services/setbuilder/share_service.py`
- Create: `server/app/schemas/` additions + `server/app/api/setbuilder_share.py` (Task 3 wires routes; service first with unit-ish tests via db fixture)
- Test: `server/tests/test_setbuilder_share.py`

- [ ] **Step 1: Write failing service tests** (db fixture; seed a Set with slots + curve points directly)

Tests: `test_duplicate_copies_children_and_resets_state`, `test_duplicate_truncates_long_name`, `test_regenerate_changes_token`, `test_revoke_nulls_token`, `test_get_by_token_rejects_bad_format`.

- [ ] **Step 2: Run, verify FAIL** — `cd server && .venv/bin/pytest tests/test_setbuilder_share.py -v` → import error.

- [ ] **Step 3: Implement service**

```python
"""Share-token + duplicate logic for WrzDJSet sets (issue #398)."""

import re
import secrets

from sqlalchemy.orm import Session

from app.models.set import Set, SetCurvePoint, SetSlot

_MAX_NAME = 120
_COPY_SUFFIX = " (copy)"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def regenerate_share_token(db: Session, set_obj: Set) -> Set:
    """Create or rotate the read-only share token (CSPRNG)."""
    set_obj.share_token = secrets.token_urlsafe(32)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def revoke_share_token(db: Session, set_obj: Set) -> Set:
    """Revoke sharing: NULL the token so old links 404."""
    set_obj.share_token = None
    db.commit()
    db.refresh(set_obj)
    return set_obj


def get_set_by_share_token(db: Session, token: str) -> Set | None:
    """Indexed lookup; malformed tokens short-circuit to None (no oracle)."""
    if not _TOKEN_RE.fullmatch(token):
        return None
    return db.query(Set).filter(Set.share_token == token).one_or_none()


def duplicate_set(db: Session, src: Set) -> Set:
    """Copy a set (slots, curve, targets, vibe windows); reset lifecycle state."""
    name = src.name + _COPY_SUFFIX
    if len(name) > _MAX_NAME:
        name = src.name[: _MAX_NAME - len(_COPY_SUFFIX)] + _COPY_SUFFIX
    dup = Set(
        owner_id=src.owner_id,
        event_id=src.event_id,
        name=name,
        vibe_theme=src.vibe_theme,
        target_duration_sec=src.target_duration_sec,
        bpm_floor=src.bpm_floor,
        bpm_ceiling=src.bpm_ceiling,
        key_strictness=src.key_strictness,
        status="draft",
        sharing_mode="private",
    )
    db.add(dup)
    db.flush()
    for slot in sorted(src.slots, key=lambda s: s.position):
        db.add(
            SetSlot(
                set_id=dup.id,
                position=slot.position,
                track_id=slot.track_id,
                locked=slot.locked,
                notes=slot.notes,
                transition_score=slot.transition_score,
                transition_warnings=slot.transition_warnings,
            )
        )
    for cp in src.curve_points:
        db.add(
            SetCurvePoint(
                set_id=dup.id,
                position_sec=cp.position_sec,
                energy=cp.energy,
                label=cp.label,
                is_slow_window_start=cp.is_slow_window_start,
                is_slow_window_end=cp.is_slow_window_end,
            )
        )
    db.commit()
    db.refresh(dup)
    return dup
```

- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `feat(setbuilder): share-token + duplicate service`

### Task 3: Schemas (additive) + owner routes + public route

**Files:**
- Modify (ADDITIVE): `server/app/schemas/setbuilder.py` — add `share_token: str | None = None` to `SetSummary`; append `SharedSlotView`, `SharedCurvePointView`, `SharedSetView`
- Create: `server/app/api/setbuilder_share.py` (router + public_router)
- Modify (ADDITIVE): `server/app/api/__init__.py` — register both routers
- Test: extend `server/tests/test_setbuilder_share.py`

- [ ] **Step 1: Failing API tests**

Owner routes: POST `/api/setbuilder/sets/{id}/share` 200 returns token; POST again rotates (old token then 404 publicly); DELETE `/api/setbuilder/sets/{id}/share` 204 then public 404; POST `/api/setbuilder/sets/{id}/duplicate` 201 returns new SetDetail with `" (copy)"` name + draft status; all four 401 unauth, 403 pending, 404 on another DJ's set.
Public route: GET `/api/public/setbuilder/shared/{token}` 200 with projection; assert response contains NO `owner_id`/`id`/`event_id`/`tidal_playlist_id`/`share_token` keys; 404 unknown token; 404 malformed token; works with NO auth header.
List surfacing: GET `/api/setbuilder/sets` items include `share_token`.

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Schemas (append to `schemas/setbuilder.py`; plus one field on SetSummary)**

```python
class SharedSlotView(BaseModel):
    """View-only slot projection for public share links (no DB ids)."""

    model_config = ConfigDict(from_attributes=True)

    position: int
    track_id: str | None
    locked: bool
    notes: str | None
    transition_score: float | None


class SharedCurvePointView(BaseModel):
    """View-only curve-point projection for public share links."""

    model_config = ConfigDict(from_attributes=True)

    position_sec: int
    energy: int
    label: str | None
    is_slow_window_start: bool
    is_slow_window_end: bool


class SharedSetView(BaseModel):
    """Public read-only projection of a shared set.

    Never include owner identity, internal ids, event linkage, collaborator
    info, or the token itself (issue #398 security requirements).
    """

    name: str
    status: Literal["draft", "locked", "exported"]
    vibe_theme: str | None
    target_duration_sec: int | None
    bpm_floor: int | None
    bpm_ceiling: int | None
    key_strictness: float
    slots: list[SharedSlotView]
    curve_points: list[SharedCurvePointView]


class ShareTokenOut(BaseModel):
    """Owner response after creating/rotating a share token."""

    share_token: str
```

- [ ] **Step 4: Router file `server/app/api/setbuilder_share.py`**

```python
"""Share-link + duplicate routes for WrzDJSet (issue #398).

`router` mounts under /api/setbuilder (owner-scoped, active DJ only).
`public_router` mounts under /api/public/setbuilder (no auth; read-only
projection; token is the sole capability — mutations all live on the
authenticated router, so a leaked link can never modify anything).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.set import Set
from app.models.user import User
from app.schemas.setbuilder import SetDetail, SharedCurvePointView, SharedSetView, SharedSlotView, ShareTokenOut
from app.services.setbuilder import set_service, share_service

router = APIRouter()
public_router = APIRouter()


def _get_owned_or_404(db: Session, set_id: int, user: User) -> Set:
    set_obj = set_service.get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


@router.post("/sets/{set_id}/share", response_model=ShareTokenOut)
@limiter.limit("10/minute")
def create_or_rotate_share_token(...): ...


@router.delete("/sets/{set_id}/share", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def revoke_share_token(...): ...


@router.post("/sets/{set_id}/duplicate", response_model=SetDetail, status_code=201)
@limiter.limit("10/minute")
def duplicate_set(...): ...


@public_router.get("/shared/{token}", response_model=SharedSetView)
@limiter.limit("30/minute")
def view_shared_set(token: str, request: Request, db: Session = Depends(get_db)) -> SharedSetView:
    set_obj = share_service.get_set_by_share_token(db, token)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Not found")
    return SharedSetView(
        name=set_obj.name,
        status=set_obj.status,
        vibe_theme=set_obj.vibe_theme,
        target_duration_sec=set_obj.target_duration_sec,
        bpm_floor=set_obj.bpm_floor,
        bpm_ceiling=set_obj.bpm_ceiling,
        key_strictness=set_obj.key_strictness,
        slots=[SharedSlotView.model_validate(s) for s in sorted(set_obj.slots, key=lambda s: s.position)],
        curve_points=[
            SharedCurvePointView.model_validate(c)
            for c in sorted(set_obj.curve_points, key=lambda c: c.position_sec)
        ],
    )
```

Registration in `api/__init__.py` (additive, after existing setbuilder line):

```python
api_router.include_router(setbuilder_share.router, prefix="/setbuilder", tags=["setbuilder"])
api_router.include_router(
    setbuilder_share.public_router, prefix="/public/setbuilder", tags=["setbuilder-public"]
)
```

- [ ] **Step 5: Run tests, verify PASS; run full backend CI** (ruff check, ruff format --check, bandit, pytest).
- [ ] **Step 6: Commit** — `feat(setbuilder): share/revoke/duplicate routes + public view-only endpoint`

### Task 4: Frontend API client + types (+ fixture updates)

**Files:**
- Modify (ADDITIVE): `dashboard/lib/api-types.ts` — add `share_token: string | null` to `SetSummary`; add `SharedSlotView`, `SharedCurvePointView`, `SharedSetView`, `ShareTokenOut` interfaces
- Modify (ADDITIVE): `dashboard/lib/api.ts` — `duplicateSet`, `shareSet`, `revokeSetShare`, `getSharedSet` (publicFetch)
- Modify: `dashboard/app/(dj)/setbuilder/__tests__/page.test.tsx` fixtures gain `share_token: null`

- [ ] Steps: add types → add methods → `npx tsc --noEmit` + `npm test -- --run` → commit `feat(setbuilder): frontend api client for share + duplicate`.

```typescript
  async duplicateSet(setId: number): Promise<SetDetail> {
    return this.fetch(`/api/setbuilder/sets/${setId}/duplicate`, { method: 'POST' });
  }
  async shareSet(setId: number): Promise<ShareTokenOut> {
    return this.fetch(`/api/setbuilder/sets/${setId}/share`, { method: 'POST' });
  }
  async revokeSetShare(setId: number): Promise<void> {
    await this.rawFetch(`/api/setbuilder/sets/${setId}/share`, { method: 'DELETE' });
  }
  async getSharedSet(token: string): Promise<SharedSetView> {
    return this.publicFetch(`${getApiUrl()}/api/public/setbuilder/shared/${encodeURIComponent(token)}`);
  }
```

### Task 5: ShareDialog component + set-list integration

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/ShareDialog.tsx`
- Create: `dashboard/app/(dj)/setbuilder/__tests__/ShareDialog.test.tsx`
- Modify (ADDITIVE): `dashboard/app/(dj)/setbuilder/page.tsx` — "Shared" badge when `share_token` set; row buttons "Duplicate" and "Share"; mount `<ShareDialog>`

ShareDialog: props `{ set: SetSummary; onClose; onChanged(token: string | null) }`. Shows share URL (`${window.location.origin}/shared/${token}`) with Copy button when shared; buttons Create link / Regenerate / Revoke calling api. Tests: renders create state, calls shareSet and surfaces URL, revoke calls revokeSetShare.

Page integration (additive): `const [shareTarget, setShareTarget] = useState<SetSummary | null>(null);` + Duplicate handler `const dup = await api.duplicateSet(id); setSets(prev => [dup, ...prev]);` + badge `{s.share_token && <span className="badge">Shared</span>}`.

- [ ] TDD steps + run vitest + commit `feat(setbuilder): share dialog + duplicate/share actions on set list`.

### Task 6: Builder topbar actions (brand-menu equivalent)

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/SetActionsMenu.tsx` (Duplicate → router.push to new set; Share → opens ShareDialog)
- Modify (ADDITIVE): `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` — replace spacer `<span style={{ width: 60 }} />` with `<SetActionsMenu set={set} onShareChanged={...} />`

- [ ] Implement + tsc + commit `feat(setbuilder): duplicate/share actions in builder topbar`.

### Task 7: Public view-only page `/shared/[token]`

**Files:**
- Create: `dashboard/app/shared/[token]/page.tsx` (+ colocated `shared.module.css` if needed)
- Create: `dashboard/app/shared/[token]/__tests__/page.test.tsx`

Client page: `use(params)` for token, fetch `api.getSharedSet(token)`, render "View only" badge, set name, meta chips (target duration, BPM range, key strictness, vibe), ordered slot list, curve point list. Error state: "This link is invalid or has been revoked." No auth hooks, no mutation calls, no agent/export UI.

- [ ] TDD steps (loading, success render, 404 error message) + commit `feat(setbuilder): public read-only shared set page`.

### Task 8: Full CI + finish

- [ ] Backend: `cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/pytest --tb=short -q`
- [ ] Migration: `.venv/bin/alembic upgrade head && .venv/bin/alembic check`
- [ ] Frontend: `cd dashboard && npm run lint && npx tsc --noEmit && npm test -- --run`
- [ ] `git checkout next-env.d.ts` if dirty; push branch; open PR (Closes #398, Design decisions section, migration-slot note).

## Self-review notes
- Spec coverage: duplicate (Task 2/3/5/6), tokenized read-only link (1/2/3/7), revoke/regenerate (2/3/5), share state on list (3/4/5). ✓
- Server-side view-only enforcement: public router has exactly one GET; token grants nothing else. ✓
- Security: CSPRNG token, indexed unique column, format pre-validation, rate limits, sanitized projection. ✓

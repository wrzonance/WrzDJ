# Frictionless Join Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a DJ mark an event "frictionless join" so live-event guests land straight on song search with an auto-generated username — no nickname/email step — while `/collect` stays fully hardened.

**Architecture:** A per-event boolean `Event.frictionless_join` (snapshot-seeded at creation from the DJ's `User.frictionless_join_default`) is read by the `/join` page. When true, the page skips `NicknameGate` and calls a new server endpoint that auto-generates a unique nickname (via `coolname`) on the existing per-event `GuestProfile`. The auto-name + optional rename path is gated by the soft human-cookie check **and** by `event.frictionless_join` (so it can never bypass email verification on non-frictionless events). `/collect` endpoints and their `require_email_verified` gates are untouched.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic (backend), Next.js 16 / React 19 + vanilla CSS (frontend), pytest + vitest, `coolname` (BSD-2-Clause, zero-dep name generator), OpenAPI-generated TS types.

**Spec:** `docs/superpowers/specs/2026-05-29-frictionless-join-design.md`

## Test execution note (read before running any pytest)

`server/pyproject.toml` sets `addopts = "... --cov-fail-under=85"`, so **every** pytest invocation computes coverage over all of `app` and a single-file run will FAIL the 85% gate even when its tests pass. Therefore **all single-file/targeted pytest commands in this plan append `--no-cov`** (tests still run; coverage gating is skipped). The **full-suite** runs in Task 6 Step 7 and Task 13 keep coverage on — those are the real gate. The backend DB for this worktree is the isolated `wrzdj_fric` database (configured in the worktree `.env`); `alembic` commands target it.

## Routing resolution note (read before coding)

The `/join/[code]` page currently calls **both** `/api/events/{code}/*` (collection-code lookup) and `/api/public/collect/{code}/*` (collection-code lookup via `NicknameGate`) successfully with one `code` param. This plan therefore anchors all new guest endpoints to the **collect router** (`/api/public/collect`, resolved via `collect.py:_get_event_or_404` → `Event.code == code`), the identical resolution path `NicknameGate` already uses. This guarantees the new endpoints resolve the same event row the existing gate does, independent of the latent collection-vs-join code routing quirk (pre-existing, out of scope for #369).

## File structure

**Backend (create):**
- `server/app/services/guest_names.py` — auto-name generator (one responsibility)

**Backend (modify):**
- `server/app/models/user.py` — add `frictionless_join_default`
- `server/app/models/event.py` — add `frictionless_join`
- `server/alembic/versions/<new>_add_frictionless_join.py` — migration
- `server/pyproject.toml` — add `coolname` dependency
- `server/app/schemas/event.py` — `EventOut` + `EventUpdate`
- `server/app/schemas/user.py` — `UserOut`
- `server/app/schemas/collect.py` — `EnsureNameRequest` / `EnsureNameResponse` / `JoinConfigResponse`
- `server/app/services/event.py` — `create_event` seed + `update_event` apply
- `server/app/services/account.py` — `update_preferences`
- `server/app/api/collect.py` — `ensure_name` + `join_config` endpoints
- `server/app/api/auth.py` — `PATCH /me/preferences`

**Frontend (modify):**
- `dashboard/lib/api-types.generated.ts` — regenerated (do not hand-edit)
- `dashboard/lib/api.ts` — `getJoinConfig`, `ensureGuestName`, `updateMyPreferences`, `getMe` field
- `dashboard/app/join/[code]/page.tsx` — gate-mode decision + auto-name
- `dashboard/components/IdentityBar.tsx` — "Add a name" rename affordance
- `dashboard/app/(dj)/events/[code]/page.tsx` — frictionless toggle state + handler
- `dashboard/app/(dj)/events/[code]/components/EventManagementTab.tsx` — pass-through props
- `dashboard/app/(dj)/events/[code]/components/KioskControlsCard.tsx` — render toggle
- `dashboard/app/(dj)/account/page.tsx` — "Guest Experience" card

---

## Task 1: Data model columns + migration

**Files:**
- Modify: `server/app/models/user.py` (after `help_pages_seen`, ~line 52)
- Modify: `server/app/models/event.py` (after `kiosk_display_only`, ~line 61)
- Create: `server/alembic/versions/<generated>_add_frictionless_join.py`
- Test: `server/tests/test_frictionless_model.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_frictionless_model.py
from app.models.event import Event
from app.models.user import User


def test_user_frictionless_default_defaults_false(db):
    user = User(username="dj_fric", password_hash="x", role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.frictionless_join_default is False


def test_event_frictionless_join_defaults_false(db, test_user: User):
    from app.services.event import create_event

    event = create_event(db, "Frictionless Test", test_user)
    assert event.frictionless_join is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_model.py -q --no-cov`
Expected: FAIL — `AttributeError: 'User' object has no attribute 'frictionless_join_default'`

- [ ] **Step 3: Add the model columns**

In `server/app/models/user.py`, after the `help_pages_seen` column:

```python
    # Frictionless join: DJ default applied to new events (snapshot at creation).
    frictionless_join_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
```

In `server/app/models/event.py`, after the `kiosk_display_only` column block:

```python
    # Frictionless join: guests skip nickname/email and get an auto-generated name.
    # Seeded from the creator's frictionless_join_default at event creation.
    frictionless_join: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
```

(`Boolean` is already imported in both files.)

- [ ] **Step 4: Generate the migration skeleton**

Run: `cd server && .venv/bin/alembic revision -m "add frictionless join flags"`
This creates a new file under `server/alembic/versions/` with `revision`/`down_revision` already linked to the current head. Open it and replace the `upgrade`/`downgrade` bodies:

```python
def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("frictionless_join_default", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "events",
        sa.Column("frictionless_join", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("events", "frictionless_join")
    op.drop_column("users", "frictionless_join_default")
```

- [ ] **Step 5: Apply migration and check for drift**

Run: `cd server && .venv/bin/alembic upgrade head && .venv/bin/alembic check`
Expected: upgrade succeeds; `alembic check` prints "No new upgrade operations detected."

- [ ] **Step 6: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_model.py -q --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add server/app/models/user.py server/app/models/event.py server/alembic/versions/ server/tests/test_frictionless_model.py
git commit -m "feat(join): add frictionless_join model columns + migration (#369)"
```

---

## Task 2: Auto-name generator service

**Files:**
- Modify: `server/pyproject.toml` (dependencies array)
- Create: `server/app/services/guest_names.py`
- Test: `server/tests/test_guest_names.py`

- [ ] **Step 1: Add the dependency**

In `server/pyproject.toml`, add to the `dependencies` list:

```toml
    "coolname==5.0.0",
```

Run: `cd server && .venv/bin/pip install coolname==5.0.0`

- [ ] **Step 2: Write the failing test**

```python
# server/tests/test_guest_names.py
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.services.guest_names import generate_unique_nickname


def test_generates_titlecased_no_hyphen(db, test_event: Event):
    nick = generate_unique_nickname(db, event_id=test_event.id)
    assert nick
    assert "-" not in nick
    assert nick[0].isupper()
    assert len(nick) <= 30


def test_avoids_existing_nickname_in_event(db, test_event: Event, monkeypatch):
    # Force the 2-word generator to always collide, proving the suffix/retry path.
    import app.services.guest_names as gn

    guest = Guest(token="g" * 64, fingerprint_hash="fp_x")
    db.add(guest)
    db.commit()
    db.add(GuestProfile(event_id=test_event.id, guest_id=guest.id, nickname="Taken"))
    db.commit()

    calls = {"n": 0}

    def fake_slug(n):
        if n == 2:
            calls["n"] += 1
            return "taken"  # always collides at 2 words
        return "unique-three-words"  # 3-word fallback

    monkeypatch.setattr(gn, "generate_slug", fake_slug)
    nick = generate_unique_nickname(db, event_id=test_event.id, max_attempts=3)
    # Either a digit-suffixed "Taken##" or the 3-word fallback; never bare "Taken".
    assert nick.lower() != "taken"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_guest_names.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.guest_names'`

- [ ] **Step 4: Write the implementation**

```python
# server/app/services/guest_names.py
"""Auto-generated guest nicknames for frictionless-join events.

Server-side so it shares the per-event nickname uniqueness check and never
ships a wordlist to the client. Vocabulary comes from `coolname` (BSD-2-Clause,
zero deps).
"""

import secrets

from coolname import generate_slug
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.guest_profile import GuestProfile


def _slug_to_name(slug: str) -> str:
    """'dancing-panda' -> 'DancingPanda', clamped to the 30-char nickname limit."""
    name = "".join(part.capitalize() for part in slug.split("-"))
    return name[:30]


def _is_taken(db: Session, *, event_id: int, candidate: str) -> bool:
    return (
        db.query(GuestProfile.id)
        .filter(
            GuestProfile.event_id == event_id,
            func.lower(GuestProfile.nickname) == candidate.lower(),
        )
        .first()
        is not None
    )


def generate_unique_nickname(db: Session, *, event_id: int, max_attempts: int = 5) -> str:
    """Return a nickname unique (case-insensitive) within the event.

    Tries `max_attempts` two-word names, suffixing a 2-digit number after the
    first collision. Falls back to a collision-proof three-word name if all
    attempts collide.
    """
    for attempt in range(max_attempts):
        base = _slug_to_name(generate_slug(2))
        candidate = base if attempt == 0 else f"{base}{secrets.randbelow(90) + 10}"
        candidate = candidate[:30]
        if not _is_taken(db, event_id=event_id, candidate=candidate):
            return candidate
    return _slug_to_name(generate_slug(3))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_guest_names.py -q --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add server/pyproject.toml server/app/services/guest_names.py server/tests/test_guest_names.py
git commit -m "feat(join): add coolname-based guest nickname generator (#369)"
```

---

## Task 3: EventOut field + EventUpdate + update_event apply

**Files:**
- Modify: `server/app/schemas/event.py` (`EventOut` ~line 79, `EventUpdate` ~line 31)
- Modify: `server/app/services/event.py` (`update_event` ~line 151)
- Modify: `server/app/api/events.py` (`update_event_endpoint` ~line 451 — pass new field)
- Test: `server/tests/test_frictionless_event_api.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_frictionless_event_api.py
from app.models.user import User


def test_event_out_exposes_frictionless_join(client, db, test_user: User, auth_headers):
    r = client.post("/api/events", json={"name": "E1", "expires_hours": 6}, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["frictionless_join"] is False


def test_patch_event_sets_frictionless_join(client, db, test_user: User, auth_headers):
    code = client.post(
        "/api/events", json={"name": "E2", "expires_hours": 6}, headers=auth_headers
    ).json()["code"]
    r = client.patch(f"/api/events/{code}", json={"frictionless_join": True}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["frictionless_join"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_event_api.py -q --no-cov`
Expected: FAIL — response JSON has no `frictionless_join` key (KeyError on assert).

- [ ] **Step 3: Add the schema fields**

In `server/app/schemas/event.py`, add to `EventOut` (after `requests_open`):

```python
    # Frictionless join (guests skip nickname/email)
    frictionless_join: bool = False
```

Add to `EventUpdate`:

```python
    frictionless_join: bool | None = None
```

- [ ] **Step 4: Apply it in the service + endpoint**

In `server/app/services/event.py`, change `update_event` signature and body:

```python
def update_event(
    db: Session,
    event: Event,
    name: str | None = None,
    expires_at: datetime | None = None,
    frictionless_join: bool | None = None,
) -> Event:
    """Update an event's properties."""
    if name is not None:
        event.name = name
    if expires_at is not None:
        event.expires_at = expires_at
    if frictionless_join is not None:
        event.frictionless_join = frictionless_join
    db.commit()
    db.refresh(event)
    return event
```

In `server/app/api/events.py`, in `update_event_endpoint`, pass the field:

```python
    updated = update_event(
        db,
        event,
        name=event_data.name,
        expires_at=event_data.expires_at,
        frictionless_join=event_data.frictionless_join,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_event_api.py -q --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add server/app/schemas/event.py server/app/services/event.py server/app/api/events.py server/tests/test_frictionless_event_api.py
git commit -m "feat(join): expose + edit event.frictionless_join via EventOut/PATCH (#369)"
```

---

## Task 4: Event creation seeds from DJ default

**Files:**
- Modify: `server/app/services/event.py` (`create_event` ~line 90)
- Test: `server/tests/test_frictionless_seed.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_frictionless_seed.py
from app.models.user import User
from app.services.event import create_event


def test_create_event_seeds_from_dj_default(db, test_user: User):
    test_user.frictionless_join_default = True
    db.commit()
    event = create_event(db, "Seeded", test_user)
    assert event.frictionless_join is True


def test_create_event_default_off_when_dj_default_off(db, test_user: User):
    event = create_event(db, "NotSeeded", test_user)
    assert event.frictionless_join is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_seed.py -q --no-cov`
Expected: FAIL — `test_create_event_seeds_from_dj_default` asserts True but gets False.

- [ ] **Step 3: Seed the field in create_event**

In `server/app/services/event.py`, in `create_event`, add `frictionless_join` to the `Event(...)` constructor:

```python
        event = Event(
            code=code,
            join_code=join_code,
            name=name,
            created_by_user_id=user.id,
            expires_at=expires_at,
            frictionless_join=user.frictionless_join_default,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_seed.py -q --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/event.py server/tests/test_frictionless_seed.py
git commit -m "feat(join): seed event.frictionless_join from DJ default at creation (#369)"
```

---

## Task 5: ensure-name + join-config endpoints

**Files:**
- Modify: `server/app/schemas/collect.py` (add request/response models)
- Modify: `server/app/api/collect.py` (add two endpoints near `set_profile`)
- Test: `server/tests/test_frictionless_ensure_name.py`

- [ ] **Step 1: Write the failing test**

Mirror the `_default_guest_cookie` helper from `tests/test_collect_public.py` (mints `wrzdj_guest` + `wrzdj_human` cookies).

```python
# server/tests/test_frictionless_ensure_name.py
from app.models.event import Event
from app.models.guest import Guest
from app.services.human_verification import HUMAN_COOKIE_NAME, issue_human_cookie


def _verified_guest_cookie(client, db):
    from fastapi import Response

    guest = Guest(token="frictionguest" + "0" * 51, fingerprint_hash="fp_fric")
    db.add(guest)
    db.commit()
    db.refresh(guest)
    helper = Response()
    issue_human_cookie(helper, guest.id)
    human_value = helper.headers.get("set-cookie", "").split("=", 1)[1].split(";", 1)[0]
    client.cookies.clear()
    client.cookies.set("wrzdj_guest", guest.token)
    client.cookies.set(HUMAN_COOKIE_NAME, human_value)
    return guest


def test_join_config_reports_flag(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    r = client.get(f"/api/public/collect/{test_event.code}/join-config")
    assert r.status_code == 200
    assert r.json()["frictionless_join"] is True


def test_ensure_name_autogenerates_when_frictionless(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    _verified_guest_cookie(client, db)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["auto_generated"] is True
    assert body["nickname"]


def test_ensure_name_idempotent(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    _verified_guest_cookie(client, db)
    first = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={}).json()
    second = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={}).json()
    assert first["nickname"] == second["nickname"]


def test_ensure_name_manual_rename(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    _verified_guest_cookie(client, db)
    client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    r = client.post(
        f"/api/public/collect/{test_event.code}/guest/ensure-name",
        json={"nickname": "MyChosenName"},
    )
    assert r.status_code == 200
    assert r.json()["nickname"] == "MyChosenName"
    assert r.json()["auto_generated"] is False


def test_ensure_name_403_when_not_frictionless(client, db, test_event: Event):
    # test_event.frictionless_join defaults False
    _verified_guest_cookie(client, db)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "frictionless_disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_ensure_name.py -q --no-cov`
Expected: FAIL — 404 (endpoints don't exist yet).

- [ ] **Step 3: Add the schemas**

In `server/app/schemas/collect.py`, after `CollectProfileResponse`:

```python
class JoinConfigResponse(BaseModel):
    frictionless_join: bool


class EnsureNameRequest(BaseModel):
    nickname: Nickname | None = None


class EnsureNameResponse(BaseModel):
    nickname: str
    auto_generated: bool
```

(`Nickname` is the validated, profanity-checked type already defined at the top of this file.)

- [ ] **Step 4: Add the endpoints**

In `server/app/api/collect.py`, import the new pieces near the top:

```python
from app.schemas.collect import EnsureNameRequest, EnsureNameResponse, JoinConfigResponse
from app.services.guest_names import generate_unique_nickname
from app.api.deps import require_verified_human_soft
```

Then add, just after the `set_profile` endpoint:

```python
@router.get("/{code}/join-config", response_model=JoinConfigResponse)
@limiter.limit("60/minute")
def join_config(code: str, request: Request, db: Session = Depends(get_db)):
    """Public, unauthenticated: lets the join page decide its gate mode on load."""
    event = _get_event_or_404(db, code)
    return JoinConfigResponse(frictionless_join=event.frictionless_join)


@router.post("/{code}/guest/ensure-name", response_model=EnsureNameResponse)
@limiter.limit("10/minute")
def ensure_name(
    code: str,
    payload: EnsureNameRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    guest_id: int | None = Depends(require_verified_human_soft),
):
    """Frictionless-join name management. Auto-generates a nickname when none is
    set, or applies a manual rename. Gated on event.frictionless_join so it can
    never bypass email verification on a hardened (non-frictionless) event.
    """
    event = _get_event_or_404(db, code)
    if not event.frictionless_join:
        raise HTTPException(status_code=403, detail={"code": "frictionless_disabled"})
    if guest_id is None:
        raise HTTPException(status_code=403, detail={"code": "human_verification_required"})

    existing = collect_service.get_profile(db, event_id=event.id, guest_id=guest_id)
    if payload.nickname is not None:
        chosen, auto = payload.nickname, False
    elif existing is not None and existing.nickname:
        return EnsureNameResponse(nickname=existing.nickname, auto_generated=False)
    else:
        chosen, auto = generate_unique_nickname(db, event_id=event.id), True

    try:
        profile = upsert_profile(db, event_id=event.id, guest_id=guest_id, nickname=chosen)
    except NicknameConflictError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "nickname_taken", "claimed": exc.claimed}
        )
    return EnsureNameResponse(nickname=profile.nickname, auto_generated=auto)
```

(`Response` is already imported from fastapi in this file; if not, add it to the existing fastapi import. `collect_service`, `upsert_profile`, `NicknameConflictError`, `_get_event_or_404`, `limiter` are already imported/defined in collect.py.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_ensure_name.py -q --no-cov`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add server/app/schemas/collect.py server/app/api/collect.py server/tests/test_frictionless_ensure_name.py
git commit -m "feat(join): ensure-name + join-config endpoints for frictionless mode (#369)"
```

---

## Task 6: DJ default — UserOut field + PATCH /me/preferences

**Files:**
- Modify: `server/app/schemas/user.py` (`UserOut`)
- Modify: `server/app/services/account.py` (add `update_preferences`)
- Modify: `server/app/api/auth.py` (add `PATCH /me/preferences`)
- Test: `server/tests/test_frictionless_preferences.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_frictionless_preferences.py
def test_me_exposes_frictionless_default(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["frictionless_join_default"] is False


def test_patch_preferences_updates_default(client, auth_headers):
    r = client.patch(
        "/api/auth/me/preferences",
        json={"frictionless_join_default": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["frictionless_join_default"] is True
    # persisted
    assert client.get("/api/auth/me", headers=auth_headers).json()["frictionless_join_default"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_preferences.py -q --no-cov`
Expected: FAIL — `/me` response has no `frictionless_join_default`.

- [ ] **Step 3: Add the UserOut field**

In `server/app/schemas/user.py`, add to `UserOut`:

```python
    frictionless_join_default: bool = False
```

- [ ] **Step 4: Add the service function**

In `server/app/services/account.py`:

```python
def update_preferences(db: Session, user: User, *, frictionless_join_default: bool) -> User:
    """Update self-service DJ preferences."""
    user.frictionless_join_default = frictionless_join_default
    db.commit()
    db.refresh(user)
    return user
```

(Ensure `User` and `Session` are imported in that module — they are used by existing functions.)

- [ ] **Step 5: Add the endpoint + request schema**

In `server/app/api/auth.py`, add a request model near the other auth schemas (or inline in `app/schemas/user.py` and import). Inline at top of `auth.py` imports if a local model is simplest:

```python
from pydantic import BaseModel


class MePreferencesUpdate(BaseModel):
    frictionless_join_default: bool
```

Then the endpoint (place after `change_password`):

```python
@router.patch("/me/preferences", response_model=UserOut)
@limiter.limit("20/minute")
def update_me_preferences(
    body: MePreferencesUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    updated = account_service.update_preferences(
        db, current_user, frictionless_join_default=body.frictionless_join_default
    )
    return UserOut.model_validate(updated)
```

(`UserOut`, `account_service`, `get_current_active_user`, `limiter`, `Request` are already imported in auth.py. If `limiter` is not used elsewhere in auth.py, drop the decorator — check existing endpoints; `change_password` shows the established decorator pattern to mirror.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_frictionless_preferences.py -q --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 7: Run the full backend suite + lint**

Run: `cd server && .venv/bin/ruff check . && .venv/bin/ruff format . && .venv/bin/pytest --tb=short -q`
Expected: lint clean; all tests pass; coverage ≥ threshold.

- [ ] **Step 8: Commit**

```bash
git add server/app/schemas/user.py server/app/services/account.py server/app/api/auth.py server/tests/test_frictionless_preferences.py
git commit -m "feat(join): per-DJ frictionless_join_default via PATCH /me/preferences (#369)"
```

---

## Task 7: Regenerate OpenAPI types

**Files:**
- Modify: `server/openapi.json` (generated)
- Modify: `dashboard/lib/api-types.generated.ts` (generated)

- [ ] **Step 1: Regenerate**

Run:
```bash
cd dashboard && npm run types:export && npm run types:generate
```

- [ ] **Step 2: Verify the new fields landed**

Run: `cd dashboard && grep -n "frictionless_join" lib/api-types.generated.ts`
Expected: matches for `frictionless_join` (EventOut), `frictionless_join_default` (UserOut), and the `EnsureNameResponse`/`JoinConfigResponse` schemas.

- [ ] **Step 3: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors (the `Event` type alias now carries `frictionless_join`).

- [ ] **Step 4: Commit**

```bash
git add server/openapi.json dashboard/lib/api-types.generated.ts
git commit -m "chore(types): regenerate OpenAPI types for frictionless join (#369)"
```

---

## Task 8: API client methods

**Files:**
- Modify: `dashboard/lib/api.ts` (`getMe` ~line 401; new methods near `getCollectProfile` ~line 1222)
- Test: `dashboard/lib/__tests__/api.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// add to dashboard/lib/__tests__/api.test.ts
describe('frictionless join api', () => {
  it('getJoinConfig hits the public collect endpoint', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ frictionless_join: true }), { status: 200 })
    );
    const res = await apiClient.getJoinConfig('CODE01');
    expect(res.frictionless_join).toBe(true);
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining('/api/public/collect/CODE01/join-config'),
      expect.anything()
    );
    spy.mockRestore();
  });

  it('ensureGuestName posts to the ensure-name endpoint', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ nickname: 'DancingPanda', auto_generated: true }), { status: 200 })
    );
    const res = await apiClient.ensureGuestName('CODE01');
    expect(res.nickname).toBe('DancingPanda');
    spy.mockRestore();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run api.test`
Expected: FAIL — `apiClient.getJoinConfig is not a function`.

- [ ] **Step 3: Add the methods**

In `dashboard/lib/api.ts`, add `frictionless_join_default: boolean;` to the inline return type of `getMe()`.

Add near `getCollectProfile` (use the generated schema types where available):

```typescript
  async getJoinConfig(code: string): Promise<{ frictionless_join: boolean }> {
    return this.publicFetch(`${getApiUrl()}/api/public/collect/${code}/join-config`);
  }

  async ensureGuestName(
    code: string,
    reverify?: () => Promise<void>,
    nickname?: string,
  ): Promise<{ nickname: string; auto_generated: boolean }> {
    const doFetch = () =>
      fetch(`${getApiUrl()}/api/public/collect/${code}/guest/ensure-name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(nickname ? { nickname } : {}),
      });
    return withHumanRetry(doFetch, reverify);
  }

  async updateMyPreferences(prefs: { frictionless_join_default: boolean }): Promise<void> {
    await this.fetch('/api/auth/me/preferences', {
      method: 'PATCH',
      body: JSON.stringify(prefs),
    });
  }
```

(`withHumanRetry`, `publicFetch`, `getApiUrl` already exist in this file. `withHumanRetry` parses the JSON body and re-bootstraps on a 403 `human_verification_required`, matching `submitRequest`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run api.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/lib/__tests__/api.test.ts
git commit -m "feat(join): api client getJoinConfig/ensureGuestName/updateMyPreferences (#369)"
```

---

## Task 9: Join page — gate-mode decision + auto-name

**Files:**
- Modify: `dashboard/app/join/[code]/page.tsx` (state ~line 90-123; mount effect; `IdentityBar` usages)
- Test: `dashboard/app/join/[code]/__tests__/page.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// add to dashboard/app/join/[code]/__tests__/page.test.tsx
it('skips NicknameGate and auto-names when frictionless_join is on', async () => {
  mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
  mockApi.ensureGuestName.mockResolvedValue({ nickname: 'DancingPanda', auto_generated: true });
  mockApi.getEvent.mockResolvedValue({
    id: 1, code: 'TEST01', join_code: 'TEST01', name: 'Party', requests_open: true,
    frictionless_join: true,
  } as never);
  mockApi.checkHasRequested.mockResolvedValue({ has_requested: false } as never);
  render(<JoinPage />);
  // No "What's your nickname?" gate; the auto-name shows in the identity bar.
  await waitFor(() => expect(screen.getByText(/DancingPanda/)).toBeInTheDocument());
  expect(screen.queryByText(/What's your nickname/i)).not.toBeInTheDocument();
});
```

Add `getJoinConfig: vi.fn()` and `ensureGuestName: vi.fn()` to the `mockApi` object at the top of the test file, and (in tests that don't set it) default `getJoinConfig` to resolve `{ frictionless_join: false }` in `beforeEach` so existing gate tests still render `NicknameGate`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run join`
Expected: FAIL — gate still renders / `getJoinConfig` undefined.

- [ ] **Step 3: Implement the gate-mode decision**

In `dashboard/app/join/[code]/page.tsx`, add state near the other gate state (after line 111):

```typescript
  const [autoNamed, setAutoNamed] = useState(false);
  const { isLoading: identityLoading } = useGuestIdentity();
```

(Import `useGuestIdentity` from `'@/lib/use-guest-identity'` if not already imported.)

Add a mount effect that decides the gate mode (place before the existing `loadEvent` effect):

```typescript
  // Decide gate mode on load. Frictionless events skip NicknameGate entirely:
  // the guest gets an auto-generated name and lands straight on search.
  useEffect(() => {
    if (gateComplete || identityLoading) return;
    let active = true;
    (async () => {
      try {
        const cfg = await api.getJoinConfig(code);
        if (!active || !cfg.frictionless_join) return; // not frictionless -> NicknameGate renders
        const res = await api.ensureGuestName(code, reverify);
        if (!active) return;
        setNickname(res.nickname);
        setAutoNamed(res.auto_generated);
        setGateComplete(true);
      } catch {
        // On any failure, fall back to the normal NicknameGate flow.
      }
    })();
    return () => { active = false; };
  }, [code, gateComplete, identityLoading, reverify]);
```

Update the three `IdentityBar` usages to pass the rename affordance (add `autoNamed` + `onRename`):

```typescript
        <IdentityBar
          nickname={nickname}
          emailVerified={emailVerified}
          onVerified={() => setEmailVerified(true)}
          autoNamed={autoNamed}
          onRename={async (newName: string) => {
            await api.ensureGuestName(code, reverify, newName);
            setNickname(newName);
            setAutoNamed(false);
          }}
          forceDark
        />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run join`
Expected: PASS (new test + existing gate tests still green).

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/join/[code]/page.tsx" "dashboard/app/join/[code]/__tests__/page.test.tsx"
git commit -m "feat(join): skip nickname gate + auto-name on frictionless events (#369)"
```

---

## Task 10: IdentityBar "Add a name" rename affordance

**Files:**
- Modify: `dashboard/components/IdentityBar.tsx`
- Test: `dashboard/components/__tests__/IdentityBar.test.tsx` (create if absent)

- [ ] **Step 1: Write the failing test**

```typescript
// dashboard/components/__tests__/IdentityBar.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { IdentityBar } from '../IdentityBar';

describe('IdentityBar rename', () => {
  it('shows "Add a name" when autoNamed and calls onRename', async () => {
    const onRename = vi.fn().mockResolvedValue(undefined);
    render(
      <IdentityBar nickname="DancingPanda" emailVerified={false} onVerified={() => {}}
        autoNamed onRename={onRename} />
    );
    fireEvent.click(screen.getByText(/Add a name/i));
    fireEvent.change(screen.getByPlaceholderText(/your name/i), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByText(/^Save$/));
    await waitFor(() => expect(onRename).toHaveBeenCalledWith('Alex'));
  });

  it('does not show "Add a name" when not autoNamed', () => {
    render(<IdentityBar nickname="Alex" emailVerified={false} onVerified={() => {}} />);
    expect(screen.queryByText(/Add a name/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run IdentityBar`
Expected: FAIL — `autoNamed`/`onRename` not supported; no "Add a name" control.

- [ ] **Step 3: Extend IdentityBar**

In `dashboard/components/IdentityBar.tsx`, extend `Props`:

```typescript
interface Props {
  nickname: string;
  emailVerified: boolean;
  onVerified: () => void;
  picksLabel?: string;
  forceDark?: boolean;
  autoNamed?: boolean;
  onRename?: (newName: string) => Promise<void> | void;
}
```

Add local state + a minimal inline rename control. Inside the component, add:

```typescript
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState('');
  const [savingName, setSavingName] = useState(false);
```

(Import `useState` from `'react'` if not already imported.) Render an "Add a name" button next to the name when `autoNamed && onRename` and not already verified, and a tiny inline form when `renaming`:

```tsx
      {autoNamed && onRename && !renaming && (
        <button className="identity-bar-action" onClick={() => { setDraft(''); setRenaming(true); }}>
          Add a name
        </button>
      )}
      {renaming && (
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input
            className="input"
            placeholder="Your name"
            value={draft}
            maxLength={30}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
          />
          <button
            className="btn btn-primary"
            disabled={!draft.trim() || savingName}
            onClick={async () => {
              setSavingName(true);
              try { await onRename!(draft.trim()); setRenaming(false); }
              finally { setSavingName(false); }
            }}
          >
            Save
          </button>
        </span>
      )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run IdentityBar`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/IdentityBar.tsx dashboard/components/__tests__/IdentityBar.test.tsx
git commit -m "feat(join): IdentityBar 'Add a name' rename for auto-named guests (#369)"
```

---

## Task 11: DJ per-event toggle (event management)

**Files:**
- Modify: `dashboard/app/(dj)/events/[code]/page.tsx` (add `frictionlessJoin` state + `onToggleFrictionless`, mirroring the existing `requestsOpen`/`onToggleRequests` wiring)
- Modify: `dashboard/app/(dj)/events/[code]/components/EventManagementTab.tsx` (props pass-through)
- Modify: `dashboard/app/(dj)/events/[code]/components/KioskControlsCard.tsx` (render the toggle)
- Test: `dashboard/app/(dj)/events/[code]/components/__tests__/EventManagementTab.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// add to EventManagementTab.test.tsx (mirror existing requests-open toggle test)
it('renders Frictionless join toggle and fires handler', () => {
  const onToggleFrictionless = vi.fn();
  render(
    <EventManagementTab
      {...baseProps}
      frictionlessJoin={false}
      togglingFrictionless={false}
      onToggleFrictionless={onToggleFrictionless}
    />
  );
  fireEvent.click(screen.getByText(/Frictionless join/i));
  expect(onToggleFrictionless).toHaveBeenCalled();
});
```

(Use the file's existing `baseProps` helper; if absent, mirror the prop object the other tests in this file construct.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run EventManagementTab`
Expected: FAIL — no "Frictionless join" control.

- [ ] **Step 3: Thread the prop through**

In `KioskControlsCard.tsx`, extend the props interface with:

```typescript
  frictionlessJoin: boolean;
  togglingFrictionless: boolean;
  onToggleFrictionless: () => void;
```

Destructure them in the function signature, and render a toggle row mirroring the `onToggleRequests` button block:

```tsx
        <button
          type="button"
          className="kiosk-toggle"
          disabled={togglingFrictionless}
          onClick={onToggleFrictionless}
        >
          Frictionless join: {frictionlessJoin ? 'On' : 'Off'}
        </button>
        <p className="kiosk-toggle-help">
          Guests skip the nickname/email step and get an auto-generated name. Good for weddings & private parties.
        </p>
```

In `EventManagementTab.tsx`, add the three props to `EventManagementTabProps` and forward them to `<KioskControlsCard>`:

```tsx
          frictionlessJoin={props.frictionlessJoin}
          togglingFrictionless={props.togglingFrictionless}
          onToggleFrictionless={props.onToggleFrictionless}
```

In `app/(dj)/events/[code]/page.tsx`, add state + handler mirroring `requestsOpen`/`onToggleRequests`:

```typescript
  const [frictionlessJoin, setFrictionlessJoin] = useState(event?.frictionless_join ?? false);
  const [togglingFrictionless, setTogglingFrictionless] = useState(false);

  const onToggleFrictionless = async () => {
    if (!event) return;
    setTogglingFrictionless(true);
    try {
      const updated = await api.updateEvent(event.code, { frictionless_join: !frictionlessJoin });
      setFrictionlessJoin(updated.frictionless_join);
      setEvent(updated);
    } finally {
      setTogglingFrictionless(false);
    }
  };
```

Pass `frictionlessJoin`, `togglingFrictionless`, `onToggleFrictionless` into `<EventManagementTab>`. Initialize/sync `frictionlessJoin` from `event.frictionless_join` when the event loads (mirror how `requestsOpen` is synced from `event`).

Extend `updateEvent` in `dashboard/lib/api.ts` to accept the field:

```typescript
  async updateEvent(
    code: string,
    data: { expires_at?: string; name?: string; frictionless_join?: boolean },
  ): Promise<Event> {
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run EventManagementTab`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/(dj)/events/[code]/page.tsx" "dashboard/app/(dj)/events/[code]/components/EventManagementTab.tsx" "dashboard/app/(dj)/events/[code]/components/KioskControlsCard.tsx" dashboard/lib/api.ts "dashboard/app/(dj)/events/[code]/components/__tests__/EventManagementTab.test.tsx"
git commit -m "feat(join): DJ per-event frictionless toggle in event management (#369)"
```

---

## Task 12: DJ default toggle on Account page

**Files:**
- Modify: `dashboard/app/(dj)/account/page.tsx` (new "Guest Experience" card)
- Test: `dashboard/app/(dj)/account/__tests__/page.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
// add to dashboard/app/(dj)/account/__tests__/page.test.tsx
it('toggles frictionless_join_default and saves', async () => {
  mockApi.getMe.mockResolvedValue({
    id: 1, username: 'dj', role: 'dj', help_pages_seen: [],
    pending_email: null, email: null, frictionless_join_default: false,
  } as never);
  const update = vi.spyOn(mockApi, 'updateMyPreferences').mockResolvedValue(undefined as never);
  render(<AccountPage />);
  const toggle = await screen.findByLabelText(/Frictionless join by default/i);
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(update).toHaveBeenCalledWith({ frictionless_join_default: true })
  );
});
```

Add `updateMyPreferences: vi.fn()` to the test file's `mockApi`, and ensure `getMe` is mocked with `frictionless_join_default`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run account`
Expected: FAIL — no "Frictionless join by default" control.

- [ ] **Step 3: Add the card**

In `dashboard/app/(dj)/account/page.tsx`, add state:

```typescript
  const [frictionlessDefault, setFrictionlessDefault] = useState(false);
  const [savingPref, setSavingPref] = useState(false);
```

In the existing `api.getMe()` effect, also read the field:

```typescript
      api.getMe()
        .then(user => {
          if (!isActive) return;
          setEmailPending(prev => prev ?? (user.pending_email ?? null));
          setFrictionlessDefault(user.frictionless_join_default);
        })
        .catch(() => {});
```

Add a handler:

```typescript
  const handleToggleFrictionless = async () => {
    const next = !frictionlessDefault;
    setSavingPref(true);
    try {
      await api.updateMyPreferences({ frictionless_join_default: next });
      setFrictionlessDefault(next);
    } finally {
      setSavingPref(false);
    }
  };
```

Add a new card after the Change Email card (mirror the existing card styling):

```tsx
      <div style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginTop: '1.5rem' }}>
        <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Guest Experience</h2>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <input
            type="checkbox"
            checked={frictionlessDefault}
            disabled={savingPref}
            onChange={handleToggleFrictionless}
            aria-label="Frictionless join by default"
          />
          <span>
            Frictionless join by default (new events)
            <br />
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              New events let guests skip the nickname/email step and get an auto-generated name.
            </span>
          </span>
        </label>
      </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run account`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/(dj)/account/page.tsx" "dashboard/app/(dj)/account/__tests__/page.test.tsx"
git commit -m "feat(join): DJ frictionless-join default toggle on Account page (#369)"
```

---

## Task 13: Full local CI + final verification

- [ ] **Step 1: Backend CI**

Run:
```bash
cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/bandit -r app -c pyproject.toml -q && .venv/bin/alembic upgrade head && .venv/bin/alembic check && .venv/bin/pytest --tb=short -q
```
Expected: all green, coverage ≥ threshold, no migration drift.

- [ ] **Step 2: Frontend CI**

Run:
```bash
cd dashboard && npm run lint && npx tsc --noEmit && npm test -- --run
```
Expected: lint clean, no type errors, all vitest suites pass.

- [ ] **Step 3: Fix `next-env.d.ts` if touched**

Run: `cd dashboard && git checkout next-env.d.ts 2>/dev/null || true`

- [ ] **Step 4: Final commit (if any lint/format fixes were applied)**

```bash
git add -A && git commit -m "chore(join): lint/format fixes for frictionless join (#369)" || echo "nothing to commit"
```

---

## Self-review checklist (completed during plan authoring)

- **Spec coverage:** model (T1), auto-name lib (T2), EventOut+PATCH (T3), creation seed (T4), ensure-name+join-config+frictionless guard (T5), DJ default+PATCH /me (T6), types (T7), api client (T8), join page skip-gate+auto-name (T9), IdentityBar rename (T10), DJ per-event toggle (T11), DJ default UI (T12). Anti-abuse preserved: ensure-name keeps `require_verified_human_soft` and is guarded by `event.frictionless_join`. Collect untouched (no edits to collect gates). ✓
- **Placeholder scan:** no TBD/TODO; every code step has concrete code. ✓
- **Type consistency:** `ensureGuestName`/`getJoinConfig` return shapes match `EnsureNameResponse`/`JoinConfigResponse`; `frictionless_join` (Event) and `frictionless_join_default` (User) names consistent across backend, generated types, and frontend. ✓
- **Out of scope:** settings-hub consolidation, tri-state inherit, Turnstile removal — all deferred per spec. ✓

# Admin Guest Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin-only Guests page that lists every guest identity with email, Turnstile, and fingerprint signals, and lets an admin edit the nickname, revoke the email, or delete the guest.

**Architecture:** Two new columns on `guests` record Turnstile passes. A new `admin_guests` service builds one paginated query (collision subquery + membership batch load) that three admin routes expose. The dashboard page reuses the admin console's existing table/badge/tab/modal vocabulary with two small row/modal components.

**Tech Stack:** FastAPI, SQLAlchemy 2 (`Mapped`), Alembic, Pydantic v2, pytest; Next.js 16 / React 19, vanilla CSS, Vitest + Testing Library, `openapi-typescript`.

**Spec:** `docs/superpowers/specs/2026-10-21-admin-guest-management-design.md`

## Global Constraints

- Branch `feat/admin-guest-management` in this worktree; never commit to `main`. Conventional Commits with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Backend coverage gate `--cov-fail-under=85` must hold; `ruff check`, `ruff format --check`, `bandit`, `alembic upgrade head && alembic check` must pass. Run from `server/` with `.venv/bin/…`.
- Frontend: `npm run lint`, `npx tsc --noEmit`, `npm test -- --run`, and the generated-types check (`npm run types:generate && git diff --exit-code -- lib/api-types.generated.ts`). Vanilla CSS + inline styles only; existing tokens only.
- Admin routes use `get_current_admin`; list route `120/minute`, mutations `30/minute` (match the user routes).
- Masked email format: first character + `***@` + domain (`a***@example.com`). Never return the plaintext email.
- No IP-derived data anywhere (`docs/RECOVERY-IP-IDENTITY.md`).
- Files ≤ 400 lines; `app/api/admin.py` is at 371, so the three routes go in a new `app/api/admin_guests.py` router mounted under the same `/admin` prefix.

## Review Focus

1. A `q` containing `%` or `_` must be a literal search, not a wildcard (Task 3 test `test_search_escapes_like_wildcards`).
2. A guest whose `fingerprint_hash` is `NULL` must report `fingerprint_shared_with == 0` and never match the `shared` filter, even when several guests have `NULL` (Task 3 test `test_null_fingerprints_are_not_shared`).
3. Deleting a guest with requests and votes must leave those rows in place with `guest_id` `NULL` (Task 4 test `test_delete_keeps_requests_anonymised`).
4. `PATCH` with an empty body must change nothing and still return 200 (Task 4 test `test_patch_empty_body_is_noop`).
5. A per-event nickname that only differs by case from another profile in the same event must be rejected with 409, not a 500 from the unique index (Task 4 test `test_patch_profile_nickname_conflict_409`). Note: the test DB is SQLite and the functional index is Postgres-only, so the service checks for the conflict itself before writing.

---

### Task 1: Record Turnstile passes on the guest

**Files:**
- Create: `server/alembic/versions/074_guest_human_verification.py`
- Modify: `server/app/models/guest.py`
- Modify: `server/app/services/human_verification.py`
- Modify: `server/app/api/guest.py:84-98`
- Test: `server/tests/test_verify_human_endpoint.py`

**Interfaces:**
- Produces: `Guest.human_verified_at: datetime | None`, `Guest.human_verify_count: int`;
  `record_human_verification(db: Session, guest_id: int) -> None` in `app/services/human_verification.py`.

- [ ] **Step 1: Write the failing test** in `TestVerifyHumanEndpoint`:

```python
@patch("app.api.guest.verify_turnstile_token", new_callable=AsyncMock, return_value=True)
def test_success_records_pass_on_guest(self, mock_turnstile, client, db):
    guest = _create_guest(db)
    client.cookies.set("wrzdj_guest", guest.token)
    client.post("/api/public/guest/verify-human", json={"turnstile_token": "t"})
    client.post("/api/public/guest/verify-human", json={"turnstile_token": "t"})
    db.refresh(guest)
    assert guest.human_verify_count == 2
    assert guest.human_verified_at is not None

@patch("app.api.guest.verify_turnstile_token", new_callable=AsyncMock, return_value=False)
def test_failure_does_not_record_pass(self, mock_turnstile, client, db):
    guest = _create_guest(db)
    client.cookies.set("wrzdj_guest", guest.token)
    client.post("/api/public/guest/verify-human", json={"turnstile_token": "bad"})
    db.refresh(guest)
    assert guest.human_verify_count == 0
    assert guest.human_verified_at is None
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_verify_human_endpoint.py -q --no-cov` → FAIL (`AttributeError: human_verify_count`).

- [ ] **Step 3: Add the columns** to `Guest`: `human_verified_at = mapped_column(DateTime, nullable=True)`; `human_verify_count = mapped_column(Integer, default=0, server_default="0", nullable=False)`.

- [ ] **Step 4: Write migration 074** (`revision = "074"`, `down_revision = "073"`): `add_column` both (count with `server_default="0"`, `nullable=False`); downgrade drops both.

- [ ] **Step 5: Implement `record_human_verification(db, guest_id)`**: load the guest, set `human_verified_at = utcnow()`, increment the count, commit. No-op when the guest row is missing. Call it in `verify_human` after the Turnstile check passes and before `issue_human_cookie`.

- [ ] **Step 6: Run** the file again → PASS. Then `.venv/bin/alembic upgrade head && .venv/bin/alembic check` → "No new upgrade operations detected."

- [ ] **Step 7: Commit** `feat(guest): record Turnstile passes per guest (#862)`.

---

### Task 2: Admin guest schemas and serialisation helpers

**Files:**
- Create: `server/app/schemas/admin_guest.py`
- Modify: `server/app/services/guest_identity.py` (add `browser_label`)
- Create: `server/app/services/admin_guests.py` (helpers only in this task)
- Test: `server/tests/test_admin_guests.py` (unit section)

**Interfaces:**
- Produces: `AdminGuestEventOut(event_id, code, name, nickname, submission_count, joined_at)`;
  `AdminGuestOut(id, nickname, browser, email_verified, email_masked, email_verified_at, human_verified_at, human_verify_count, fingerprint_short, fingerprint_shared_with, created_at, last_seen_at, event_count, request_count, events)`;
  `AdminGuestUpdate(revoke_email: bool = False)`;
  `AdminGuestProfileUpdate(nickname: str | None = Field(None, max_length=30))`;
  `GuestFilter = Literal["all", "verified", "unverified", "shared"]`;
  `browser_label(user_agent: str | None) -> str | None` ("Safari · iOS"; `None` when family unknown);
  `mask_email(email: str) -> str`.

- [ ] **Step 1: Write failing unit tests** at the top of `tests/test_admin_guests.py`:

```python
def test_mask_email():
    assert mask_email("alice@example.com") == "a***@example.com"
    assert mask_email("a@b.co") == "a***@b.co"

def test_browser_label():
    assert browser_label("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1") == "Safari · iOS"
    assert browser_label("curl/8.0") is None
    assert browser_label(None) is None
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_admin_guests.py -q --no-cov` → FAIL (import error).

- [ ] **Step 3: Implement** the schemas (all `Out` models extend `BaseSchema` from `app.schemas.common`), `browser_label` beside `_parse_ua` (title-case family, platform label map `ios→iOS, android→Android, windows→Windows, macos→macOS, linux→Linux`), and `mask_email` in `admin_guests.py`.

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(admin): guest schemas and label helpers (#862)`.

---

### Task 3: List guests service + route

**Files:**
- Modify: `server/app/services/admin_guests.py`
- Create: `server/app/api/admin_guests.py`
- Modify: `server/app/api/__init__.py` (mount under `/admin`, tag `admin`)
- Test: `server/tests/test_admin_guests.py`

**Interfaces:**
- Produces: `list_guests(db, *, page: int, limit: int, filter: GuestFilter, q: str | None) -> tuple[list[dict], int]`;
  `serialize_guest(db, guest: Guest) -> dict` (single-guest version used by Task 4);
  `GET /api/admin/guests?page&limit&filter&q` → `PaginatedResponse`.

- [ ] **Step 1: Write failing tests** (fixture `guests` creates: A verified email `alice@example.com`, hash `h1`, 2 Turnstile passes, `GuestProfile` on `test_event` with nickname "Alice"; B unverified, hash `h1`, profile on `test_event` with nickname "bob_1"; C unverified, hash `None`, no profile; D unverified, hash `None`, no profile; A has one `Request` on `test_event`). `nickname` in the response is the newest profile nickname:

```python
def test_list_guests_shape(client, admin_headers, guests):
    data = client.get("/api/admin/guests", headers=admin_headers).json()
    assert data["total"] == 4
    a = next(g for g in data["items"] if g["nickname"] == "Alice")
    assert a["email_verified"] is True and a["email_masked"] == "a***@example.com"
    assert a["human_verify_count"] == 2 and a["human_verified_at"]
    assert a["fingerprint_short"] == "h1" and a["fingerprint_shared_with"] == 1
    assert a["event_count"] == 1 and a["request_count"] == 1
    assert a["events"][0]["code"] == test_event.code  # pass test_event into the test
    assert a["browser"] == "Safari · iOS"

def test_filter_verified / test_filter_unverified / test_filter_shared  # totals 1 / 3 / 2
def test_null_fingerprints_are_not_shared(...)  # C and D: fingerprint_shared_with == 0, absent from shared
def test_search_nickname_case_insensitive(...)  # q=ALICE → total 1
def test_search_escapes_like_wildcards(...)     # q=b_b → total 0 (literal underscore), q=% → total 0
def test_invalid_filter_400 / test_dj_forbidden_403 / test_pending_forbidden_403 / test_anonymous_401
```

- [ ] **Step 2: Run** → FAIL (404 route missing).

- [ ] **Step 3: Implement `list_guests`**: collision subquery `select(Guest.fingerprint_hash, func.count(Guest.id).label("n")).where(Guest.fingerprint_hash.is_not(None)).group_by(...)`; outer-join it on hash; `shared` filter = `n > 1`; `verified` = `email_verified_at.is_not(None)`; search = `EXISTS` subquery on `GuestProfile.nickname.ilike(f"%{escaped}%", escape="\\")` with `q` escaped for `\\ % _`; order `last_seen_at desc, id desc`; count then page. Batch-load `GuestProfile` joined to `Event` (ordered `created_at desc`) and `Request` counts for the page's guest ids in one query each; the display `nickname` is the first non-null profile nickname in that order. `serialize_guest` reuses the same row builder for one guest.

- [ ] **Step 4: Implement the route** with `page: int = Query(1, ge=1, le=1000)`, `limit: int = Query(20, ge=1, le=100)`, `filter: str = "all"` (400 on invalid), `q: str | None = Query(None, max_length=30)`.

- [ ] **Step 5: Run** the file → PASS. **Step 6: Commit** `feat(admin): paginated guest list with verification and fingerprint signals (#862)`.

---

### Task 4: Edit and delete routes

**Files:**
- Modify: `server/app/services/admin_guests.py`, `server/app/api/admin_guests.py`
- Test: `server/tests/test_admin_guests.py`

**Interfaces:**
- Produces: `get_guest_by_id(db, guest_id) -> Guest | None`;
  `revoke_guest_email(db, guest) -> Guest`;
  `update_guest_profile_nickname(db, guest, event_id: int, nickname: str | None) -> GuestProfile` (raises `ProfileNotFound`, `NicknameTaken`);
  `delete_guest_admin(db, guest) -> None`;
  `PATCH /api/admin/guests/{guest_id}` → `AdminGuestOut`; `PATCH /api/admin/guests/{guest_id}/events/{event_id}` → `AdminGuestOut`; `DELETE /api/admin/guests/{guest_id}` → 204.

- [ ] **Step 1: Write failing tests**:

```python
def test_patch_empty_body_is_noop(...)            # {} → 200, email unchanged
def test_patch_revoke_email(...)                  # email_verified False, email_masked None, email_verified_at None; DB verified_email/email_hash None
def test_patch_404 / test_patch_dj_403
def test_patch_profile_nickname(...)              # {"nickname": "  Zed "} → events[0].nickname "Zed", top-level nickname "Zed"
def test_patch_profile_nickname_empty_clears(...) # {"nickname": ""} → None
def test_patch_profile_nickname_conflict_409(...) # another profile "zed" (lower-case) on the same event → 409 "Nickname already taken in this event"
def test_patch_profile_same_guest_case_change_ok(...) # "Alice" → "ALICE" on own profile → 200
def test_patch_profile_404_when_not_member(...)   # event the guest never joined → 404
def test_delete_removes_profiles(...)             # 204; GuestProfile rows for guest gone
def test_delete_keeps_requests_anonymised(...)    # Request + RequestVote rows remain, guest_id None, Request.nickname None
def test_delete_404 / test_delete_dj_403
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the service functions and three routes. Conflict check: `GuestProfile` on the same `event_id`, `func.lower(nickname) == new.lower()`, `id != profile.id`. Delete, in one transaction: `db.query(Request).filter(Request.guest_id == guest.id).update({"nickname": None})`, `db.query(GuestProfile).filter(GuestProfile.guest_id == guest.id).delete()`, `db.delete(guest)`, commit.

- [ ] **Step 4: Run** the whole backend suite `.venv/bin/pytest --tb=short -q` → PASS, coverage ≥ 85. Run `ruff check .`, `ruff format --check .`, `bandit -r app -c pyproject.toml -q`. **Step 5: Commit** `feat(admin): edit nickname, revoke email, and delete guests (#862)`.

---

### Task 5: OpenAPI export, dashboard API client, relative-age helper

**Files:**
- Modify: `server/openapi.json` (via `.venv/bin/python scripts/export_openapi.py`)
- Modify: `dashboard/lib/api-types.generated.ts` (via `npm run types:generate`)
- Modify: `dashboard/lib/api-types.ts` (export `AdminGuest`, `AdminGuestEvent`, `AdminGuestUpdate`, `AdminGuestProfileUpdate`, `AdminGuestFilter`)
- Modify: `dashboard/lib/api.ts` after `bulkDeleteAdminEvents`
- Modify: `dashboard/lib/format-time.ts`
- Test: `dashboard/lib/__tests__/format-time.test.ts`, `dashboard/lib/__tests__/api.test.ts`

**Interfaces:**
- Produces: `api.getAdminGuests(page = 1, limit = 20, filter: AdminGuestFilter = 'all', q?: string): Promise<PaginatedResponse<AdminGuest>>`;
  `api.updateAdminGuest(id: number, data: AdminGuestUpdate): Promise<AdminGuest>`;
  `api.updateAdminGuestProfile(id: number, eventId: number, data: AdminGuestProfileUpdate): Promise<AdminGuest>`;
  `api.deleteAdminGuest(id: number): Promise<void>`;
  `formatRelativeAge(iso: string, now?: Date): string` → `just now` (<60 s), `5m ago`, `2h ago`, `3d ago`, else `toLocaleDateString()`.

- [ ] **Step 1: Write failing tests** for `formatRelativeAge` (the five branches) and for the three API methods (URL + method, matching the existing `getAdminUsers` test style in `api.test.ts`).
- [ ] **Step 2: Run** `npm test -- --run lib/__tests__/format-time.test.ts lib/__tests__/api.test.ts` → FAIL.
- [ ] **Step 3: Regenerate** `openapi.json` and the generated types; add the exports and methods; implement `formatRelativeAge`.
- [ ] **Step 4: Run** → PASS; `npx tsc --noEmit` clean. **Step 5: Commit** `feat(dashboard): admin guest API client and relative-age formatter (#862)`.

---

### Task 6: Guests page

**Files:**
- Create: `dashboard/app/admin/guests/page.tsx`
- Create: `dashboard/app/admin/guests/components/GuestRow.tsx`
- Create: `dashboard/app/admin/guests/components/GuestEditModal.tsx`
- Modify: `dashboard/app/admin/layout.tsx:33-40` (nav item `{ href: '/admin/guests', label: 'Guests' }` after Events)
- Modify: `dashboard/app/globals.css` (only if a reusable rule is needed: `.admin-table-detail` for the expanded row)
- Test: `dashboard/app/admin/guests/__tests__/page.test.tsx`

**Interfaces:**
- Consumes Task 5's `api` methods and types.
- `GuestRow({ guest, expanded, onToggle, onEdit, onDelete })`; `GuestEditModal({ guest, onClose, onSaved })`.

- [ ] **Step 1: Write failing page tests** (mock `@/lib/help/HelpContext` and `@/lib/api` exactly as the users test does):

```
renders heading "Guest Management" and the four filter tabs
displays guests with masked email, "Verified"/"Unverified" badges, "Unique"/"Shared ×1"/"None" badges
shows "Never" for a guest with no Turnstile pass and "2 passes" for one with two
expands a row to show event memberships (code + per-event nickname)
search input calls getAdminGuests(1, 20, 'all', 'ali') after debounce (vi.useFakeTimers)
filter tab calls getAdminGuests(1, 20, 'shared', undefined)
edit modal saves a changed per-event nickname via updateAdminGuestProfile(id, eventId, { nickname: 'Zed' }) and revoke via updateAdminGuest(id, { revoke_email: true }); unchanged fields send nothing
edit modal shows a 409 message next to the input and stays open
delete calls window.confirm then deleteAdminGuest(id)
shows "No guests match this filter." when items is empty
shows "Failed to load guests" when the API rejects
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Build the page** per the spec's Frontend section: `useAdminPage` with `PAGE_ID = 'admin-guests'`; header with total count; tabs; search `input.input` with `aria-label="Search by nickname"`; `table.admin-table` with the eight columns; detail row rendered as a second `<tr>` with `colSpan={8}`; `HelpSpot`s on header, filters, table, actions. Copy fixed by the spec: badges `Verified`, `Unverified`, `Unique`, `Shared ×N`, `None`; human cell `N passes · <age>` / `Never`; empty state `No guests match this filter.`; confirm text from the spec.
- [ ] **Step 4: Run** the tests → PASS; `npm run lint`; `npx tsc --noEmit`; `npm test -- --run`.
- [ ] **Step 5: Visual check**: start the backend and dashboard from this worktree (see `project_worktree_push_to_testing` memory: `--webpack`, worktree `.env`), log in as admin, screenshot `/admin/guests` at 1280 and 390 wide via the page's own render path. Fix contrast, spacing, focus rings, and overflow in one batch.
- [ ] **Step 6: Commit** `feat(admin): guest management page (#862)`.

---

### Task 7: Finish

- [ ] Run every CI check listed in Global Constraints from the worktree; paste outcomes.
- [ ] Push the branch, open a **draft** PR with the Why/What/Testing template, `Closes #862`, agent credit; move #862 to `In review`.
- [ ] Run the one end-of-branch adversarial review (Codex `gpt-5.6-sol` xhigh, read-only, `git diff main...HEAD`); fix material findings; re-run checks; push.

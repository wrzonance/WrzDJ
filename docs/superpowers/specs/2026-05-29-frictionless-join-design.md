# Frictionless Join — Design Spec

**Issue:** #369 — "Restore 'Scan QR → Request Song' Guest Flow (No Signup/Email Verification)"
**Date:** 2026-05-29
**Author:** thewrz
**Status:** Approved (brainstorm) → pending implementation plan

## Problem

The `/join` (live-event) guest page currently blocks the entire experience behind
`NicknameGate` (`dashboard/app/join/[code]/page.tsx:389` — `if (!gateComplete) return <NicknameGate />`).
A first-time guest must pick "New name" → type a nickname (≥2 chars) → Save → Skip email
(~4 interactions) before they can even see the song search.

For weddings / private parties this friction is unwanted: the QR code is handed out only
to in-room guests during the event, so heavy bot-hardening is unnecessary there. The
hardening was added primarily for the long-lived, public-internet `/collect` (pre-event
voting) page, and its nickname/email requirements leaked into the live `/join` flow.

The fix removes only the **nickname/email** friction on `/join`, while keeping the
invisible anti-abuse layer (Turnstile human-cookie + guest fingerprint) intact, and never
touching `/collect`.

## Key facts grounding the design

- Friction is **frontend-only**. Backend join endpoints (`events.py` search/submit/vote)
  already gate on `require_verified_human_soft` — no nickname, no email server-side.
- The nickname is **not** the anti-abuse key. Double-vote/dedup runs off the `wrzdj_guest`
  cookie + ThumbmarkJS fingerprint (`guest_id`). Dropping the nickname does not reopen
  double-voting.
- `/collect` hard gates (`require_email_verified`) live on `collect.py` endpoints. A
  join-only flag never reaches them.
- `GET /api/events/{code}` (`events.py:359`) is **public, no auth**, returns `EventOut` —
  this is what the join page reads via `api.getEvent(code)`. Adding the flag here surfaces
  it to the join page with no new fetch.
- Per-event booleans are well-precedented on `Event` (`requests_open`, `kiosk_display_only`,
  `tidal_sync_enabled`, …).

## Decisions (locked during brainstorm)

1. **Scope:** per-event override + per-DJ default, via a **snapshot** model.
   The DJ's default *pre-fills* a new event's own boolean at creation time; thereafter the
   event's boolean is the final say. No nullable column, no runtime resolution, no
   "default changed → old events mutate" surprise.
2. **Relaxed UX:** when frictionless is on, the guest lands **straight on song search**
   with an **auto-generated username**; an optional "Add a name" affordance lets them
   rename / claim later. Never required.
3. **Username generation:** server-side via `coolname` (BSD-2-Clause, zero deps, actively
   maintained). Numeric suffix on collision.
4. **Identity:** keep the existing ThumbmarkJS fingerprint + `wrzdj_guest` cookie. No change.
5. **Anti-abuse preserved:** Turnstile human-verification (`require_verified_human_soft`,
   invisible managed mode) stays on `/join`. Only nickname/email friction is removed.

## Data model

- `User.frictionless_join_default: Mapped[bool]` — default `False`. The DJ's personal default.
- `Event.frictionless_join: Mapped[bool]` — default `False`. **Seeded from the creator's
  `frictionless_join_default` at event creation**, editable per-event afterward.

Alembic migration adds both columns. Models get matching `Mapped[bool]` definitions; run
`alembic upgrade head && alembic check` locally (CI enforces no drift).

## Backend

### Auto-name service
- New dependency: `coolname` in `server/pyproject.toml` (BSD-2-Clause, zero transitive deps,
  Python 3.10+; backend is 3.11+).
- New `server/app/services/guest_names.py`:
  - `generate_unique_nickname(db, event) -> str` → `coolname.generate_slug(2)` →
    title-cased, hyphen-stripped → `"DancingPanda"`.
  - On collision (reuse the existing per-event nickname uniqueness check used by the
    collect claim flow), append 2–3 random digits and retry up to **5 times**; if still
    colliding, fall back to `coolname.generate_slug(3)` (three words, collision-proof in
    practice).

### Ensure-name endpoint
- New public endpoint `POST /api/public/events/{join_code}/guest/ensure-name`:
  - Gated by `require_verified_human_soft` (same human-cookie layer as other join endpoints).
  - If the event is frictionless **and** the resolved guest has no nickname: generate +
    store one.
  - Returns `{ nickname: str, auto_generated: bool }`. Idempotent — returns the existing
    nickname (with `auto_generated` reflecting how it was set) if one already exists.
  - If the event is **not** frictionless, this endpoint is a no-op / not used by the
    frontend (the normal `NicknameGate` flow runs instead).

### Expose + edit
- `EventOut` (`server/app/schemas/event.py`) gains `frictionless_join: bool` — read by the
  public join page.
- `PATCH /api/events/{code}` accepts `frictionless_join: bool` (DJ per-event toggle; owner-scoped).
- Per-DJ default `frictionless_join_default`:
  - **Read** via the existing `GET /api/auth/me` (the user object the account page already
    fetches via `api.getMe()`); add the field to that response.
  - **Written** via a new self-service preferences endpoint `PATCH /api/auth/me`
    (owner = current user; no admin route). Password/email already have dedicated routes;
    this is the first general user-preferences PATCH.
  - Event creation reads the creator's `frictionless_join_default` to seed the new event's
    `frictionless_join`.

## Frontend

### Join page — `dashboard/app/join/[code]/page.tsx`
- When `event.frictionless_join` is true:
  - **Skip `<NicknameGate>`** (the `if (!gateComplete)` early return at line 389).
  - On load, call `api.ensureGuestName(code)`, set `nickname` from the response, mark
    `gateComplete`. Guest lands straight on search.
- `IdentityBar`: when the name is auto-generated (`auto_generated: true`), show an
  **"Add a name" / rename** affordance → small modal reusing the nickname input; the email /
  cross-device path remains available there but never required.
- When `event.frictionless_join` is false: today's `NicknameGate` flow, unchanged.

### DJ controls
- Event management page: a "Frictionless join" checkbox in the event settings card (wires
  `PATCH /{code}`). Helper text: "Guests skip the nickname/email step and get an
  auto-generated name. Good for weddings & private parties."
- DJ default lives on the **existing Account Settings page** (`app/(dj)/account/page.tsx`,
  reached via the dashboard "Account" button → `/account`). Add a new "Guest Experience"
  card with a "Frictionless join by default (new events)" toggle; read from `api.getMe()`,
  save via `api.updateMyPreferences({ frictionless_join_default })` → `PATCH /api/auth/me`.

### API client (`dashboard/lib/api.ts`)
- Add `ensureGuestName(code): Promise<{ nickname: string; auto_generated: boolean }>`
  (public, no auth).
- Add `updateMyPreferences({ frictionless_join_default }): Promise<User>` → `PATCH /api/auth/me`.
- Extend the `Event` type with `frictionless_join: boolean` and the `User`/`getMe` type with
  `frictionless_join_default: boolean`.

## Explicitly untouched

- `/collect` page and `collect.py` endpoints — all hard gates (`require_email_verified`)
  stay. The flag is never read there.
- Turnstile human-verification on `/join` — stays (invisible managed mode).
- Dedup / anti-double-vote — still `wrzdj_guest` cookie + ThumbmarkJS fingerprint.

## Testing

### Backend (pytest)
- Migration upgrade + `alembic check` (no drift).
- `guest_names.generate_unique_nickname`: happy path + collision → suffix retry.
- Ensure-name endpoint: frictionless on (generates), frictionless off (no-op), idempotency
  (second call returns same nickname), human-cookie gate behavior.
- `EventOut` serializes `frictionless_join`.
- Event creation seeds `frictionless_join` from the creator's `frictionless_join_default`.
- `PATCH /{code}` updates `frictionless_join` (owner-scoped; non-owner rejected).

### Frontend (vitest)
- Join page: skips gate + shows search when `frictionless_join` true; renders `NicknameGate`
  when false.
- `IdentityBar`: rename affordance appears for auto-generated names.
- DJ controls: event checkbox + DJ-default toggle call the right endpoints.
- Update `Event` / EventOut fixtures with the new field (per CLAUDE.md shared-type pitfall).

## Future consolidation (noted, not in this PR)

The `frictionless_join_default` toggle is added to the existing `/account` page as a first
step. Eventually the Account page should become a unified DJ settings hub that absorbs:
- the current Account Settings (password / email),
- this new Guest Experience default, and
- the **AI settings** currently at `/settings/ai` (from the `epic/ai-engine` branch).

This PR only adds the new card to `/account`; the broader merge of `/settings/ai` into
`/account` is tracked separately and must wait until `epic/ai-engine` lands on `main`.

## Out of scope (YAGNI)

- Live "inherit" tri-state on the event column (snapshot model chosen instead).
- Per-event auto-name vocabulary customization.
- Removing Turnstile from `/join`.
- The full settings-hub consolidation above (separate effort, post-`epic/ai-engine`).

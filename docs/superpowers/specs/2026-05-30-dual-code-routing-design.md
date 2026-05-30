# Dual-Code Routing Fix — Design

**Status:** Draft for approval
**Author:** thewrz
**Date:** 2026-05-30
**Issue:** [#382](https://github.com/thewrz/WrzDJ/issues/382) — Dual-code routing breaks frictionless `/join`
**Related:** #324 (collection-vs-live code split — `2026-05-20-collection-vs-live-event-codes-design.md`), #380 (frictionless join — `2026-05-29-frictionless-join-design.md`), #381 (nickname email-gate fix)

## Background

The #324 split gave each event two public codes on one row: `event.code` (collection — long-lived, social-media, gated) and `event.join_code` (live — day-of, in-venue, frictionless). That spec's routing audit told implementers to "route every `Event.code ==` filter through the appropriate helper" but the audit was **incomplete**: the live `/join` page also calls the general `/api/events/{code}` family (`get_event`, `event_search`, `submit_request`), which were never migrated and still resolve by **collection code**.

Then #380 (frictionless) added two new collection-router endpoints (`join-config`, `ensure-name`) and three cross-page reads (`getCollectEvent` for phase, `getCollectProfile` for email-verified) **onto the live `/join` page** — all resolving by collection code, all called with `join_code`. This re-introduced and widened the mismatch.

**Net effect:** no single `{code}` value makes the `/join` page work. The real DJ share link carries `join_code` (`events.py` builds `join_url = /join/{event.join_code}`), so the canonical link hits the collection-resolving main loader and 404s into the error screen. Using the collection code instead loads the shell but every live endpoint (queue, votes, SSE) 404s, leaving a permanently empty queue.

This is a **resolution-layer** defect only. De-dupe, votes, OTP, and guest identity are keyed by `event_id + guest_id`, never by the code string — so once a call resolves to the right `Event`, every downstream path is already correct. The blast radius is "which lookup each guest endpoint uses."

## Root cause — corrected routing matrix

Every endpoint the `/join/[code]` page calls today, with how the backend resolves the URL `{code}`:

| Frontend call | Endpoint | Router | Resolves by | Broken on `join_code`? |
|---|---|---|---|---|
| `getEvent` (main loader) | `GET /api/events/{code}` | events.py | **collection** | ✗ 404 → error screen |
| `eventSearch` | `GET /api/events/{code}/search` | events.py | **collection** | ✗ |
| `submitRequest` | `POST /api/events/{code}/requests` | events.py | **collection** | ✗ |
| `getJoinConfig` | `GET /api/public/collect/{code}/join-config` | collect.py | **collection** | ✗ |
| `ensureGuestName` | `POST /api/public/collect/{code}/guest/ensure-name` | collect.py | **collection** | ✗ |
| `getCollectEvent` (phase) | `GET /api/public/collect/{code}` | collect.py | **collection** | ✗ |
| `getCollectProfile` (email-verified) | `GET /api/public/collect/{code}/profile` | collect.py | **collection** | ✗ |
| `getCollectProfile`/`setCollectProfile` **via `NicknameGate`** | `GET`/`POST /api/public/collect/{code}/profile` | collect.py | **collection** | ✗ (non-frictionless path) |
| `checkHasRequested` | `GET /api/public/events/{code}/has-requested` | public.py | join_code | ✓ works |
| `getPublicRequests` | `GET /api/public/events/{code}/requests` | public.py | join_code | ✓ works |
| `MyRequestsTracker` | `GET /api/public/events/{code}/my-requests` | public.py | join_code | ✓ works |
| `useEventStream` | `GET /api/public/events/{code}/stream` | sse.py | join_code | ✓ works |

`NicknameGate` is a **shared component** mounted by both the collect page (collection code) and the non-frictionless `/join` path (`join_code`), so its profile reads/writes are part of the broken surface.

### Two latent bugs surfaced during analysis

1. **Private id leak.** `GET /api/events/{code}` returns `EventOut`, which serializes `id: int` (= `event.id`) plus **both** codes and `join_url`/`collect_url`. The `/join` page calls this — so the canonical private key the product wants kept blind is exposed to guests whenever that call succeeds. `event.id` is already the de-facto private identifier (every guest handler operates on it server-side and never serializes it elsewhere); the fix is to keep it that way on the live surface.
2. **SSE channel keying.** `event_bus` channels are keyed by a single code string. The stream endpoint resolves `join_code → event` then subscribes by **`event.code`** (canonical). Publishers must therefore publish on `event.code`, not the URL code. `submit_request` currently publishes the **URL** `code`; today that equals `event.code` (DJ uses collection code), but once a `join_code` can reach submit, publishing the URL code would post to the wrong channel and the guest's own submit would never reach the guest's own stream.

## Goals

- Every **guest-facing** endpoint resolves to the same `Event` regardless of which of the event's two public codes the client holds. Codes are globally unique across both columns (`generate_unique_event_code`), so this is collision-free.
- The live `/join` page works end-to-end via the real `join_code` share link: load, frictionless auto-name **or** nickname gate, queue, votes, search, submit, SSE, email verification, lost-cookie → re-login → guest-merge.
- Behavioral boundaries (frictionless vs collect) stay enforced by **flags and auth dependencies** (`event.frictionless_join`, `require_email_verified`, `require_verified_human`), never by code identity.
- Close the `event.id` leak on the live guest surface.
- Drift-resistant: one canonical guest resolver + guard tests that fail if a future feature wires the wrong lookup or leaks the private id.
- No regression to collect page, DJ dashboard, kiosk, or bridge.

## Non-goals

- Changing the two-code product model (#324 stays). Collect remains long-lived/gated; join remains day-of/frictionless.
- **Hard capability-scoping** (collect endpoints rejecting `join_code` and vice versa). Explicitly decided against: both codes are public and map to one event, the private key is `event.id`, and behavioral gating lives in flags/auth — so cross-code resolution carries no security weight. The cost (endpoint twins + parametrizing the shared `NicknameGate`) is exactly the redundancy/drift we want to avoid.
- A third/encrypted code. `event.id` already is the private canonical key; encrypting a value never transmitted is negative ROI.
- Changing collect-page auth (email + human) — unchanged.
- Changing DJ `get_event`/`EventOut` (still exposes `id` to the **authenticated** DJ) — out of scope; we only stop guests from hitting it.
- Bridge (`event.code`), kiosk display/`kiosk-link` (`join_code`/`code` as today), DJ management resolution — unchanged.
- Token-enumeration hardening (code length / rate limits) — orthogonal; tracked separately.

## Design

### 1. Canonical guest resolver (single source of truth)

```python
# server/app/services/event.py  (or_ already imported)

def get_event_by_public_code_with_status(
    db: Session, code: str
) -> tuple[Event | None, EventLookupResult]:
    """Resolve a guest-facing public code that may be EITHER the collection
    `code` or the live `join_code` (one event, two public handles). Behavioral
    gating is enforced by the endpoint's flags/auth deps, never by which code
    resolved the event."""
    event = (
        db.query(Event)
        .filter(or_(Event.code == code.upper(), Event.join_code == code.upper()))
        .first()
    )
    return _event_with_status(event)
```

Reuses the existing `_event_with_status` (NOT_FOUND / ARCHIVED / EXPIRED / FOUND), so every consumer keeps identical 404/410 semantics.

### 2. Resolution swaps (the whole change is "use the canonical resolver on the guest surface")

| Location | Today | After |
|---|---|---|
| collect.py `_get_event_or_404` | `Event.code == code` | canonical — covers preview, leaderboard, profile GET/POST, join-config, ensure-name, profile/me, requests, vote, enrich-preview, live-join-code in one swap |
| events.py `event_search` | `get_event_by_code_with_status` | canonical |
| events.py `submit_request` | `get_event_by_code_with_status` | canonical |
| public.py `get_public_requests`, `check_has_requested`, `get_my_requests` | join_code | canonical (behavior-preserving for existing join_code callers) |
| sse.py `event_stream` | join_code | canonical (still subscribes by `event.code`) |
| events.py `get_event` (DJ + kiosk-link) | collection | **unchanged** (DJ/authed; guest use is removed — see §3) |
| public.py `get_kiosk_display`, bridge, DJ management | as today | **unchanged** |

After this, there is exactly **one** resolver for the guest-join surface. `NicknameGate` works on both pages with **zero component change** (its profile reads/writes now resolve either code).

### 3. New guest-safe live event endpoint (closes the id leak + collapses 3 calls → 1)

```
GET /api/public/events/{code}   (canonical resolver, no auth)  → PublicEventResponse
```

New `PublicEventResponse` schema (`server/app/schemas/public.py`) — guest-safe projection, **no `event.id`**:

| Field | Source | Why |
|---|---|---|
| `name` | `event.name` | header |
| `collection_code` | `event.code` | the pre-event `/collect/{code}` cross-link (the public long-term code) |
| `requests_open` | `event.requests_open` | CTA + closed state |
| `status` | `compute_event_status` | active/expired/archived (drives 410 UX) |
| `banner_url`, `banner_colors` | banner helpers | theming |
| `phase` | `event.phase` | pre-event banner (replaces `getCollectEvent`) |
| `frictionless_join` | `event.frictionless_join` | gate decision (replaces `getJoinConfig`) |
| `submission_cap_per_guest` | `event.submission_cap_per_guest` | cap display |

This single call replaces the join page's `getEvent` (EventOut, leaked id) **+** `getJoinConfig` **+** `getCollectEvent`. `email_verified`/`nickname` stay guest-scoped via the existing `getCollectProfile` (now canonical), so this endpoint needs no guest cookie.

### 4. SSE publisher fix

Audit every `publish_event(...)` call site and key on the resolved **`event.code`**, not the URL `code`:
- `submit_request` (events.py) — **required**: a `join_code` submit must publish to the `event.code` channel the stream subscribes to.
- accept-all / reject-all / now-playing (events.py), status-change (requests.py), bridge (bridge.py) — change to `event.code` for explicitness; no-op today (DJ/bridge already pass collection code = `event.code`).

### 5. Frontend changes (live `/join` page only)

| File | Change |
|---|---|
| `dashboard/lib/api.ts` | Add `getPublicEvent(code) → PublicEventResponse` (`publicFetch /api/public/events/{code}`). No change to `ensureGuestName`/`eventSearch`/`submitRequest`/`getCollectProfile` — their paths now resolve canonically. |
| `dashboard/app/join/[code]/page.tsx` | Main loader: `getEvent` → `getPublicEvent`. Drop the separate `getJoinConfig` + `getCollectEvent` calls (folded into `getPublicEvent`: `frictionless_join`, `phase`). Phase-banner link uses `collection_code` from the response (not the URL `join_code`). Keep `getCollectProfile` for `email_verified`. |
| `dashboard/components/NicknameGate.tsx` | **No change.** |

Required frontend delta is small and mostly deletion. Everything else works once the backend resolvers go canonical.

## Testing

### Backend (pytest)

| Test | Asserts |
|---|---|
| `test_public_code_resolver_accepts_both` | `get_event_by_public_code_with_status` returns the same event for `code` and `join_code`; NOT_FOUND for a bogus code |
| `test_join_config_resolves_by_join_code` | `GET /collect/{join_code}/join-config` → 200 (was 404) |
| `test_ensure_name_resolves_by_join_code` | `POST /collect/{join_code}/guest/ensure-name` auto-names on a frictionless event reached by join_code |
| `test_frictionless_flag_gates_not_code` | `ensure-name` on a **non-frictionless** event returns 403 `frictionless_disabled` whether reached by `code` or `join_code` — boundary is the flag, not the code |
| `test_collect_submit_still_email_gated_via_join_code` | `POST /collect/{join_code}/requests` without verified email → 403 `email_verification_required` (no vote-pump regression) |
| `test_events_search_submit_resolve_by_join_code` | `GET /api/events/{join_code}/search` + `POST /api/events/{join_code}/requests` → 200 |
| `test_public_event_endpoint_no_id_leak` | `GET /api/public/events/{join_code}` body contains no key equal to `event.id`; schema declares no `id` field |
| `test_public_event_endpoint_fields` | Response carries `frictionless_join`, `phase`, `requests_open`, `collection_code == event.code` |
| `test_sse_submit_via_join_code_publishes_event_code` | `submit_request` reached by `join_code` calls `publish_event(event.code, ...)` so a `/stream/{join_code}` subscriber receives it |
| `test_dj_get_event_unchanged` | `GET /api/events/{collection_code}` (DJ) still returns `EventOut` with `id` (authed) — no regression |
| `test_collect_page_endpoints_unchanged_by_collection_code` | All collect endpoints still resolve normally via collection code |

### Frontend (vitest — extend `app/join/[code]/__tests__/page.test.tsx`)

| Test | Asserts |
|---|---|
| `join loads via getPublicEvent` | Page mounts with mocked `getPublicEvent`, renders queue/CTA |
| `frictionless path skips gate` | `frictionless_join: true` → `ensureGuestName` called, no `NicknameGate` |
| `non-frictionless renders gate` | `frictionless_join: false` → `NicknameGate` renders |
| `phase banner links to collection_code` | Pre-event banner href is `/collect/{collection_code}`, not the join_code |
| `no getEvent/EventOut on join page` | Join page no longer calls the id-leaking `getEvent` |

## Rollout

- **No migration** — no schema change (resolver + one read endpoint + frontend). `alembic check` stays green (no model drift).
- Local CI (mirrors `ci.yml`): backend ruff check / ruff format --check / bandit / pip-audit / pytest ≥85%; frontend lint / `tsc --noEmit` / vitest; bridge + bridge-app `tsc --noEmit` / vitest.
- Branch `fix/dual-code-routing-382` → PR into `main` → remote CI green → squash-merge.
- Deploy: `./deploy/deploy.sh` (no nginx change, no migration).
- Optional "eat the dogfood" for a live LAN test before production.

### Smoke (the real share link)

1. Open `/join/{join_code}` (the DJ's actual link) in an incognito tab on a phone.
2. Frictionless ON → lands on search with an auto-name; OFF → `NicknameGate` renders.
3. Queue populates; cast a vote; submit a song; confirm SSE updates the queue live.
4. Verify email from the identity bar; clear cookies; reopen the link; re-verify → guest-merge restores requests/votes.
5. Confirm DevTools network has **no** response body containing the integer `event.id`.

## Risk register

| Risk | Mitigation |
|---|---|
| Canonical resolver lets a `join_code` hit collect endpoints | Collect gates (`require_email_verified`, `require_verified_human`) are unchanged — resolution ≠ authorization. `test_collect_submit_still_email_gated_via_join_code` pins it. |
| Exposing `collection_code` to live guests via `getPublicEvent` | Acceptable — collection code is the *more* public, long-lived share code; the collect page stays auth-gated. |
| New endpoint duplicates some `EventOut` fields | Intentional guest-safe projection (id hygiene); narrow, read-only, low maintenance. |
| Missed a `publish_event` site still keying URL code | Test asserts the submit path; grep-audit all call sites during implementation. |
| `get_event` still leaks `id` to DJ | Out of scope — DJ is authenticated and trusted; guest path no longer touches it. |
| Future endpoint wires the wrong resolver | `test_public_code_resolver_accepts_both` + serializer-hygiene test are the drift guards. |

## Sources

- #324 design (`docs/superpowers/specs/2026-05-20-collection-vs-live-event-codes-design.md`) — established the two-code model and the (incomplete) routing audit this fix completes.
- [OWASP — Insecure Direct Object Reference prevention](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html) — keep internal surrogate keys (`event.id`) off public serializers.

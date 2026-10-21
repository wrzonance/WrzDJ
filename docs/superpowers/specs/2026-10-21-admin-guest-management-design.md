# Admin Guest Management

**Status:** design for issue #862. Approved by thewrz on 2026-10-21.

## Intent

Admins can manage DJ accounts and events, but not the guests who join events. A guest is the
anonymous identity in `guests` (server cookie token, ThumbmarkJS fingerprint, optional verified
email, optional nickname) plus one `guest_profiles` row per event joined. When a guest is
griefing, spamming, or asks to be forgotten, the only tool today is psql. Admins also cannot see
the two abuse signals WrzDJ already collects: Turnstile passes and fingerprint collisions.

## Goals

- One page, **Admin → Guests**, that lists every guest identity with its verification state,
  abuse signals, dates, and event memberships.
- Edit a guest's per-event nicknames and revoke a verified email.
- Delete a guest (cleanup and right-to-be-forgotten, not a ban).
- Record Turnstile passes per guest so "human" is a real, stored signal.

## Non-goals

- Per-event guest moderation from the DJ dashboard (DJ-facing, separate threat model).
- Bulk actions. One guest at a time is enough for the moderation volume today.
- Exposing `guests.nickname`. No application code writes that column (builder check,
  2026-10-21); the name a guest is known by is `guest_profiles.nickname`, per event. The page
  derives a display name from the newest profile and edits profiles directly.
- Blocking a deleted guest from coming back. The browser keeps its `wrzdj_guest` cookie and
  `identify_guest` mints a fresh row on the next visit. A block list is a separate feature.
- Showing or editing raw fingerprint components or the user agent string.

## Anti-goals

- Exposing the plaintext verified email by default. It is encrypted at rest for a reason; the
  table shows a masked form (`a***@example.com`).
- Storing any IP-derived data. `docs/RECOVERY-IP-IDENTITY.md` still holds.
- Inventing a "human score". Cloudflare Turnstile returns pass/fail only. The UI shows what was
  recorded: pass count and last pass time.

## Data model change (Alembic 074)

Two columns on `guests`:

| column | type | default | written by |
| --- | --- | --- | --- |
| `human_verified_at` | `DateTime` nullable | `NULL` | `POST /api/public/guest/verify-human` on Turnstile success |
| `human_verify_count` | `Integer` not null | `0` | same endpoint, `+1` per success |

Downgrade drops both. Existing rows read as "never verified", which is honest: nothing was
recorded before this change.

## Backend

New module `app/services/admin_guests.py` (keeps `services/admin.py` under budget) and new
schemas in `app/schemas/admin_guest.py`. Routes live in `app/api/admin.py` next to the user
routes, admin-only via `get_current_admin`, rate-limited like their user counterparts.

### `GET /api/admin/guests`

Query: `page` (1..1000), `limit` (1..100), `filter` in `all | verified | unverified | shared`,
`q` (substring of any per-event nickname, case-insensitive, literal `%`/`_`, max 30 chars).
Returns the shared `PaginatedResponse` whose items are `AdminGuestOut`:

```
id, nickname (newest non-null guest_profiles.nickname, or None),
browser (e.g. "Safari · iOS", parsed with guest_identity._parse_ua),
email_verified: bool, email_masked: str | None, email_verified_at,
human_verified_at, human_verify_count,
fingerprint_short: str | None (first 12 hex chars), fingerprint_shared_with: int
  (other guests with the same hash; 0 = unique; None hash → 0),
created_at, last_seen_at,
event_count, request_count,
events: [ { event_id, code, name, nickname, submission_count, joined_at } ]
```

Ordering: `last_seen_at desc`. The collision count is one grouped subquery over
`fingerprint_hash`, not N+1. Event memberships are loaded for the page's guests in one query.

### `PATCH /api/admin/guests/{id}`

Body `AdminGuestUpdate`: `revoke_email: bool = False` (sets `verified_email`, `email_hash`,
`email_verified_at` to `NULL`). 404 when missing. Returns the refreshed `AdminGuestOut`.

### `PATCH /api/admin/guests/{id}/events/{event_id}`

Body `AdminGuestProfileUpdate`: `nickname: str | None` (max 30, whitespace-trimmed; `""` or
`null` clears). 404 when the guest has no profile on that event. 409 `"Nickname already taken in
this event"` when the per-event case-insensitive uniqueness index rejects it. Returns the
refreshed `AdminGuestOut`.

### `DELETE /api/admin/guests/{id}`

204. In one transaction: `requests.nickname` set `NULL` for the guest's requests (the
per-submission name snapshot the DJ and public lists display), the guest's `guest_profiles`
rows deleted, then the guest. `requests` and `request_votes` keep their rows with `guest_id` set
`NULL` by the existing FK; verification codes cascade. 404 when missing.

### Tests

`tests/test_admin_guests.py`: list shape, each filter, search, collision count, masked email,
browser parse, revoke email, per-event nickname set / clear / conflict 409, delete cascade
semantics including the request-name scrub, 403 for DJ and pending, 401 anonymous, 404s. `tests/test_verify_human_endpoint.py` gains an assertion that a
Turnstile success stamps `human_verified_at` and increments `human_verify_count`. Coverage gate
stays at 85.

## Frontend

Operate mode. The page inherits the admin console's existing vocabulary exactly: `container`,
`header`, `tabs`/`tab`, `admin-table`, `badge`, `modal`, `btn`, `pagination`, `HelpSpot`
onboarding. No new fonts, no new colours outside the existing tokens.

### `/admin/guests`

- Nav: "Guests" after "Events" in `app/admin/layout.tsx`.
- Header "Guest Management" + total count.
- Filter tabs: All / Verified / Unverified / Shared fingerprint. Search input for nickname,
  debounced 300 ms, resets page to 1.
- Table columns: Guest · Email · Human · Fingerprint · Joined · Last seen · Events · Actions.
  - Guest: nickname in `--color-nickname-accent` (or "No name yet" in secondary), `#id` and
    browser label beneath in secondary small text.
  - Email: `badge` success-subtle "Verified" + masked address + verified date; or `badge`
    surface-raised "Unverified".
  - Human: "3 passes · 2h ago" with a success tint; or "Never" in tertiary.
  - Fingerprint: short hash in tabular monospace plus `badge`: success-subtle "Unique",
    warning-subtle "Shared ×N", or surface "None" when no hash.
  - Events: count as a button that toggles an inline detail row listing memberships (code, name,
    per-event nickname, submissions, joined). No modal for reading.
  - Actions: Edit, Delete (`btn-sm`).
- Empty state per filter: "No guests match this filter." with the active filter named.
- Loading: existing `loading` block. Errors: existing danger text block.
- Edit modal (same shape as Users): one nickname input per event membership (labelled by event
  name), "Revoke verified email" checkbox shown only when verified, Save/Cancel. Save issues one
  request per changed field; a 409 is shown next to the offending input and the modal stays
  open.
- Delete: `window.confirm` with the consequence sentence: "Delete guest "name"? Their event
  memberships are removed; their requests and votes stay but become anonymous."

### Code

- `lib/api.ts`: `getAdminGuests(page, limit, filter, q)`, `updateAdminGuest(id, data)`,
  `updateAdminGuestProfile(id, eventId, data)`, `deleteAdminGuest(id)`; `lib/api-types.ts`
  exports `AdminGuest`, `AdminGuestEvent`, `AdminGuestUpdate`, `AdminGuestProfileUpdate` from
  the regenerated OpenAPI types.
- `app/admin/guests/page.tsx` ≤ 400 lines; the table row and the edit modal are their own
  components in `app/admin/guests/components/`.
- `lib/format-time.ts` gains `formatRelativeAge(iso, now)` ("2h ago", "3d ago") if nothing
  equivalent exists; reuse if it does.
- Tests mirror `app/admin/users/__tests__/page.test.tsx`: render, filters, search, expand row,
  edit submit, delete confirm, empty state.

## Calls made after the builder check (2026-10-21)

- Nickname means the per-event profile nickname; the unused global column is not exposed.
- Delete scrubs `requests.nickname` so the confirm copy is true.
- Delete is not a ban; a block list is out of scope and noted under non-goals.

## Left to the builder

- Exact copy of the help spots.
- Whether the relative-age helper lives in `format-time.ts` or a sibling file.
- Responsive stacking of the table under 720 px (follow whatever the Users table does).

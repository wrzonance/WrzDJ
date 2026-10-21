# Recovery: How to Restore IP-Based Guest Identity

This document is the recovery anchor for the IP-identity removal. It exists so that if the cookie + ThumbmarkJS approach proves insufficient at some future date — or if a regulatory / forensic / abuse-defense need re-emerges that genuinely requires storing the client IP alongside guest data — the restoration is mechanical rather than archaeological.

## Why this was removed

Prior to commit `9f4e4065eebdfb01f43e214785a3c898cf81c212` (PR #266), the codebase identified guests by *both* a cookie/fingerprint pair (`Guest.token` + `Guest.fingerprint_hash`) and the raw client IP (`client_fingerprint` columns on `requests`, `request_votes`, `guest_profiles`, plus `Guest.ip_address`). The IP path was a fallback for "orphan" rows from the pre-cookie era.

In production this caused a real bug: any two guests behind a shared NAT (a venue WiFi, a household, an office, the local Docker dev-proxy) inherited each other's nicknames because `collect_service.get_profile()` matched by `client_fingerprint` (raw IP) when the cookie's `guest_id` had no profile row yet. A second device joining an event would be greeted as "Hi, alpha!" — alpha being the first guest from that NAT.

The IP-as-identity path was always a leaky abstraction: rate-limit collisions behind NAT, dedup unique constraints that had to be progressively dropped (PRs #252, the request_votes constraint drop in PR `31f60e2`), and a confusing column name (`client_fingerprint` is *not* a fingerprint, it's an IP). Cookie-first identity (PR #254) made IP redundant; this change finishes that migration.

## What this codebase guarantees post-cleanup

- **Identity = `guest_id`.** The `guests` table row is the source of truth for guest identity. A server-issued HttpOnly cookie (`wrzdj_guest`) resolves it, with ThumbmarkJS browser fingerprint as the cookie-loss reconciliation fallback (`services/guests/identity.py`).
- **Guest identity does not persist IP addresses.** The guest, request, vote and profile models have no IP-derived identity columns, and the application does not log guest IPs.
- **IP use is ephemeral.** The slowapi rate limiter uses `core.rate_limit.get_client_ip()` as its in-memory bucket key; guest CAPTCHA verification also sends it to Turnstile as `remoteip`. Neither flow stores it as guest identity.
- **Submission caps are per-person, not per-IP.** Guests behind a shared NAT each get their own `submission_cap_per_guest`. This is intentional (see Risk Note #3 in the original plan).

## Restoration procedure

### Step 1: Choose a schema restoration plan

The historical removal is `039_drop_ip_columns.py`, whose parent is revision `038`.
Its `downgrade()` restores the old columns. The command below applies **only to an isolated
database already at revision `039`**, for example when reproducing the original change:

```
cd server
.venv/bin/alembic current   # must report 039 before the next command
.venv/bin/alembic downgrade 038
```

This reverses migration `039_drop_ip_columns.py`, restoring:

- `requests.client_fingerprint` (`String(64)`, nullable, indexed)
- `request_votes.client_fingerprint` (`String(64)`, nullable, indexed)
- `guest_profiles.client_fingerprint` (`String(64)`, nullable, indexed)
- `guest_profiles` unique constraint `(event_id, client_fingerprint)`
- `guests.ip_address` (`String(45)`, nullable)

On a current installation, `downgrade -1` reverses the latest migration, not this removal.
Downgrading all the way to `038` would also reverse every later migration. For an approved
restoration on the current schema, write a forward migration adapted from revision `039`'s
`downgrade()`, test it against a populated database copy, and verify model/schema agreement.
Adding columns cannot recover IP values that the original upgrade deleted.

### Step 2: Adapt the historical implementation

The merged removal is preserved in commit `9f4e4065`. Inspect that change as a reference:

```
git show 9f4e4065 -- server/app server/alembic/versions/039_drop_ip_columns.py
```

A blanket revert also undoes unrelated collection fixes from the same merged commit and conflicts
with later service moves. Implement only the approved behavior against the current modules. The
historical removal affected these symbols (paths below reflect that commit; guest identity now
lives in `services/guests/identity.py`):

- `core/rate_limit.py`: `get_client_fingerprint`, `mask_fingerprint`, `_fp_source`, `_fp_logger`, `MAX_FINGERPRINT_LENGTH`
- `services/vote.py`: `client_fingerprint` parameter on `_find_existing_vote`, `add_vote`, `remove_vote`, `has_voted`; the IP-based fallback branch in `_find_existing_vote`
- `services/request.py`: `client_fingerprint` parameter on `create_request`; the `get_requests_by_fingerprint` function
- `services/collect.py`: `fingerprint` parameter on `get_profile`, `upsert_profile`, `check_and_increment_submission_count`; the IP fallback in `get_profile`
- `services/email_verification.py`: `_link_orphan_profiles_to_guest` function and its call sites
- `services/guest_identity.py`: `ip_address` parameter on `identify_guest` and the `guest.ip_address = ...` assignment
- `api/votes.py`, `api/public.py`, `api/collect.py`, `api/events.py`, `api/guest.py`: all the `get_client_fingerprint(request)` call sites and `client_fingerprint == fingerprint` matching branches

### Step 3: Optional — frontend race-fix revert

The frontend race fix (NicknameGate awaiting `useGuestIdentity` ready signal) is *independent* of the IP-identity removal and stays correct regardless. Reverting it is unnecessary and not recommended. If you do want to revert it for some reason, look for the commit that modifies `dashboard/lib/use-guest-identity.ts` and `dashboard/components/NicknameGate.tsx`.

### Step 4: Confirm

```
cd server
.venv/bin/alembic check                                  # schema matches models
.venv/bin/pytest tests/test_no_ip_identity.py tests/test_no_ip_storage.py tests/test_no_ip_logging.py -v
.venv/bin/pytest -q
```

The three privacy suites assert the current no-IP-identity contract. An approved behavior change
needs corresponding boundary tests and an explicit update to that contract; retain checks for
unchanged privacy guarantees. `test_reversibility.py` existed in the original commit but is no
longer part of the suite.

## Files that need to change (frozen reference)

This list is the audit trail. If you find a file in the post-cleanup codebase that is *not* in this list and references `client_fingerprint`, `get_client_fingerprint`, `mask_fingerprint`, `_fp_logger`, or `ip_address` in a non-trivial way, treat it as a bug.

### Modified files (touched by both removal and restoration)

| File | What removal changed | What restoration brings back |
|---|---|---|
| `server/app/core/rate_limit.py` | Removed `get_client_fingerprint`, `mask_fingerprint`, `_fp_source`, `_fp_logger`, `MAX_FINGERPRINT_LENGTH` | All five symbols restored |
| `server/app/models/request.py` | Removed `client_fingerprint` Mapped column | Mapped column re-added |
| `server/app/models/request_vote.py` | Removed `client_fingerprint` Mapped column | Mapped column re-added |
| `server/app/models/guest_profile.py` | Removed `client_fingerprint` Mapped column + the `(event_id, client_fingerprint)` unique constraint | Both re-added |
| `server/app/models/guest.py` | Removed `ip_address` Mapped column | Re-added |
| `server/app/services/collect.py` | `get_profile`, `upsert_profile`, `check_and_increment_submission_count` lost `fingerprint` param | Param restored, IP-fallback branch in `get_profile` restored |
| `server/app/services/vote.py` | All four functions lost `client_fingerprint` param | Restored, with the `else` branch in `_find_existing_vote` |
| `server/app/services/request.py` | `create_request` lost param, `get_requests_by_fingerprint` deleted | Restored |
| `server/app/services/email_verification.py` | `_link_orphan_profiles_to_guest` deleted; `mask_fingerprint(...)` log calls removed | Both restored |
| `server/app/services/guest_identity.py` | `identify_guest` lost `ip_address` param; `guest.ip_address = ...` assignment removed | Both restored |
| `server/app/api/votes.py` | `get_client_fingerprint` import + calls removed; 401-on-no-guest branch added | Reverted |
| `server/app/api/public.py` | Lines ~237-319: fingerprint variable + IP-fallback `else` branches removed in `check_has_requested` and `get_my_requests` | Reverted |
| `server/app/api/collect.py` | Lines ~131-430: fingerprint variable + IP-fallback branches removed in `get_profile`, `set_profile`, `my_picks`, `submit`, `vote`; `mask_fingerprint(...)` log lines removed | Reverted |
| `server/app/api/events.py` | `client_fingerprint=get_client_fingerprint(request)` kwarg removed from `create_request` call | Reverted |
| `server/app/api/guest.py` | `ip_address=ip_address` kwarg removed from `identify_guest` call | Reverted |
| `CLAUDE.md` | Security section paragraph about `client_fingerprint` export-scrubbing replaced with single sentence | Reverted |

### New files (created by removal — safe to delete on restoration)

- `server/alembic/versions/039_drop_ip_columns.py` — the migration; **do not delete or rewrite** an applied revision
- `server/tests/test_no_ip_identity.py` — assertions invert after restore; delete or invert
- `server/tests/test_no_ip_storage.py` — same
- `server/tests/test_no_ip_logging.py` — same
- `server/tests/test_reversibility.py` — historical file, no longer present
- `docs/RECOVERY-IP-IDENTITY.md` — keep, but update the "post-cleanup" section to reflect that IP-identity is back in active use

### Modified test files

- `server/tests/conftest.py` — `test_guest` fixture lost `ip_address=...` kwarg; restore on revert
- `server/tests/test_voting.py`, `test_collect.py`, `test_requests.py` — `add_vote(db, req.id, "192.168.1.1")` style calls were rewritten to `add_vote(db, req.id, guest_id=...)`; restore old call sites if reverting
- `dashboard/components/__tests__/NicknameGate.test.tsx` — race tests added; harmless on restore

## When would you actually restore this?

Probably never. But if any of these come up:

1. **A regulator / venue contract requires per-IP audit logs.** Restore Step 1 only (the schema). Add a write-only audit table that captures IP at submit time. Don't restore the matching/fallback paths — that's what caused the original bug.
2. **The cookie+fingerprint approach is provably failing in production** — e.g., ThumbmarkJS becomes unavailable, or a major browser disables the wrzdj_guest cookie path. Restore Step 1 + Step 2, but only after exhausting alternatives (different fingerprint library, server-side identity providers, OAuth-style guest auth).
3. **Investigation of a specific incident.** The application does not retain guest IP logs to query.
   Use existing guest/request audit identifiers. Any new diagnostic capture requires a separate,
   scoped design; restoring IP-based identity reintroduces the original shared-NAT failure.

In all three cases, prefer surgical re-introduction over a wholesale revert.

## Quick command reference

| Goal | Command |
|---|---|
| See what was removed | `git show 9f4e4065 --stat` |
| Verify schema is currently IP-free | `cd server && .venv/bin/alembic current && .venv/bin/alembic check` |
| Verify the guest privacy contract | `cd server && .venv/bin/pytest tests/test_no_ip_identity.py tests/test_no_ip_storage.py tests/test_no_ip_logging.py -v` |
| Inspect the historical schema restoration | Read `server/alembic/versions/039_drop_ip_columns.py:downgrade` |
| Plan restoration on the current schema | Add a reviewed forward migration and matching model/API changes; validate a populated database copy |

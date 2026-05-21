# Collection vs Live Event Codes — Design

**Status:** Draft for approval
**Author:** thewrz
**Date:** 2026-05-20
**Related incident:** Production audit of event ELZ2G2 ("Home School Prom 2026") on 2026-05-20.

## Background

The production audit of ELZ2G2 surfaced two problems that share a common solution surface:

1. **Vote pumping via cookie cycling.** One iPhone (UA: iOS 18.6, fingerprint `1bc97a8e418edc278d110b044baa42f4`) created 23 ephemeral `guest_id` rows over 7 days and cast 241 votes (66% of all event votes) without verifying an email. The DB unique constraint `uq_request_vote_guest (request_id, guest_id)` is trivially bypassed by regenerating the guest cookie. The mitigating gate (Turnstile-issued `wrzdj_human` cookie) was not enforced because `system_settings.human_verification_enforced = false` (soft mode). The vote endpoint also has no email-verification dependency.

2. **Mass auto-rejection bug.** 142 of 154 ELZ2G2 requests were silently auto-rejected by `poll_tidal_collection_removals` across three poll cycles (May 19 13:09, May 20 05:02–05:03, May 20 22:02–22:07). Root cause: `get_playlist_tracks` returns `[]` on any exception, making "Tidal API failed" indistinguishable from "playlist is genuinely empty". The poller then iterates synced requests, finds none of their track IDs in the empty set, and rejects all of them.

The user has also confirmed a design direction that has been latent in the codebase: **collection-phase URLs need to be friction-heavy (email + Turnstile), live-event URLs need to be friction-free.** Currently both phases share a single `event.code`, so any QR code or shared URL points at both phases simultaneously.

## Goals

- **Split event identity into two codes per event.** `event.code` (existing) is the collection code; a new `event.join_code` is the live-event/QR code. Same event row, two distinct codes.
- **Harden the collection page** so vote pumping by cookie cycling becomes structurally impossible: hard human verification (Turnstile) AND email verification on every mutating endpoint.
- **Keep the live event frictionless.** The join code path is unchanged in behavior — no Turnstile, no email, just a guest cookie + nickname.
- **Fix the Tidal poller bug** so an API failure or partial response never triggers a mass rejection again.
- **Recover ELZ2G2 data** by restoring the 142 bug-rejected requests and removing the lone surviving pumped vote.

## Non-goals

- Changing the live-event join experience (cookie, nickname, voting model) in any way other than the URL `{code}` parameter source.
- Adding proof-of-personhood (biometrics, social vouching) — accepted as overkill for a music-request app.
- TOTP / authenticator-app verification — would kill the venue use case.
- Per-event override of `human_verification_enforced` — deferred.
- HMAC secret rotation tooling — deferred (document procedure only).
- Bridge resolving events by `join_code` — bridge stays on `event.code`.
- Migrating non-ELZ2G2 events' data (no other events have inflated `vote_count` rows from the same bug pattern).

## Schema

### Migration

Add `events.join_code` as a NOT NULL, UNIQUE 6-character string column. Backfill existing events by generating a fresh code per event using the existing `_generate_code()` helper, with a uniqueness check that scans both `code` and `join_code` columns to prevent any value being reused as the other type.

```python
# server/alembic/versions/XXX_add_event_join_code.py
def upgrade() -> None:
    op.add_column('events', sa.Column('join_code', sa.String(10), nullable=True))
    conn = op.get_bind()
    events = conn.execute(sa.text("SELECT id FROM events WHERE join_code IS NULL")).fetchall()
    for (event_id,) in events:
        while True:
            candidate = _generate_code()
            exists = conn.execute(
                sa.text("SELECT 1 FROM events WHERE code = :c OR join_code = :c"),
                {"c": candidate},
            ).first()
            if not exists:
                conn.execute(
                    sa.text("UPDATE events SET join_code = :c WHERE id = :id"),
                    {"c": candidate, "id": event_id},
                )
                break
    op.alter_column('events', 'join_code', nullable=False)
    op.create_index('ix_events_join_code', 'events', ['join_code'], unique=True)

def downgrade() -> None:
    op.drop_index('ix_events_join_code', 'events')
    op.drop_column('events', 'join_code')
```

### Column semantics after migration

| Column | Role | Used by |
|---|---|---|
| `events.code` | Collection code (gated) | `/collect/{code}`, `/api/public/collect/{code}/*`, DJ-facing `(dj)/events/{code}` page, bridge integration |
| `events.join_code` | Live join / QR code (frictionless) | `/join/{join_code}`, `/api/public/events/{join_code}/*`, `/e/{join_code}/display`, `/kiosk-link/{join_code}` |

### Code generation helper

```python
# server/app/services/event.py (additions)

def _generate_unique_event_code(db: Session) -> str:
    """Generate a code unique across both `code` and `join_code` columns."""
    while True:
        candidate = _generate_code()
        exists = (
            db.query(Event)
            .filter(or_(Event.code == candidate, Event.join_code == candidate))
            .first()
        )
        if not exists:
            return candidate
```

Existing code-generation paths route through this helper for both columns.

## Route resolution

### Lookup helpers (single source of truth)

```python
# server/app/services/event.py

def get_event_by_collection_code(db: Session, code: str) -> Event | None:
    return db.query(Event).filter(Event.code == code).first()

def get_event_by_join_code(db: Session, join_code: str) -> Event | None:
    return db.query(Event).filter(Event.join_code == join_code).first()
```

Audit every `Event.code ==` filter in `server/app/api/` and route each through the appropriate helper.

### Routing matrix

| Path | Resolves by | Gated? | Guest-visible (QR)? |
|---|---|---|---|
| `/collect/{code}` (frontend) | `events.code` | Hard human + email | No |
| `/api/public/collect/{code}/*` (mutating) | `events.code` | Hard human + email | No |
| `/api/public/collect/{code}` (preview) | `events.code` | None | No |
| `/api/public/collect/{code}/leaderboard` | `events.code` | None | No |
| `/join/{join_code}` (frontend) | `events.join_code` | Unchanged | Yes |
| `/api/public/events/{join_code}/*` | `events.join_code` | Unchanged | Yes |
| `/e/{join_code}/display` | `events.join_code` | Unchanged | Yes |
| `/kiosk-link/{join_code}` | `events.join_code` | Unchanged | Yes |
| `/(dj)/events/{code}` | `events.code` | DJ auth | DJ-only |
| Bridge ingestion | `events.code` | Bridge key | DJ-only |

### QR generation

The QR target URL switches from `event.code` to `event.join_code`:

```python
qr_target = f"{PUBLIC_URL}/join/{event.join_code}"
```

The DJ dashboard exposes both codes as separate copy buttons with distinct labels (Collection vs Live Join).

### DJ-side bridge

Bridge uses `events.code` (the collection code) unchanged. No bridge code change required.

## Collection-page gating

### New dependency: `require_email_verified`

Chains the existing `require_verified_human` (hard mode) and adds an email-verification check.

```python
# server/app/api/deps.py

def require_email_verified(
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_verified_human),
) -> int:
    guest = db.get(Guest, guest_id)
    if guest is None or guest.verified_email is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "email_verification_required"},
        )
    return guest_id
```

### Switching collect endpoints to hard mode

Replace `require_verified_human_soft` with `require_email_verified` on every mutating collect endpoint AND on personal-profile read endpoints. Collect endpoints are hard-gated regardless of the global `human_verification_enforced` flag — there is no soft-mode fallback for collect.

| Method | Endpoint | Email | Turnstile (hard) |
|---|---|---|---|
| GET | `/api/public/collect/{code}` (event preview) | — | — |
| GET | `/api/public/collect/{code}/leaderboard` | — | — |
| GET | `/api/public/collect/{code}/profile` | — | required |
| GET | `/api/public/collect/{code}/profile/me` | required | required |
| POST | `/api/public/collect/{code}/profile` | required | required |
| POST | `/api/public/collect/{code}/requests` | required | required |
| POST | `/api/public/collect/{code}/vote` | required | required |
| POST | `/api/public/collect/{code}/enrich-preview` | required | required |
| GET | `/api/public/collect/{code}/...search` | required | required |

### OTP hardening

Audit-driven changes to `services/email_verification.py` (or wherever OTP verify lives):

1. **Expiry: 5 minutes.** Reduce existing expiry (currently unknown — confirm during implementation) to 5 min.
2. **Attempts: hard cap at 5.** Production audit found `attempts = 0` across all 18 codes — the counter is not being incremented on bad submissions. Fix: increment `attempts` on every failed `verify_email_code` call; reject when `attempts >= 5` with `{"code": "otp_locked"}`.
3. **User-enumeration safe.** `POST /api/public/guest/verify/request` returns identical `{"sent": true}` response shape whether the email already exists on another `guest_id` or is brand new. The backend silently reconciles (see next item).
4. **Email-uniqueness reconciliation.** On `verify/confirm`, if `Guest.email_hash` already exists on a different `guest_id`:
   - Reissue the canonical `guest_id`'s `wrzdj_guest` cookie on the response.
   - Reissue the `wrzdj_human` cookie bound to the canonical `guest_id`.
   - Delete the orphan ephemeral guest row.
   - Return success without disclosing the merge.

   This is the structural defeat of cookie cycling: a verified email maps to exactly one immutable `guest_id` across all future cookie clears.

### Turnstile per-action labels

Use distinct `action` strings (≤32 chars) on each Turnstile widget instance:
- `collect_otp_send` — fresh per OTP-request call
- `collect_submit` — collect page session bootstrap before submit
- `collect_vote` — collect page session bootstrap before vote

Cloudflare uses these for analytics, and they let us tune challenge thresholds per action later.

### Siteverify enforcement

Confirm `services/turnstile.py` treats `timeout-or-duplicate` from Cloudflare siteverify as a hard failure (rejects the token). If it currently passes through, fix it.

### Cookie flags

Confirm `wrzdj_human` is issued with `Secure; HttpOnly; SameSite=Lax`. Lax (not Strict) because the cookie must survive top-level navigation from QR scans and external links.

### Frontend changes

| File | Change |
|---|---|
| `dashboard/app/collect/[code]/page.tsx` | Wrap mutating UI in `<EmailGate>` block; reuse existing `useHumanVerification` hook for the Turnstile half |
| `dashboard/components/EmailGate.tsx` | NEW — full-screen blocker, two stages (email entry + OTP entry), reuses `EmailVerification.tsx` internals |
| `dashboard/lib/api.ts` | Extend `withHumanRetry` → `withVerificationRetry` (handles both 403 codes: `human_verification_required` and `email_verification_required`) |
| `dashboard/lib/useEmailVerified.ts` | NEW — hook that fetches `/collect/{code}/profile/me`, returns `{verified, refresh}` |

### Page-load state machine

```
[Page mount]
    │
    ▼
[1. Fetch GET /collect/{code} (event preview, no gate)]
    │
    ▼
[2. useHumanVerification: Turnstile bootstrap → wrzdj_human cookie]
    │ on fail/escalate: visible Turnstile widget
    ▼
[3. Fetch GET /collect/{code}/profile/me (require_email_verified)]
    │ 403 email_verification_required → render EmailGate
    │ 200 → guest is verified
    ▼
[4. Render full collect UI: leaderboard, submit, vote, profile]
```

### Failure UX

| Failure | User-facing message |
|---|---|
| Turnstile network/blocked | "Verification challenge failed. Refresh and try again." |
| OTP send rate-limited | "Too many attempts. Wait 60s." |
| OTP code expired | "Code expired. Request a new one." |
| OTP code wrong | "Code didn't match. Try again. ({attempts}/5)" |
| OTP locked (5 attempts) | "Too many wrong codes. Request a new code." |
| Email collision (different cookie) | Silently rebound. No user-visible error. |

## Live-page gating

**No change.** The live join experience (`/join/{join_code}`, `/api/public/events/{join_code}/*`) keeps exactly its current behavior: guest cookie + optional nickname, no Turnstile, no email, no human cookie required. The only change is the URL parameter resolves from `events.join_code` instead of `events.code`.

## Tidal poller hardening

### Failure-mode distinction in `get_playlist_tracks`

```python
class TidalFetchError(Exception):
    """Raised when Tidal playlist tracks can't be fetched (vs. genuinely empty)."""


def get_playlist_tracks(db: Session, user: User, playlist_id: str) -> list:
    session = get_tidal_session(db, user)
    if not session:
        raise TidalFetchError("No active Tidal session for user")

    try:
        playlist = session.playlist(playlist_id)
        all_tracks = []
        offset = 0
        page_size = 100
        while True:
            page = playlist.tracks(limit=page_size, offset=offset)
            if not page:
                break
            all_tracks.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return all_tracks
    except Exception as e:
        logger.error("Tidal playlist fetch failed: %s: %s", type(e).__name__, e)
        raise TidalFetchError(str(e)) from e
```

Two structural changes:
- Throws `TidalFetchError` on any failure (no silent `[]`).
- Paginates through all tracks (handles playlists >100; today's truncation at 100 is a latent bug).

### Safe abort in `poll_tidal_collection_removals`

```python
def poll_tidal_collection_removals(db: Session, event: Event) -> int:
    if not event.tidal_collection_playlist_id:
        return 0

    user = event.created_by
    try:
        playlist_tracks = get_playlist_tracks(db, user, event.tidal_collection_playlist_id)
    except TidalFetchError as e:
        logger.warning(
            "Tidal collection poll aborted for event %s: %s. NOT marking any requests rejected.",
            event.code, e,
        )
        log_activity(db, level="warn", source="tidal_poll",
                     message=f"Poll aborted: {e}", event_code=event.code)
        return 0

    current_ids = {str(t.id) for t in playlist_tracks}

    synced = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.submitted_during_collection == True,  # noqa: E712
            Request.tidal_collection_track_id.isnot(None),
            Request.status != RequestStatus.REJECTED.value,
        )
        .all()
    )

    # Suspicious-empty guard
    if not current_ids and synced:
        logger.error(
            "Tidal collection poll: playlist returned 0 tracks but %d synced requests exist for event %s. "
            "Suspecting API issue, NOT rejecting.",
            len(synced), event.code,
        )
        log_activity(db, level="warn", source="tidal_poll",
                     message=f"Empty playlist with {len(synced)} synced rows; rejection sweep skipped",
                     event_code=event.code)
        return 0

    candidate_rejections = [
        req for req in synced if req.tidal_collection_track_id not in current_ids
    ]

    # Mass-rejection cap (defense in depth)
    if len(candidate_rejections) > len(synced) * 0.50 and len(candidate_rejections) > 5:
        logger.error(
            "Tidal collection poll: refused to reject %d/%d for event %s (>50%% threshold)",
            len(candidate_rejections), len(synced), event.code,
        )
        log_activity(db, level="error", source="tidal_poll",
                     message=f"Aborted mass rejection: would reject {len(candidate_rejections)}/{len(synced)}",
                     event_code=event.code)
        return 0

    for req in candidate_rejections:
        req.status = RequestStatus.REJECTED.value

    count = len(candidate_rejections)
    if count > 0:
        db.commit()
        rejected_ids = [r.id for r in candidate_rejections]
        logger.info("Tidal poll: rejected %d removed track(s) for event %s", count, event.code)
        log_activity(db, level="info", source="tidal_poll",
                     message=f"Auto-rejected {count} requests (IDs: {rejected_ids[:20]})",
                     event_code=event.code)

    return count
```

Three new safety properties:
1. `TidalFetchError` → abort, no mass-reject.
2. Suspicious-empty guard: playlist returned 0 tracks while ≥1 synced request exists → abort.
3. Mass-rejection cap: >50% of synced rows in one cycle → abort.

All three paths write to `activity_log` so the DJ can see what the poller did and didn't do.

## ELZ2G2 data recovery

Run as a one-shot SQL script after the deploy completes and the Tidal poller fix is live. Archived in `deploy/scripts/recovery-elz2g2-2026-05-20.sql`.

```sql
BEGIN;

CREATE TEMP TABLE elz2g2_recovery AS
SELECT id, song_title, artist, status, updated_at, tidal_collection_track_id
FROM requests
WHERE event_id = 15
  AND status = 'rejected'
  AND (
    updated_at BETWEEN '2026-05-19 13:09:00' AND '2026-05-19 13:10:00'
    OR updated_at BETWEEN '2026-05-20 05:02:00' AND '2026-05-20 05:04:00'
    OR updated_at BETWEEN '2026-05-20 22:02:00' AND '2026-05-20 22:08:00'
  );

-- Expect ~142 rows
SELECT COUNT(*), MIN(updated_at), MAX(updated_at) FROM elz2g2_recovery;

UPDATE requests
SET status = 'new', updated_at = NOW()
WHERE id IN (SELECT id FROM elz2g2_recovery);

-- Drop the lone surviving pumped vote on request #169 (Uptown Funk)
DELETE FROM request_votes WHERE id = 362;
UPDATE requests SET vote_count = vote_count - 1 WHERE id = 169;

-- Sanity check before commit
SELECT status, COUNT(*) FROM requests WHERE event_id = 15 GROUP BY status;

COMMIT;
```

## Rollout

### Sequence

1. Local CI: ruff check, ruff format --check, bandit, pip-audit, pytest with coverage ≥85; frontend lint, tsc --noEmit, vitest; bridge tsc + vitest; bridge-app tsc + vitest; `alembic upgrade head && alembic check`.
2. Push branch, PR, watch remote CI green.
3. Merge to main.
4. `ssh wrz-droplet` → `git fetch && git checkout main && git pull`.
5. `pg_dump` to `/backups/pre-collection-split-2026-05-XX.sql.gz`.
6. `./deploy/deploy.sh` runs the Alembic migration, which adds `join_code` and backfills.
7. Verify container health, smoke `/healthz`.
8. Run `deploy/scripts/recovery-elz2g2-2026-05-20.sql`.
9. Flip `UPDATE system_settings SET human_verification_enforced = true`.
10. Smoke test (next subsection).

### Smoke tests (post-deploy, pre-announcement)

1. Open `/collect/ELZ2G2` in incognito — EmailGate renders.
2. Submit a test email, get OTP, submit wrong code 5 times — locked.
3. Request new code, submit correct — full collect UI appears, submit a song.
4. Note `guest_id` in DevTools, clear cookies, return — re-verify email → confirm same `guest_id` reissued.
5. Open `/join/{new_join_code}` in incognito on a phone — no Turnstile, no email; vote works.
6. As DJ, remove a track from the Tidal collection playlist → wait 5 min → confirm only that track rejected, not all.
7. As DJ, force Tidal token expiry → wait 5 min → confirm `activity_log` has "Tidal collection poll aborted" with no mass rejection.

### Rollback

```bash
ssh wrz-droplet
cd ~/WrzDJ
git revert HEAD
./deploy/deploy.sh
.venv/bin/alembic downgrade -1
# Recovery SQL changes stay (harmless: requests at 'new' instead of 'rejected')
# Optional: UPDATE system_settings SET human_verification_enforced = false
```

## Testing

### Backend (pytest)

| Test | Asserts |
|---|---|
| `test_event_has_distinct_join_code` | New event has `code != join_code`, both unique, both 6 chars |
| `test_join_code_collision_resolved_in_backfill` | Migration backfills unique join_code despite random gen collisions |
| `test_collect_endpoint_403_without_human_cookie` | Mutating collect endpoint without cookie returns 403 `human_verification_required` even when global `enforced=false` |
| `test_collect_endpoint_403_without_email_verified` | Guest with valid human cookie but no `verified_email` → 403 `email_verification_required` |
| `test_join_endpoint_no_gate` | `POST /api/public/events/{join_code}/vote` works with no email and no human cookie |
| `test_otp_attempts_increment_and_block` | 5 wrong submissions → 6th rejected with `otp_locked`; `attempts` column reflects this |
| `test_otp_expiry_5_minutes` | Code created with `expires_at = now + 5min` |
| `test_otp_send_no_enumeration` | Sending OTP to existing email vs new email returns identical response shape |
| `test_email_reconciliation_rebinds_guest` | New guest cookie verifying existing email → rebound to canonical guest_id, orphan removed |
| `test_tidal_fetch_error_aborts_rejection` | Mocked Tidal API failure → poller returns 0 rejections, no status changes |
| `test_tidal_empty_playlist_with_synced_rows_aborts` | Playlist returns 0 tracks, synced_rows>0 → no rejections, activity_log entry |
| `test_tidal_mass_rejection_cap` | Mock 60% of tracks "removed" → no status changes, activity_log entry |
| `test_tidal_pagination_handles_150_tracks` | Playlist with 150 tracks → `get_playlist_tracks` returns all 150 |
| `test_qr_url_uses_join_code` | QR URL generation uses `event.join_code`, never `event.code` |

### Frontend (vitest)

| Test | Asserts |
|---|---|
| `EmailGate.test.tsx` | Renders when 403 `email_verification_required` returned from profile/me |
| `collect-page-blocks-without-email.test.tsx` | Submit/vote actions disabled until both gates pass |
| `join-page-still-frictionless.test.tsx` | `/join/{code}` page renders without Turnstile widget |
| `qr-uses-join-code.test.tsx` | DJ-side QR copy button shows join_code URL, not code URL |

## Risk register

| Risk | Mitigation |
|---|---|
| Alembic migration partial-applies on prod | Wrap backfill in single transaction; `pg_dump` immediately before deploy |
| `human_verification_enforced=true` blocks legit early ELZ2G2 users | Smoke-test the collect flow with two different test emails before flipping |
| `/join/{join_code}` URL leaks become spammable | Accept (same risk as today's `event.code` URL) |
| Bridge breaks after migration | No bridge change; bridge keeps resolving by `event.code` |
| Tidal hardening false-positive aborts | Acceptable: 0 auto-rejections beats 142 wrong auto-rejections; DJ can reject manually |
| Recovery SQL un-rejects something the DJ explicitly rejected | Audit confirms DJ has not manually rejected anything; the timestamps queried are exclusively from poll cycles |

## Sources informing best-practice decisions

- [Cloudflare Turnstile · widget configurations](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/)
- [Cloudflare Turnstile · concepts](https://developers.cloudflare.com/turnstile/concepts/widget/)
- [OWASP Email Validation and Verification Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP — Testing for Account Enumeration](https://owasp.org/www-project-web-security-testing-guide/v42/4-Web_Application_Security_Testing/03-Identity_Management_Testing/04-Testing_for_Account_Enumeration_and_Guessable_User_Account)
- [MDN — One-time passwords](https://developer.mozilla.org/en-US/docs/Web/Security/Authentication/OTP)
- [Authentica — Email OTP best practices](http://authentica.sa/en/email-otp-practices-for-secure-authentication/)
- [AWS — Secure One-Time Password Architecture](https://aws.amazon.com/blogs/messaging-and-targeting/build-a-secure-one-time-password-architecture-with-aws/)
- [Teleport — HTTP session management](https://goteleport.com/blog/http-session-best-practices/)
- [GitGuardian — HMAC secrets explained](https://blog.gitguardian.com/hmac-secrets-explained-authentication/)
- [arxiv — Sybil-resistant voting mechanism](https://arxiv.org/pdf/2407.01844)

# Human Verification on Public Guest Pages

WrzDJ guards `/join`, `/collect`, and `/kiosk-pair` against mass automated abuse and email-cost abuse using a layered approach. This doc explains how it works for future developers.

## Three mechanisms

1. **Session cookie (`wrzdj_human`)** — issued after a Cloudflare Turnstile check on page load. Required for all guest-mutating endpoints. 60-min sliding window. Refreshed on every successful gated call.
2. **Per-action Turnstile (OTP only)** — `POST /api/public/guest/verify/request` requires a fresh Turnstile token per email send. Burns Resend cost only with proven human input.
3. **IP-bound nonce (kiosk-pair only)** — `GET /api/public/kiosk/pair-challenge` issues a 10-second nonce, `POST /api/public/kiosk/pair` requires it. Tightened rate limit (3/min). No Turnstile because Pi has no input device for hard challenges.

## Cookie format

`wrzdj_human` is an HMAC-SHA256 signed JSON payload:

```
base64url(payload).base64url(hmac_sha256(payload, key))
```

Payload: `{"guest_id": <int>, "exp": <unix_ts>}`

Key sourced from `HUMAN_COOKIE_SECRET` env var (32 bytes, base64). Required in production. Dev auto-generates ephemeral key with startup warning — cookies don't survive a server restart in dev.

## Backend integration

- `app/services/human_verification.py` — sign/verify cookie helpers (`issue_human_cookie`, `verify_human_cookie`, `COOKIE_NAME`).
- `app/api/deps.py:require_verified_human` — hard dependency, raises 403 when invalid.
- `app/api/deps.py:require_verified_human_soft` — soft-mode wrapper, reads `SystemSettings.human_verification_enforced`. Use this during rollout.
- `app/api/guest.py:verify_human` — bootstrap endpoint that validates Turnstile and issues cookie.

Apply the dependency:

```python
from app.api.deps import require_verified_human_soft

@router.post("/some-mutating-endpoint")
def my_handler(
    ...,
    _human: int | None = Depends(require_verified_human_soft),
):
    ...
```

## Frontend integration

- `lib/turnstile.ts` — script loader + site-key cache.
- `lib/useHumanVerification.ts` — React hook that runs Turnstile in `interaction-only` mode on mount and POSTs to `/api/public/guest/verify-human`.
- `lib/api.ts:withHumanRetry` — fetch wrapper that catches 403 + `detail.code === 'human_verification_required'`, calls `reverify()`, retries once.
- `lib/useHumanVerification.ts:reverify` — resolves only once verification completes and the `wrzdj_human` cookie is issued (rejects with `HumanVerificationFailedError` on terminal failure); never resets a challenge that is already in flight. `withHumanRetry` relies on this contract, and surfaces a typed `HumanVerificationRequiredError` when the retried request is still rejected (#419).

Page integration pattern:

```tsx
const { state, reverify, widgetContainerRef } = useHumanVerification();

await api.someMutatingCall(args, reverify);

return (
  <div>
    {/* Hidden widget container, only visible when Cloudflare escalates */}
    <div ref={widgetContainerRef} style={{ display: state === 'challenge' ? 'block' : 'none' }} />
  </div>
);
```

## Rollout

- **Phase 1** (deploy): `human_verification_enforced=False` on `system_settings`. Soft-mode logs warnings on missing cookie but allows requests through. Frontend bootstrap deployed in same release.
- **Phase 2** (+7 days): Admin flips `human_verification_enforced=True` from the admin Settings page. Endpoint dependency starts returning 403. All live users have valid cookies (frontend has been live for a week).
- **Phase 3** (+30 days): Replace `require_verified_human_soft` calls with `require_verified_human` and remove the soft-mode wrapper.

## Observability

Structured log events:
- `guest.human_verify action=verified guest_id=N` — bootstrap success.
- `guest.human_verify action=blocked guest_id=N reason=cookie_invalid|expired|missing` — 403 from gated endpoint.
- `guest.human_verify action=missing guest_id=N reason=soft_mode_pass` — soft-mode warning.
- `guest.human_verify action=turnstile_failed reason=cloudflare_rejected` — Turnstile rejected token.
- `kiosk.pair action=nonce_issued|nonce_consumed|nonce_expired|nonce_missing` — kiosk pairing.

## Single-worker assumption

The kiosk-pair nonce dict (`_pair_nonces` in `api/kiosk.py`) is in-memory. `server/scripts/start.sh` runs `uvicorn` with no `--workers` flag (= 1 worker), so this is safe today. **If the deploy ever scales to multiple workers, replace the dict with a `KioskPairChallenge` SQLAlchemy model** (10-second TTL row, periodic cleanup). The session cookie is fine across workers because it's stateless.

## Threats covered

- Mass bot floods of search/submit/vote: each guest cookie requires Turnstile solve; per-IP rate limit caps bootstrap calls.
- IP rotation: each new IP needs a new Turnstile solve. Cloudflare scoring catches IP-rotation patterns.
- OTP email-cost abuse: per-action Turnstile + email-hash 3/hr cap + IP 10/min cap.
- Kiosk pair-table flooding: IP-bound 10s nonce + 3/min rate.

## Threats NOT covered (out of scope)

- Targeted in-event griefing by attendees with valid event codes (different threat model).
- Per-action fresh Turnstile on submit/vote (would re-introduce visible friction).
- Bot detection on authenticated DJ endpoints (DJs auth via JWT, separate threat model).

## Spec reference

`docs/superpowers/specs/2026-05-01-public-page-human-verification-design.md`

# Human Verification UX Overlay + Cookie Versioning — Design

**Status:** Draft for approval
**Author:** thewrz
**Date:** 2026-05-23
**Related work:** Builds on PR #324 (collection/live code split + collect hardening) and PR #325 (Turnstile fallback container).

## Background

Two related problems were observed during the rollout of PR #324:

1. **Glitchy verification UX on the collect page.** New users (and a DJ owner viewing their own event in Firefox) saw the collect page enter a retry loop: `GET /api/public/collect/ELZ2G2/profile` returned 403 repeatedly while Turnstile invisible verification quietly ran in the background. After ~30 seconds the verification completed silently and the page "fixed itself," but the user-visible experience was multiple refreshes and 403 errors with no UI feedback. The hook fell back to a `display:none` container for the widget, so when Cloudflare considered escalating to a visible challenge it had nowhere to render — the user would have been locked out entirely.

2. **Cookie issued under the old infrastructure stays valid.** The `wrzdj_human` HMAC-signed cookie has no version field. Sessions created before PR #324's hardening shipped (when the gate was in soft mode) carry exactly the same shape as fresh post-hardening cookies. Existing cookies remain valid until the 60-minute sliding window expires. We want to force re-verification on every user whose cookie was issued before this change, because their session predates the hardening.

The redirect from the collect page to the live join page was also broken (separately) by PR #324: `router.replace(\`/join/${code}\`)` uses the collection code, but `/join/` now resolves by `join_code`. Fixing that redirect must not leak the never-publicly-exposed `join_code` to unverified bots that scrape the collect URL during the collection-to-live transition.

## Goals

- Replace the unconditional Turnstile-on-mount + race-condition + 403-loop pattern with an explicit blocking overlay that owns the verification state machine.
- Fast-path: users with a valid `wrzdj_human` cookie skip Turnstile entirely on page mount.
- Invalidate every `wrzdj_human` cookie issued before this change so users post-deploy go through a fresh verification.
- Fix the live-phase redirect bug while keeping `join_code` private from unverified bots.
- One consistent UX for the bootstrap path AND the mid-session sliding-window refresh path.

## Non-goals

- DJ-owner bypass on collect endpoints (explicitly rejected).
- Adding the overlay to the live `/join/[code]` page (explicitly scoped out).
- Pre-emptive cookie refresh at 80% TTL (deferred).
- HMAC secret rotation infrastructure (separate ops concern).
- Removing the soft-mode `require_verified_human_soft` dependency from the votes endpoint (out of scope for this PR; collect-only).

## Cookie versioning

Cookie payload gains a `v` discriminator:

```python
# server/app/services/human_verification.py

HUMAN_COOKIE_VERSION = 2  # bump on any breaking schema or policy change

def issue_human_cookie(response: Response, guest_id: int) -> None:
    settings = get_settings()
    key = settings.effective_human_cookie_secret
    ttl = settings.human_cookie_ttl_seconds
    exp = int(utcnow().timestamp()) + ttl

    payload = {
        "v": HUMAN_COOKIE_VERSION,
        "guest_id": int(guest_id),
        "exp": exp,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = _sign(payload_bytes, key)
    cookie_value = f"{_b64encode(payload_bytes)}.{_b64encode(sig)}"

    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=ttl,
        path="/api/",
    )


def verify_human_cookie(request: Request) -> int | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw or "." not in raw:
        return None

    try:
        payload_part, sig_part = raw.rsplit(".", 1)
        payload_bytes = _b64decode(payload_part)
        sig_bytes = _b64decode(sig_part)
    except (ValueError, binascii.Error):
        return None

    settings = get_settings()
    key = settings.effective_human_cookie_secret
    expected_sig = _sign(payload_bytes, key)
    if not hmac.compare_digest(expected_sig, sig_bytes):
        return None

    try:
        payload = json.loads(payload_bytes)
    except (ValueError, TypeError):
        return None

    if payload.get("v") != HUMAN_COOKIE_VERSION:
        return None  # silent reject — same outcome as a missing cookie

    try:
        guest_id_raw = payload["guest_id"]
        if not isinstance(guest_id_raw, int) or isinstance(guest_id_raw, bool):
            return None
        guest_id = guest_id_raw
        exp = payload["exp"]
        if not isinstance(exp, int) or isinstance(exp, bool):
            return None
    except (KeyError, TypeError):
        return None

    if exp < int(utcnow().timestamp()):
        return None
    return guest_id
```

Pre-existing v=1 (versionless) cookies fail the `v != 2` check and are treated as if absent. Frontend's fast-path probe will report `verified: false` and re-bootstrap through Turnstile.

Rejection is silent; no `Set-Cookie` header is emitted to clear the stale cookie. The stale cookie continues to be sent on every request and continues to fail validation until it naturally expires (≤60 minutes from issue) or is replaced when the user completes a new verification.

## Fast-path endpoint

```python
# server/app/api/guest.py

class VerifyStatusResponse(BaseModel):
    verified: bool
    expires_in: int = 0   # seconds remaining; 0 when not verified


@router.get("/guest/verify-status", response_model=VerifyStatusResponse)
@limiter.limit("60/minute")
def verify_status(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> VerifyStatusResponse:
    """Report whether the caller already has a valid wrzdj_human cookie.

    Returns verified=false on missing, expired, version-mismatched, or
    badly-signed cookies. No side effects. Safe to call on every page mount.
    """
    response.headers["Cache-Control"] = "no-store, private"

    guest_id = verify_human_cookie(request)
    if guest_id is None:
        return VerifyStatusResponse(verified=False, expires_in=0)

    raw = request.cookies.get(COOKIE_NAME)
    payload_part, _ = raw.rsplit(".", 1)
    payload = json.loads(_b64decode(payload_part))
    remaining = max(0, payload["exp"] - int(utcnow().timestamp()))
    return VerifyStatusResponse(verified=True, expires_in=remaining)
```

`Cache-Control: no-store, private` is set explicitly because this response's correctness depends on the caller's specific cookie state; any caching by intermediaries or the browser would invalidate the contract.

Rate-limited at 60/min/IP. The endpoint runs no DB queries and returns only a boolean for the caller's own cookie, so it does not enable enumeration of other guests.

## Live-redirect endpoint (gated)

To fix the redirect bug while keeping `join_code` away from unverified scrapers:

```python
# server/app/api/collect.py

class LiveJoinCodeResponse(BaseModel):
    join_code: str


@router.get("/{code}/live-join-code", response_model=LiveJoinCodeResponse)
@limiter.limit("60/minute")
def get_live_join_code(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    _guest_id: int = Depends(require_verified_human),
):
    """Return the live join_code for an event that has entered the live phase.

    Requires a verified human cookie. The join_code is never returned to
    unverified callers, preserving the property that join codes are only
    revealed via the QR code at event time.
    """
    event = _get_event_or_404(db, code)
    if event.phase not in ("live", "closed"):
        raise HTTPException(status_code=409, detail="Event is not live")
    return LiveJoinCodeResponse(join_code=event.join_code)
```

Note: gated by `require_verified_human` (not `require_email_verified`). Any human can be redirected to the live page; email verification is still only required for write actions during collection.

`CollectEventPreview` does **not** gain a `join_code` field. The only collection-code → join-code path is this gated endpoint.

## Frontend: hook rewrite

`useHumanVerification` is rewritten with:

1. A fast-path probe of `/verify-status` on mount before doing any Turnstile work.
2. A new `before-interactive-callback` flipping state to `challenge` when Cloudflare escalates from invisible to visible verification.
3. A new `retry()` method for the overlay's FailedPanel.
4. Removal of the `display:none` (and zero-size) fallback container — the overlay provides a stable widget container in all non-verified states, so the hook never needs to invent one.

Skeleton (full source in implementation):

```ts
export function useHumanVerification(): UseHumanVerification {
  const [state, setState] = useState<HumanVerificationState>('idle');
  const widgetContainerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const verifiedResolversRef = useRef<Array<() => void>>([]);
  const mountedRef = useRef(true);

  // ... submitToken, flushVerified, renderWidget definitions ...

  useEffect(() => {
    mountedRef.current = true;
    void (async () => {
      try {
        const status = await api.getVerifyStatus();
        if (!mountedRef.current) return;
        if (status.verified) {
          setState('verified');
          flushVerified();
          return;
        }
      } catch {
        // /verify-status failure (network / 5xx) falls through to Turnstile
      }
      try {
        await renderWidget();
      } catch {
        if (mountedRef.current) setState('failed');
      }
    })();
    return () => {
      mountedRef.current = false;
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, []);

  // ... ensureVerified, reverify, retry ...
}
```

`reverify()` is unchanged from a caller perspective — `withHumanRetry` still uses it for mid-session sliding-window refreshes. Internally it now flips through `loading` → `verified|challenge|failed`, which the overlay observes.

**Open implementation item**: `before-interactive-callback` is not documented in some Turnstile reference materials. If it does not exist as a named callback, fall back to polling the iframe's bounding box in a `requestAnimationFrame` loop and flipping state to `challenge` when the iframe height exceeds ~16px. This must be confirmed during implementation against the live Turnstile JS API surface.

## Frontend: overlay component

```tsx
// dashboard/components/HumanVerificationOverlay.tsx

interface Props {
  state: HumanVerificationState;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
  onRetry: () => void;
  children: ReactNode;
}

export default function HumanVerificationOverlay({
  state, widgetContainerRef, onRetry, children,
}: Props) {
  if (state === 'verified') return <>{children}</>;
  return (
    <div className="hv-overlay-backdrop">
      <div className="hv-overlay-modal" role="dialog" aria-live="polite">
        {(state === 'idle' || state === 'loading') && <LoadingPanel />}
        {state === 'challenge' && <ChallengePanel />}
        {state === 'failed' && <FailedPanel onRetry={onRetry} />}

        <div
          ref={widgetContainerRef}
          data-testid="hv-widget-container"
          style={{
            marginTop: state === 'challenge' ? '1rem' : 0,
            minHeight: state === 'challenge' ? '65px' : 0,
            opacity: state === 'challenge' ? 1 : 0,
            pointerEvents: state === 'challenge' ? 'auto' : 'none',
            transition: 'opacity 120ms ease, min-height 120ms ease',
          }}
        />
      </div>
    </div>
  );
}
```

Three inline panel sub-components:

- `LoadingPanel`: centered spinner + heading "Just a moment" + body "We're verifying your browser before you start picking songs. This usually takes a second." + footnote "Powered by Cloudflare Turnstile".
- `ChallengePanel`: heading "One more step" + body "Please complete the security check below."
- `FailedPanel`: heading "Verification didn't go through" + body "Some privacy tools (Brave Shields, strict tracking protection, VPNs) can interfere. Try again, or open this page in a different browser." + Retry button calling `onRetry()`.

The widget container is mounted in every non-verified state with `opacity: 0` and `pointer-events: none` when invisible, then transitions to visible when `state === 'challenge'`. The ref is therefore attached on mount and stays attached through state transitions; Turnstile's iframe never loses its DOM anchor.

CSS reuses the existing `email-gate-backdrop` / `email-gate-modal` styles as a base; ~25 new lines for `hv-overlay-*` selectors.

Accessibility: `role="dialog"`, `aria-live="polite"` for screen reader announcements, spinner has `aria-label="Verifying"`, Retry is a real `<button>`.

## Frontend: page integration

Collect page wraps in the overlay:

```tsx
// dashboard/app/collect/[code]/page.tsx — bottom of component

const renderPageContent = () => {
  if (!gateComplete) {
    return <NicknameGate code={code} onComplete={handleGateComplete} reverify={reverify} />;
  }
  if (error) { /* error main */ }
  if (!event) { /* loading main */ }
  if (event.phase === 'pre_announce') { /* pre-announce main */ }
  return (
    <EmailGate verified={emailVerified} onVerified={() => setEmailVerified(true)}>
      <main className="collect-page tower">
        {/* full main UI */}
      </main>
    </EmailGate>
  );
};

return (
  <HumanVerificationOverlay
    state={humanState}
    widgetContainerRef={widgetContainerRef}
    onRetry={retry}
  >
    {renderPageContent()}
  </HumanVerificationOverlay>
);
```

The pre-announce countdown page is intentionally inside the overlay; bots must verify before they can scrape event metadata or countdown timestamps.

The existing inline widget container in the main return block is deleted; the overlay owns it now. The inline `{humanState === 'failed' && ...}` error block is deleted; the overlay's FailedPanel replaces it.

`EmailGate` continues to wrap the main UI but only renders when `humanState === 'verified'` (since it sits inside the overlay's children). The two gates never overlap visually.

## Frontend: gated live-redirect handoff

```tsx
// inside the polling tick
const ev = await apiClient.getCollectEvent(code);
if (cancelled) return;
setEvent(ev);

if (ev.phase === 'live' || ev.phase === 'closed') {
  if (humanState !== 'verified') {
    // Don't redirect until we know we're verified — the join_code is gated.
    // The overlay is up anyway; next tick will retry once verified.
    return;
  }
  try {
    const { join_code } = await apiClient.getLiveJoinCode(code);
    sessionStorage.setItem(`wrzdj_live_splash_${code}`, '1');
    router.replace(`/join/${join_code}`);
  } catch {
    // 403 (verification expired) or 409 (phase mismatch) — let next tick retry
  }
  return;
}
```

Two redirect-related fixes layered here:

1. The redirect target uses `join_code` returned from the gated endpoint, not the collection code from the URL — fixes the broken `/join/{collection_code}` 404 introduced by PR #324.
2. Bots without a valid `wrzdj_human` cookie can never learn `join_code` from this flow: the gate blocks the endpoint, and the frontend short-circuits when state is not `verified`.

## Mid-session refresh

The 60-minute sliding-window cookie eventually expires. The existing `withHumanRetry` wrapper catches the resulting 403, calls `reverify()`, retries the original request. After this design lands:

- `reverify()` sets state to `loading`. The overlay reappears with the LoadingPanel.
- Turnstile re-runs invisible-mode bootstrap (~500ms-1s typical).
- On success: state → `verified`, overlay dismisses, original request retries → 200.
- On escalation: state → `challenge`, overlay reveals widget, user completes, overlay dismisses.

Mid-session refresh produces a brief overlay flash in the typical case. The page state behind the overlay is preserved (no scroll position lost, no form data lost) because the overlay is a modal layer, not a navigation.

## Bot threat model after this change

| Actor | Reaches /collect page? | Learns phase? | Learns join_code? |
|---|---|---|---|
| Verified human (cookie valid) | yes | yes | yes (via gated endpoint, only when phase==live) |
| Verified human (no cookie, completes Turnstile) | yes after challenge | yes after challenge | yes after challenge + when phase==live |
| Cookie-cycling bot | gate holds; never verified | sees preview only (uninteresting alone) | **never** |
| URL scanner with collection code | sees preview JSON | yes | **never** |

Pre-existing v=1 cookies are silently invalidated and re-verification is required immediately after deploy.

## Test plan

### Backend (pytest)

| Test | File | Asserts |
|---|---|---|
| `test_issue_human_cookie_includes_version` | `tests/test_human_verification.py` | issued cookie payload contains `v == 2` |
| `test_verify_rejects_v1_cookie` | `tests/test_human_verification.py` | crafted v=1 (or no-v) cookie → `verify_human_cookie()` returns None |
| `test_verify_rejects_wrong_version` | `tests/test_human_verification.py` | payload with `v: 99` → None |
| `test_verify_accepts_v2_cookie` | `tests/test_human_verification.py` | freshly issued cookie → returns guest_id |
| `test_verify_status_no_cookie` | `tests/test_verify_status_endpoint.py` | no `wrzdj_human` → 200 `{verified: false, expires_in: 0}` |
| `test_verify_status_valid_cookie` | `tests/test_verify_status_endpoint.py` | v=2 cookie → 200 `{verified: true, expires_in: ~3600}` |
| `test_verify_status_expired_cookie` | `tests/test_verify_status_endpoint.py` | exp in past → `{verified: false}` |
| `test_verify_status_v1_cookie` | `tests/test_verify_status_endpoint.py` | legacy v=1 cookie → `{verified: false}` |
| `test_verify_status_tampered_signature` | `tests/test_verify_status_endpoint.py` | bad HMAC → `{verified: false}` |
| `test_verify_status_cache_control_header` | `tests/test_verify_status_endpoint.py` | response includes `Cache-Control: no-store, private` |
| `test_live_join_code_requires_human` | `tests/test_collect_public.py` | no cookie → 403 `human_verification_required` |
| `test_live_join_code_returns_code_when_live` | `tests/test_collect_public.py` | verified human + phase=live → 200 with correct `join_code` |
| `test_live_join_code_409_when_not_live` | `tests/test_collect_public.py` | verified human + phase=collection → 409 |
| `test_live_join_code_404_unknown_event` | `tests/test_collect_public.py` | unknown collection code → 404 |

### Frontend (vitest)

| Test | File | Asserts |
|---|---|---|
| `fast-path skips Turnstile when verify-status returns true` | `dashboard/lib/__tests__/useHumanVerification.test.tsx` | `window.turnstile.render` never called; state idle→verified |
| `fast-path runs Turnstile when verify-status returns false` | `dashboard/lib/__tests__/useHumanVerification.test.tsx` | widget rendered; state transitions through loading |
| `network error on verify-status falls back to Turnstile` | `dashboard/lib/__tests__/useHumanVerification.test.tsx` | mocked rejection → widget renders anyway |
| `before-interactive-callback flips state to challenge` | `dashboard/lib/__tests__/useHumanVerification.test.tsx` | simulate escalation → state=challenge |
| `retry re-mounts widget from failed state` | `dashboard/lib/__tests__/useHumanVerification.test.tsx` | call retry() → widget re-rendered |
| `unmount clears mountedRef and prevents late state updates` | `dashboard/lib/__tests__/useHumanVerification.test.tsx` | unmount → late callbacks no-op |
| `HumanVerificationOverlay renders LoadingPanel when loading` | `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx` | "Just a moment" text present |
| `HumanVerificationOverlay renders ChallengePanel when challenge` | `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx` | widget container opacity=1, min-height=65px |
| `HumanVerificationOverlay renders FailedPanel with onRetry` | `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx` | retry button click invokes prop |
| `HumanVerificationOverlay renders children only when verified` | `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx` | backdrop absent, children visible |
| `widget container ref attached in all non-verified states` | `dashboard/components/__tests__/HumanVerificationOverlay.test.tsx` | ref points to DOM node |
| `collect page redirect to join holds until state=verified` | `dashboard/app/collect/[code]/page.test.tsx` | mock phase=live + state=loading → no router.replace; flip to verified → router.replace called |
| `collect page calls live-join-code endpoint before redirect` | `dashboard/app/collect/[code]/page.test.tsx` | redirect target uses fetched join_code, never the URL param |

### Manual smoke tests

1. Hit `/collect/ELZ2G2` in fresh incognito Firefox → overlay appears with "Just a moment…" → resolves within 1-3s → page renders.
2. Cookie kill: open browser with a cached v=1 wrzdj_human cookie → first gated action causes 403 → overlay flashes → silent Turnstile refresh → v=2 cookie issued → action retries → 200.
3. Cloudflare escalation test (block 3rd-party cookies in Firefox): overlay shows loading → escalates to ChallengePanel → click widget → completes → overlay dismisses → page renders.
4. Live-phase redirect: temporarily set `collection_phase_override='force_live'` on a test event → hit /collect → overlay → verify → page polls → calls live-join-code → redirects to /join/{join_code}.
5. Bot scan: with no cookie, `curl https://api.wrzdj.com/api/public/collect/ELZ2G2/live-join-code` → 403; response body contains no join_code.

## Rollout

Single PR. No DB migration. No SQL recovery. No env var changes.

1. Local CI: ruff, ruff format, bandit, pip-audit, pytest with coverage ≥85; frontend lint, tsc --noEmit, vitest; bridge tsc + vitest; bridge-app tsc + vitest; `alembic upgrade head && alembic check`.
2. Push branch, open PR, watch remote CI green, resolve CodeRabbit threads.
3. Merge to main.
4. `ssh wrz-droplet` → `git fetch && git checkout main && git pull` → `./deploy/deploy.sh`.
5. Verify container health.
6. Run manual smoke tests above.

### Rollback

```bash
git revert HEAD            # reverts the merge commit
./deploy/deploy.sh         # redeploys previous main
```

No migrations to roll back; cookies remain valid under the previous code path.

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Cookie kill spike in Turnstile load right after deploy | Low | Cloudflare scales automatically; nowhere near rate limits. |
| `/verify-status` enables enumeration | Low | Returns only a boolean for caller's own cookie; rate-limited 60/min/IP. |
| Overlay flashes briefly on returning users (verify-status latency) | Low | Add 100ms grace before rendering UI; if /verify-status returns before 100ms, no flash. |
| Live-redirect endpoint enables join_code brute-force | Low | Requires `require_verified_human`; cookie-cycling bots can't pass repeatedly. Rate-limited 60/min. |
| `before-interactive-callback` may not exist in current Turnstile JS API | Medium | Verify in docs first; fall back to iframe-size polling via `requestAnimationFrame` if absent. |
| Pre-announce countdown viewers see overlay even before event opens | Low | Acceptable per design decision. |
| Vitest mocks of `window.turnstile` flaky in jsdom | Low | Already mocking it the same way in existing tests. |
| EmailGate inside overlay — double-modal stacking | Low | EmailGate only renders when `humanState === 'verified'`; they never overlap. |
| `/verify-status` response cached by browser/CDN | Medium | Explicit `Cache-Control: no-store, private` header on response; documented in code. |
| Stale v=1 cookies clutter browser cookie jar | Low | They naturally expire ≤60 min after issue; harmless until then. |

## Out of scope (deferred)

- DJ-owner bypass on collect endpoints (explicitly rejected).
- Join page wrap.
- Proof-of-personhood (biometrics, social vouching).
- HMAC secret rotation tooling.
- Pre-emptive cookie refresh at 80% TTL.
- Migrating votes.py from `require_verified_human_soft` to hard mode.

## Sources

- [Cloudflare Turnstile · widget configurations](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/)
- [Cloudflare Turnstile · concepts](https://developers.cloudflare.com/turnstile/concepts/widget/)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP ASVS 3.3.1 — logout/expiration invalidates session token](https://owasp-aasvs4.readthedocs.io/en/latest/3.3.1.html)
- [Tornado Authentication & Security — versioned cookie_secret](https://www.tornadoweb.org/en/stable/guide/security.html)
- [Express session middleware — secret rotation array pattern](https://expressjs.com/en/resources/middleware/session/)
- [Rails secret_key_base rotation semantics](https://guides.rubyonrails.org/security.html)

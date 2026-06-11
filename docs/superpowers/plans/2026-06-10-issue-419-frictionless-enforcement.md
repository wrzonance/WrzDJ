# Issue #419: Frictionless Join × Bot-Protection Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the frontend bootstrap race where, with admin bot-protection enforcement ON, first-visit guests on a frictionless event silently degrade to the highest-friction NicknameGate path; close the enforcement × frictionless test gaps on backend and frontend.

**Architecture:** The systemic fix lives in `useHumanVerification.reverify()` — it currently resolves when the Turnstile widget is rendered/reset, violating the `withHumanRetry` contract ("resolves once `wrzdj_human` cookie is set"). We rewrite `reverify` to (a) never reset an in-flight challenge and (b) resolve only after the cookie is actually issued (or reject on terminal failure). This fixes every `withHumanRetry` call site at once. The join page then distinguishes `human_verification_required` (show the existing `HumanVerificationOverlay`, retryable) from `frictionless_disabled`/network errors (fall back to NicknameGate). **No backend behavior changes** — backend work is new tests only.

**Tech Stack:** React 19 / Next.js app router, vitest + jsdom + @testing-library/react, FastAPI + pytest (SQLite in-memory).

**Worktree:** `/home/adam/github/WrzDJ/.worktrees/feat/issue-419` — branch `feat/issue-419`. NEVER commit to main.

---

### Task 1: Backend tests — ensure-name × enforcement matrix (no behavior change)

**Files:**
- Modify: `server/tests/test_frictionless_ensure_name.py`

The endpoint composition already works (verified in the issue investigation): the `require_verified_human_soft` dependency 403s first under enforcement when the cookie is missing; with a valid cookie the endpoint's `frictionless_join` check still applies. These tests pin that composition.

- [ ] **Step 1: Add the enforcement-matrix tests**

Append to `server/tests/test_frictionless_ensure_name.py` (note: top-of-file imports already include `Event`, `Guest`, `HUMAN_COOKIE_NAME`, `issue_human_cookie`; add `SystemSettings` import):

```python
from app.models.system_settings import SystemSettings
```

and at the end of the file:

```python
def _set_enforced(db, enforced: bool = True) -> None:
    settings = db.query(SystemSettings).filter_by(id=1).first()
    if settings is None:
        settings = SystemSettings(id=1, human_verification_enforced=enforced)
        db.add(settings)
    else:
        settings.human_verification_enforced = enforced
    db.commit()


def test_ensure_name_enforced_valid_cookie_autonames(client, db, test_event: Event):
    """Enforcement ON + frictionless ON + valid human cookie -> 200 auto-name.

    Pins the issue #419 verdict: the two flags compose — frictionless removes
    typing, never bot checks, and a verified guest sails through.
    """
    test_event.frictionless_join = True
    db.commit()
    _set_enforced(db, True)
    _verified_guest_cookie(client, db)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["auto_generated"] is True
    assert body["nickname"]


def test_ensure_name_enforced_missing_human_cookie_403(client, db, test_event: Event):
    """Enforcement ON + frictionless ON + guest cookie but NO human cookie -> 403.

    The hard 403 comes from require_verified_human_soft under enforcement;
    frictionless never bypasses bot protection (issue #419).
    """
    test_event.frictionless_join = True
    db.commit()
    _set_enforced(db, True)
    guest = Guest(token="frictionenforce" + "0" * 49, fingerprint_hash="fp_fe")
    db.add(guest)
    db.commit()
    client.cookies.clear()
    client.cookies.set("wrzdj_guest", guest.token)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "human_verification_required"


def test_ensure_name_enforced_no_cookies_403(client, db, test_event: Event):
    """Enforcement ON + no cookies at all -> 403 human_verification_required."""
    test_event.frictionless_join = True
    db.commit()
    _set_enforced(db, True)
    client.cookies.clear()
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "human_verification_required"


def test_ensure_name_enforced_frictionless_disabled_precedence(client, db, test_event: Event):
    """Enforcement ON + valid cookie + frictionless OFF -> 403 frictionless_disabled.

    With the human gate satisfied, the frictionless gate must still hold:
    ensure-name can never be used to bypass identity hardening on a
    non-frictionless event.
    """
    # test_event.frictionless_join defaults False
    _set_enforced(db, True)
    _verified_guest_cookie(client, db)
    r = client.post(f"/api/public/collect/{test_event.code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "frictionless_disabled"
```

- [ ] **Step 2: Run the new tests**

Run from `/home/adam/github/WrzDJ/.worktrees/feat/issue-419/server`:
`/home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_frictionless_ensure_name.py -v --no-cov`
Expected: all 10 tests PASS (6 existing + 4 new). These pin existing behavior, so they pass immediately — that is the point (no backend change).

- [ ] **Step 3: Lint/format**

`/home/adam/github/WrzDJ/server/.venv/bin/ruff check tests/test_frictionless_ensure_name.py && /home/adam/github/WrzDJ/server/.venv/bin/ruff format tests/test_frictionless_ensure_name.py`

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_frictionless_ensure_name.py
git commit -m "test: pin ensure-name x human-verification-enforcement matrix (#419)"
```

---

### Task 2: `withHumanRetry` throws typed `HumanVerificationRequiredError` post-retry

**Files:**
- Modify: `dashboard/lib/api.ts` (~lines 321-354)
- Test: `dashboard/lib/__tests__/api.test.ts`

Today a post-retry 403 `human_verification_required` falls into the generic `ApiError` throw with an **object** detail (message becomes `[object Object]`). Pages can't distinguish "bot check failed" from "frictionless unavailable". `HumanVerificationRequiredError` already exists in api.ts (line 294) but is never thrown.

- [ ] **Step 1: Write failing tests**

Add to `dashboard/lib/__tests__/api.test.ts` (follow the file's existing import style; import `withHumanRetry` and `HumanVerificationRequiredError` from `../api`):

```ts
describe('withHumanRetry', () => {
  const verificationRequired403 = () =>
    new Response(JSON.stringify({ detail: { code: 'human_verification_required' } }), {
      status: 403,
    });

  it('calls reverify and retries once on 403 human_verification_required', async () => {
    const responses = [
      verificationRequired403(),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    ];
    const doFetch = vi.fn(async () => responses.shift()!);
    const reverify = vi.fn().mockResolvedValue(undefined);

    const result = await withHumanRetry<{ ok: boolean }>(doFetch, reverify);

    expect(reverify).toHaveBeenCalledTimes(1);
    expect(doFetch).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ ok: true });
  });

  it('throws HumanVerificationRequiredError when still 403 after the retry', async () => {
    const doFetch = vi.fn(async () => verificationRequired403());
    const reverify = vi.fn().mockResolvedValue(undefined);

    await expect(withHumanRetry(doFetch, reverify)).rejects.toBeInstanceOf(
      HumanVerificationRequiredError,
    );
    expect(doFetch).toHaveBeenCalledTimes(2);
  });

  it('propagates a reverify rejection without retrying the fetch', async () => {
    const doFetch = vi.fn(async () => verificationRequired403());
    const reverify = vi.fn().mockRejectedValue(new Error('human_verification_failed'));

    await expect(withHumanRetry(doFetch, reverify)).rejects.toThrow('human_verification_failed');
    expect(doFetch).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run to verify the new typed-error test fails**

From `/home/adam/github/WrzDJ/.worktrees/feat/issue-419/dashboard`:
`npm test -- --run lib/__tests__/api.test.ts`
Expected: "throws HumanVerificationRequiredError" FAILS (generic ApiError today); the other two PASS (they pin current behavior).

- [ ] **Step 3: Implement**

In `dashboard/lib/api.ts`, replace the `if (!res.ok)` block of `withHumanRetry` with:

```ts
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Request failed' }));
    if (error?.detail?.code === 'human_verification_required') {
      // Still unverified after the one retry — surface a typed error so pages
      // can distinguish "bot check pending/failed" from feature-level 403s
      // (e.g. frictionless_disabled). See issue #419.
      throw new HumanVerificationRequiredError();
    }
    throw new ApiError(error.detail || 'Request failed', res.status);
  }
```

Also fix the doc comment placement: the JSDoc currently at lines 321-327 (above `EmailVerificationRequiredError`) describes `withHumanRetry` — move it directly above the `withHumanRetry` function and extend it with: `Rethrows HumanVerificationRequiredError if the retried request is still rejected for missing human verification.`

- [ ] **Step 4: Run tests + types**

`npm test -- --run lib/__tests__/api.test.ts` → all PASS.
`npx tsc --noEmit` → clean.

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/lib/__tests__/api.test.ts
git commit -m "fix(join): withHumanRetry surfaces typed HumanVerificationRequiredError (#419)"
```

---

### Task 3: `useHumanVerification.reverify` honors the cookie-set contract

**Files:**
- Modify: `dashboard/lib/useHumanVerification.ts`
- Test: `dashboard/lib/__tests__/useHumanVerification.test.tsx`

Contract: `reverify()` resolves only once verification completes (cookie issued), rejects with `HumanVerificationFailedError` on terminal failure, and never resets a challenge that is already in flight. This fixes ALL `withHumanRetry` call sites (join + collect + NicknameGate + CollectDetailSheet) at once — they all pass this same hook function. All call sites already `.catch()` rejections (rejections were always possible from `withHumanRetry`'s final throw), so the new rejection path is safe.

- [ ] **Step 1: Update the turnstile mock + existing reverify test, add new tests**

In `dashboard/lib/__tests__/useHumanVerification.test.tsx`, replace the `beforeEach` turnstile mock so `reset` re-fires the captured callback (simulating real Turnstile re-running the invisible challenge after reset) and the last render opts are capturable:

```ts
type RenderOpts = { callback?: (t: string) => void; 'error-callback'?: () => void };

let lastRenderOpts: RenderOpts | null = null;

describe('useHumanVerification', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastRenderOpts = null;
    type FakeTurnstile = {
      render: (el: HTMLElement, opts: RenderOpts) => string;
      reset: (id?: string) => void;
      remove: (id: string) => void;
    };
    (window as unknown as { turnstile: FakeTurnstile }).turnstile = {
      render: vi.fn((_el, opts) => {
        lastRenderOpts = opts;
        // Asynchronously fire the callback with a fake token
        setTimeout(() => opts.callback?.('fake-token'), 0);
        return 'widget-id-1';
      }),
      // Real Turnstile re-runs the (invisible) challenge after reset and
      // invokes the original callback with a fresh token.
      reset: vi.fn(() => {
        setTimeout(() => lastRenderOpts?.callback?.('fresh-token'), 0);
      }),
      remove: vi.fn(),
    };
  });
```

The existing test `'reverify resets the widget and runs bootstrap again'` keeps passing unchanged (reset now re-fires the callback, so the awaited reverify resolves).

Add these tests inside the describe block:

```ts
  it('reverify resolves only after the re-run challenge completes', async () => {
    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe('verified'));

    // Make reset inert so we control when the new token arrives.
    const turnstile = (window as unknown as { turnstile: { reset: ReturnType<typeof vi.fn> } })
      .turnstile;
    turnstile.reset.mockImplementation(() => {});

    let resolved = false;
    let promise!: Promise<void>;
    act(() => {
      promise = result.current.reverify().then(() => {
        resolved = true;
      });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    // Widget was reset but no new token yet -> contract says we must NOT
    // have resolved (the wrzdj_human cookie is not set yet).
    expect(resolved).toBe(false);
    expect(result.current.state).toBe('loading');

    // Complete the challenge.
    await act(async () => {
      lastRenderOpts?.callback?.('fresh-token');
      await promise;
    });
    expect(resolved).toBe(true);
    expect(result.current.state).toBe('verified');
  });

  it('reverify during an in-flight challenge waits instead of resetting it', async () => {
    const turnstile = (window as unknown as {
      turnstile: { render: ReturnType<typeof vi.fn>; reset: ReturnType<typeof vi.fn> };
    }).turnstile;
    // Challenge that never auto-completes.
    turnstile.render.mockImplementation((_el: HTMLElement, opts: RenderOpts) => {
      lastRenderOpts = opts;
      return 'widget-id-1';
    });

    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe('loading'));

    let resolved = false;
    act(() => {
      void result.current.reverify().then(() => {
        resolved = true;
      });
    });
    // Mid-challenge reverify must not reset (it would restart the challenge).
    expect(turnstile.reset).not.toHaveBeenCalled();

    await act(async () => {
      lastRenderOpts?.callback?.('fake-token');
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() => expect(result.current.state).toBe('verified'));
    await waitFor(() => expect(resolved).toBe(true));
  });

  it('reverify rejects with HumanVerificationFailedError when verification fails', async () => {
    const { useHumanVerification, HumanVerificationFailedError } = await import(
      '../useHumanVerification'
    );
    const { api } = await import('../api');
    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe('verified'));

    // The re-run challenge produces a token the server rejects.
    (api.verifyHuman as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ verified: false });

    let rejection: unknown = null;
    await act(async () => {
      await result.current.reverify().catch((err: unknown) => {
        rejection = err;
      });
    });
    expect(rejection).toBeInstanceOf(HumanVerificationFailedError);
    expect(result.current.state).toBe('failed');
  });
```

- [ ] **Step 2: Run to verify new tests fail**

From `dashboard/`: `npm test -- --run lib/__tests__/useHumanVerification.test.tsx`
Expected: the three new tests FAIL (current reverify resolves immediately after reset; resets mid-flight; never rejects). Existing 4 tests PASS.

- [ ] **Step 3: Rewrite the hook**

Replace `dashboard/lib/useHumanVerification.ts` content as follows (full file):

```ts
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from './api';
import { getTurnstileSiteKey, loadTurnstileScript } from './turnstile';

export type HumanVerificationState =
  | 'idle'
  | 'loading'
  | 'verified'
  | 'challenge'
  | 'failed';

/**
 * Terminal client-side verification failure: the Turnstile widget errored or
 * the server rejected the token. `reverify()` rejects with this so callers
 * (via withHumanRetry) can distinguish "bot check failed" from feature-level
 * errors instead of silently degrading. See issue #419.
 */
export class HumanVerificationFailedError extends Error {
  constructor() {
    super('human_verification_failed');
    this.name = 'HumanVerificationFailedError';
  }
}

export interface UseHumanVerification {
  state: HumanVerificationState;
  ensureVerified: () => Promise<void>;
  reverify: () => Promise<void>;
  retry: () => void;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
}

interface VerificationWaiter {
  resolve: () => void;
  reject: (err: Error) => void;
}

/**
 * Owns the human-verification state machine for the page.
 *
 * On mount, probes /api/public/guest/verify-status to short-circuit Turnstile
 * when the visitor already has a valid wrzdj_human cookie. When no valid
 * cookie exists, renders the Turnstile widget into the page-supplied
 * widget container (provided by HumanVerificationOverlay). Cloudflare
 * escalation from invisible to visible challenge flips state to 'challenge'
 * via the before-interactive-callback so the overlay can reveal the widget.
 *
 * Contract (relied on by withHumanRetry in lib/api.ts): `reverify()` resolves
 * only once verification has completed and the wrzdj_human cookie has been
 * issued; it rejects with HumanVerificationFailedError on terminal failure.
 * It never resets a challenge that is already in flight.
 */
export function useHumanVerification(): UseHumanVerification {
  const [state, setState] = useState<HumanVerificationState>('idle');
  const widgetContainerRef = useRef<HTMLDivElement | null>(null);
  const fallbackContainerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const waitersRef = useRef<VerificationWaiter[]>([]);
  const mountedRef = useRef(true);
  const retryCountRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  const flushVerified = useCallback(() => {
    const waiters = waitersRef.current;
    waitersRef.current = [];
    waiters.forEach(({ resolve }) => resolve());
  }, []);

  const flushFailed = useCallback(() => {
    const waiters = waitersRef.current;
    waitersRef.current = [];
    waiters.forEach(({ reject }) => reject(new HumanVerificationFailedError()));
  }, []);

  const waitForVerified = useCallback(
    () =>
      new Promise<void>((resolve, reject) => {
        waitersRef.current = [...waitersRef.current, { resolve, reject }];
      }),
    [],
  );

  const submitToken = useCallback(
    async (token: string) => {
      try {
        const result = await api.verifyHuman(token);
        if (!mountedRef.current) return;
        if (result.verified) {
          setState('verified');
          flushVerified();
        } else {
          setState('failed');
          flushFailed();
        }
      } catch {
        if (mountedRef.current) setState('failed');
        flushFailed();
      }
    },
    [flushVerified, flushFailed],
  );

  const renderWidget = useCallback(async () => {
    if (!mountedRef.current) return;
    setState('loading');
    const sitekey = await getTurnstileSiteKey();
    if (!mountedRef.current) return;
    if (!sitekey) {
      // Dev / Turnstile-disabled — treat as verified
      setState('verified');
      flushVerified();
      return;
    }
    await loadTurnstileScript();
    if (!mountedRef.current || !window.turnstile) return;

    let container = widgetContainerRef.current;
    if (!container) {
      // Overlay should have mounted the ref before we get here; wait a frame
      // for React to paint and retry. After a few frames give up and create
      // a zero-size offscreen fallback so the hook still completes (covers
      // contexts that don't render the overlay, e.g. hook unit tests).
      if (retryCountRef.current < 3) {
        retryCountRef.current += 1;
        requestAnimationFrame(() => void renderWidget());
        return;
      }
      if (!fallbackContainerRef.current) {
        const el = document.createElement('div');
        el.setAttribute('data-testid', 'hv-widget-fallback');
        Object.assign(el.style, {
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: '10000',
          width: '0',
          height: '0',
          overflow: 'visible',
          pointerEvents: 'none',
        });
        document.body.appendChild(el);
        fallbackContainerRef.current = el;
      }
      container = fallbackContainerRef.current;
    }

    if (widgetIdRef.current) {
      window.turnstile.reset(widgetIdRef.current);
      return;
    }

    widgetIdRef.current = window.turnstile.render(container, {
      sitekey,
      appearance: 'interaction-only',
      size: 'normal',
      callback: (token: string) => {
        void submitToken(token);
      },
      'error-callback': () => {
        if (mountedRef.current) setState('failed');
        flushFailed();
      },
      'expired-callback': () => {
        if (!mountedRef.current) return;
        setState('idle');
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
        }
      },
      // Cloudflare invokes this when an invisible challenge escalates to a
      // visible one. We flip state so the overlay reveals the widget. If
      // this callback name turns out not to exist in the current Turnstile
      // JS API, an iframe-size polling fallback is the next step.
      'before-interactive-callback': () => {
        if (mountedRef.current) setState('challenge');
      },
    } as Parameters<typeof window.turnstile.render>[1]);
  }, [submitToken, flushVerified, flushFailed]);

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
        // A reverify() triggered while the probe was in flight may already
        // have rendered the widget — don't reset its in-progress challenge.
        if (!widgetIdRef.current) {
          await renderWidget();
        }
      } catch {
        if (mountedRef.current) setState('failed');
        flushFailed();
      }
    })();
    return () => {
      mountedRef.current = false;
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
      if (fallbackContainerRef.current) {
        fallbackContainerRef.current.remove();
        fallbackContainerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ensureVerified = useCallback((): Promise<void> => {
    if (stateRef.current === 'verified') return Promise.resolve();
    return waitForVerified();
  }, [waitForVerified]);

  const reverify = useCallback((): Promise<void> => {
    if (!mountedRef.current) return Promise.resolve();
    const current = stateRef.current;
    // A challenge is already in flight — resetting would restart it (and
    // delay every gated call on the page). Wait for it to settle instead.
    if (current === 'loading' || current === 'challenge') {
      return waitForVerified();
    }
    // 'verified' (server rejected a stale/missing cookie), 'idle', or
    // 'failed': re-run the challenge. Register the waiter BEFORE kicking the
    // widget so a synchronous flush can't be missed.
    const settled = waitForVerified();
    setState('loading');
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current);
    } else {
      void renderWidget().catch(() => {
        if (mountedRef.current) setState('failed');
        flushFailed();
      });
    }
    return settled;
  }, [renderWidget, waitForVerified, flushFailed]);

  const retry = useCallback(() => {
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.remove(widgetIdRef.current);
      widgetIdRef.current = null;
    }
    void renderWidget();
  }, [renderWidget]);

  return { state, ensureVerified, reverify, retry, widgetContainerRef };
}
```

Key changes vs old file: waiters carry `{resolve, reject}`; `flushFailed` rejects with `HumanVerificationFailedError` everywhere state becomes `'failed'`; `reverify` waits without resetting when a challenge is in flight, otherwise resets/renders and resolves only on completion; mount effect skips `renderWidget()` if a widget already exists (a racing `reverify` may have rendered it).

- [ ] **Step 4: Run hook tests**

`npm test -- --run lib/__tests__/useHumanVerification.test.tsx` → all 7 PASS.

- [ ] **Step 5: Run the full dashboard suite + types (collect page, NicknameGate, overlay tests must stay green)**

`npx tsc --noEmit && npm test -- --run` → clean.

- [ ] **Step 6: Commit**

```bash
git add dashboard/lib/useHumanVerification.ts dashboard/lib/__tests__/useHumanVerification.test.tsx
git commit -m "fix(join): reverify resolves only once human cookie is issued; never resets in-flight challenge (#419)"
```

---

### Task 4: Join page — gate decision sequencing + verification overlay (no NicknameGate degradation)

**Files:**
- Modify: `dashboard/app/join/[code]/page.tsx` (gate-decision effect ~lines 116-160, pre-gate render ~lines 433-446)
- Test: `dashboard/app/join/[code]/__tests__/page.test.tsx`

- [ ] **Step 1: Update test mocks + add failing tests**

In `dashboard/app/join/[code]/__tests__/page.test.tsx`:

(a) Extend the hoisted block with a typed verification error and export it:

```ts
const { mockApi, MockApiError, MockHumanVerificationRequiredError } = vi.hoisted(() => {
  class MockApiError extends Error {
    status: number;
    constructor(message: string, status = 0) {
      super(message);
      this.status = status;
    }
  }

  class MockHumanVerificationRequiredError extends MockApiError {
    constructor() {
      super('Human verification required', 403);
      this.name = 'HumanVerificationRequiredError';
    }
  }

  const mockApi = {
    /* ... keep existing fields unchanged ... */
  };

  return { mockApi, MockApiError, MockHumanVerificationRequiredError };
});
```

(b) Add the class to the api module mock:

```ts
vi.mock('@/lib/api', () => ({
  api: mockApi,
  ApiError: MockApiError,
  HumanVerificationRequiredError: MockHumanVerificationRequiredError,
  PUBLIC_PAGE_MAX: 500,
}));
```

(c) Update the NicknameGate mock to render a detectable marker (existing behavior of auto-completing stays):

```ts
vi.mock('@/components/NicknameGate', () => ({
  NicknameGate: ({ onComplete }: { onComplete: (r: unknown) => void }) => {
    onComplete({ nickname: 'TestUser', emailVerified: false, submissionCount: 0, submissionCap: 5 });
    return <div data-testid="nickname-gate" />;
  },
  GateResult: {},
}));
```

(d) Replace the useHumanVerification module mock so it also exports the failure error class and a `retry` field:

```ts
vi.mock('@/lib/useHumanVerification', () => {
  class MockHumanVerificationFailedError extends Error {
    constructor() {
      super('human_verification_failed');
      this.name = 'HumanVerificationFailedError';
    }
  }
  return {
    useHumanVerification: () => ({
      state: 'verified',
      reverify: vi.fn().mockResolvedValue(undefined),
      ensureVerified: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn(),
      widgetContainerRef: { current: null },
    }),
    HumanVerificationFailedError: MockHumanVerificationFailedError,
  };
});
```

(e) Add the new tests in the `'JoinEventPage — frictionless join'` describe block:

```ts
  it('auto-names after a 403-then-verified retry without flashing NicknameGate', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Party',
      collection_code: 'TEST01',
      requests_open: true,
      frictionless_join: true,
      phase: 'live',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    let reverifyAwaited = false;
    mockApi.ensureGuestName.mockImplementation(
      async (_code: string, reverify?: () => Promise<void>) => {
        // Simulate withHumanRetry under enforcement: first attempt 403s, the
        // wrapper awaits reverify (resolves once the cookie is set), retries.
        await reverify?.();
        reverifyAwaited = true;
        return { nickname: 'VerifiedOtter', auto_generated: true };
      },
    );

    render(<JoinEventPage />);

    await waitFor(() => expect(screen.getByText(/VerifiedOtter/)).toBeInTheDocument());
    expect(reverifyAwaited).toBe(true);
    expect(screen.queryByTestId('nickname-gate')).not.toBeInTheDocument();
  });

  it('shows the verification overlay, not NicknameGate, when verification cannot complete', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockRejectedValue(new MockHumanVerificationRequiredError());

    render(<JoinEventPage />);

    await waitFor(() =>
      expect(screen.getByText(/Verification didn.t go through/i)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('nickname-gate')).not.toBeInTheDocument();
  });

  it('still falls back to NicknameGate on non-verification errors (e.g. frictionless_disabled)', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockRejectedValue(new MockApiError('frictionless_disabled', 403));

    render(<JoinEventPage />);

    // The NicknameGate mock auto-completes with TestUser — proof the gate path ran.
    await waitFor(() => expect(screen.getByTestId('identity-bar')).toHaveTextContent('TestUser'));
  });
```

- [ ] **Step 2: Run to verify the two new behavior tests fail**

`npm test -- --run "app/join/[code]/__tests__/page.test.tsx"`
Expected: "shows the verification overlay" FAILS (today the catch falls back to NicknameGate). "auto-names after a 403-then-verified retry" PASSES already at page level (the await chain works once reverify honors the contract — which the mock does); keep it as the regression pin. "falls back" PASSES. All pre-existing tests PASS.

- [ ] **Step 3: Implement the page changes**

In `dashboard/app/join/[code]/page.tsx`:

(a) Imports — extend:

```ts
import { api, ApiError, HumanVerificationRequiredError, PublicEvent, GuestNowPlaying, GuestRequestInfo, PUBLIC_PAGE_MAX, SearchResult } from '@/lib/api';
import { useHumanVerification, HumanVerificationFailedError } from '@/lib/useHumanVerification';
import HumanVerificationOverlay from '@/components/HumanVerificationOverlay';
```

(b) Hook destructure — add `retry`:

```ts
const { state: humanState, reverify, retry, widgetContainerRef } = useHumanVerification();
```

(c) Gate state — after the `gateDecided` declaration add:

```ts
  /* Verification-blocked gate: ensure-name failed because the bot check is
     pending/failed (HumanVerificationRequiredError / HumanVerificationFailedError).
     This is NOT "frictionless unavailable" — we hold the guest on the
     verification overlay instead of degrading to NicknameGate (issue #419). */
  const [gateVerificationFailed, setGateVerificationFailed] = useState(false);
  const [gateAttempt, setGateAttempt] = useState(0);
```

(d) Gate-decision effect — replace the `catch` and extend deps:

```ts
  useEffect(() => {
    if (gateComplete || identityLoading) return;
    let active = true;
    (async () => {
      try {
        const cfg = await api.getJoinConfig(code);
        if (!active) return;
        if (!cfg.frictionless_join) {
          setGateDecided(true); // not frictionless -> NicknameGate renders
          return;
        }
        const res = await api.ensureGuestName(code, reverify);
        if (!active) return;
        setNickname(res.nickname);
        setAutoNamed(res.auto_generated);
        setGateComplete(true);
      } catch (err) {
        if (!active) return;
        if (
          err instanceof HumanVerificationRequiredError ||
          err instanceof HumanVerificationFailedError
        ) {
          // Bot check pending/failed — keep the verification overlay up
          // rather than silently degrading to the nickname/email gate.
          setGateVerificationFailed(true);
          return;
        }
        // frictionless_disabled / network errors -> normal NicknameGate flow.
        setGateDecided(true);
      }
    })();
    return () => { active = false; };
  }, [code, gateComplete, identityLoading, reverify, gateAttempt]);
```

(e) Retry handler — add below the effect (next to `handleRename`):

```ts
  /* Re-run both the Turnstile widget and the frictionless decision after a
     verification failure (wired to the overlay's "Try again" button). */
  const retryGateVerification = useCallback(() => {
    setGateVerificationFailed(false);
    retry();
    setGateAttempt((a) => a + 1);
  }, [retry]);
```

(f) Pre-gate render — replace the `if (!gateComplete)` block:

```tsx
  if (!gateComplete) {
    // Wait for the frictionless decision before rendering the nickname gate,
    // so frictionless events never flash the gate on their way to auto-name.
    // The overlay keeps Turnstile's challenge reachable (and failures
    // visible/retryable) while the decision is pending (issue #419).
    if (!gateDecided) {
      return (
        <HumanVerificationOverlay
          state={gateVerificationFailed ? 'failed' : humanState}
          widgetContainerRef={widgetContainerRef}
          onRetry={retryGateVerification}
        >
          <div className="guest-tower" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, color: 'rgba(255,255,255,0.4)', letterSpacing: 2 }}>
              LOADING…
            </div>
          </div>
        </HumanVerificationOverlay>
      );
    }
    return <NicknameGate code={code} onComplete={handleGateComplete} reverify={reverify} />;
  }
```

The main-layout widget container + failed message (lines ~808-820) stay unchanged — they serve the post-gate phase where the overlay is unmounted.

- [ ] **Step 4: Run page tests, full suite, lint, types**

`npm test -- --run "app/join/[code]/__tests__/page.test.tsx"` → all PASS.
`npm run lint && npx tsc --noEmit && npm test -- --run` → clean.

- [ ] **Step 5: Commit**

```bash
git add "dashboard/app/join/[code]/page.tsx" "dashboard/app/join/[code]/__tests__/page.test.tsx"
git commit -m "fix(join): hold verification overlay instead of degrading to NicknameGate under enforcement (#419)"
```

---

### Task 5: Call-site audit, docs note, full CI

**Files:**
- Modify: `docs/HUMAN-VERIFICATION.md` (contract note)
- Verify (no change expected): `dashboard/app/collect/[code]/page.tsx`, `dashboard/components/NicknameGate.tsx`, `dashboard/app/collect/[code]/components/CollectDetailSheet.tsx`

- [ ] **Step 1: Audit remaining `withHumanRetry` call sites**

All call sites pass the hook's `reverify` straight through, so the Task 3 hook fix repairs them wholesale. Verify each tolerates the new rejection path (they all already catch — confirm, don't change):
- `collect/[code]/page.tsx:133` (`submitCollectRequest`) — generic catch shows "Failed to submit. Please try again." ✔
- `collect/[code]/page.tsx:228` (`void reverify()` on live-redirect 403) — fire-and-forget; add `.catch(() => {})` ONLY if the void-rejection triggers an unhandled-rejection warning in tests; otherwise leave. Note: `void promise` does NOT swallow rejections — change line 228 to `reverify().catch(() => {});` to prevent unhandled rejections now that reverify can reject. This is the one call-site code change.
- `collect/[code]/page.tsx:430,485` (votes) — `.catch`/try-catch present ✔
- `NicknameGate.tsx:153,241` (`setCollectProfile`) — try/catch with fallback error message ✔
- `CollectDetailSheet.tsx:54` (`getCollectPreview`) — `.catch(() => {})` present ✔
- `join/[code]/page.tsx` — handleVote/handleSearch/handleSubmit/handleRename: handleRename has no catch — it's invoked by `IdentityBar`'s rename flow; check `IdentityBar.tsx` handles a rejected `onRename` (it does — confirm; if not, wrap). Confirm and document only.

- [ ] **Step 2: Update docs/HUMAN-VERIFICATION.md**

Find the `withHumanRetry` bullet (line ~47) and extend the adjacent hook description with the now-true contract, e.g. after the existing line add:

```markdown
- `lib/useHumanVerification.ts:reverify` — resolves only once verification completes and the `wrzdj_human` cookie is issued (rejects with `HumanVerificationFailedError` on terminal failure); never resets a challenge that is already in flight. Required by the `withHumanRetry` contract (#419).
```

- [ ] **Step 3: Full local CI**

Backend (from `<worktree>/server`, venv binaries via `/home/adam/github/WrzDJ/server/.venv/bin/`):
`ruff check . && ruff format --check . && bandit -r app -c pyproject.toml -q && pytest --tb=short -q`
Frontend (from `<worktree>/dashboard`):
`npm run lint && npx tsc --noEmit && npm test -- --run`
Then `git checkout -- dashboard/next-env.d.ts` if modified.

- [ ] **Step 4: Commit**

```bash
git add docs/HUMAN-VERIFICATION.md "dashboard/app/collect/[code]/page.tsx"
git commit -m "docs: document reverify contract; guard collect live-redirect reverify rejection (#419)"
```

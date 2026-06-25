# Frontend DEV_AUTH_BYPASS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `NEXT_PUBLIC_DEV_AUTH_BYPASS` build-time flag that short-circuits the Turnstile bootstrap and NicknameGate on guest pages, enabling headless Playwright specs to run without minting a `wrzdj_human` cookie.

**Architecture:** A single `devAuthBypass.ts` utility exports an `isDevAuthBypassActive()` function that double-gates on `NEXT_PUBLIC_DEV_AUTH_BYPASS` AND `process.env.NODE_ENV !== 'production'`. The hook `useHumanVerification` reads this at mount and immediately resolves to `verified` when it is active. `NicknameGate` reads it and calls `onComplete` immediately with a stub guest. Both component-level touch points are additive — one early-return guard each.

**Tech Stack:** Next.js 15 (App Router), React 19, TypeScript, Vitest + Testing Library

## Global Constraints

- NO Tailwind, no UI framework — vanilla CSS + inline React styles only.
- Dark theme: bg `#0a0a0a`, cards `#1a1a1a`, text `#ededed`.
- TypeScript strict mode — `npx tsc --noEmit` must pass.
- ESLint clean — `npm run lint` must pass.
- Vitest green — `npm test -- --run` must pass.
- Double-gate: bypass active only when `NEXT_PUBLIC_DEV_AUTH_BYPASS` is truthy **and** `process.env.NODE_ENV !== 'production'`.
- Never weaken the backend gate — that is independently enforced.
- `next-env.d.ts` is auto-modified by builds — `git checkout dashboard/next-env.d.ts` before committing if it drifted.

---

### Task 1: `lib/devAuthBypass.ts` — the double-gate utility

**Files:**
- Create: `dashboard/lib/devAuthBypass.ts`
- Create: `dashboard/lib/__tests__/devAuthBypass.test.ts`

**Interfaces:**
- Produces: `isDevAuthBypassActive(): boolean` — returns `true` only when both gates pass.

- [ ] **Step 1: Write the failing test**

Create `dashboard/lib/__tests__/devAuthBypass.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from 'vitest';

// We test the module with different env combinations by re-importing after
// resetting the module registry (vi.resetModules()), so env reads happen fresh.

describe('isDevAuthBypassActive', () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it('returns false when flag is absent (default)', async () => {
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '');
    vi.stubEnv('NODE_ENV', 'development');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(false);
  });

  it('returns true when flag is set in development', async () => {
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('NODE_ENV', 'development');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(true);
  });

  it('returns false when flag is set but NODE_ENV is production', async () => {
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '1');
    vi.stubEnv('NODE_ENV', 'production');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(false);
  });

  it('returns false when flag is set but NODE_ENV is test', async () => {
    // In Vitest test runs NODE_ENV is typically "test" — bypass should still
    // be off unless the flag is also set AND NODE_ENV is development.
    // This test confirms it requires the flag to be truthy too.
    vi.stubEnv('NEXT_PUBLIC_DEV_AUTH_BYPASS', '');
    vi.stubEnv('NODE_ENV', 'test');
    const { isDevAuthBypassActive } = await import('../devAuthBypass');
    expect(isDevAuthBypassActive()).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd dashboard && npx vitest run lib/__tests__/devAuthBypass.test.ts
```

Expected: FAIL — `Cannot find module '../devAuthBypass'`.

- [ ] **Step 3: Write minimal implementation**

Create `dashboard/lib/devAuthBypass.ts`:

```typescript
/**
 * DEV-ONLY guest-gate bypass for headless Playwright testing.
 *
 * SECURITY: Double-gated —
 *   1. Build-time: NEXT_PUBLIC_DEV_AUTH_BYPASS must be truthy (baked into the
 *      bundle at `next build` time; absent in production builds by default).
 *   2. Runtime: NODE_ENV must not be 'production'.
 *
 * A production build where the env var is somehow present still gets
 * NODE_ENV === 'production', so the bypass is INERT by construction.
 * The backend enforces its own DEV_AUTH_BYPASS gate independently.
 *
 * Mirror of the backend `Settings.auth_bypass_enabled` property in
 * server/app/core/config.py.
 */
export function isDevAuthBypassActive(): boolean {
  const flagSet = Boolean(process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS);
  const notProd = process.env.NODE_ENV !== 'production';
  return flagSet && notProd;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd dashboard && npx vitest run lib/__tests__/devAuthBypass.test.ts
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-557
git add dashboard/lib/devAuthBypass.ts dashboard/lib/__tests__/devAuthBypass.test.ts
git commit -m "feat(dashboard): add isDevAuthBypassActive double-gate utility (#557)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Short-circuit `useHumanVerification` when bypass is active

**Files:**
- Modify: `dashboard/lib/useHumanVerification.ts` (add 4-line guard at top of `useEffect`)
- Modify: `dashboard/lib/__tests__/useHumanVerification.test.tsx` (add 1 test)

**Interfaces:**
- Consumes: `isDevAuthBypassActive()` from `dashboard/lib/devAuthBypass.ts`
- Produces: `useHumanVerification()` returns `state === 'verified'` immediately when bypass is active.

- [ ] **Step 1: Write the failing test**

Add to `dashboard/lib/__tests__/useHumanVerification.test.tsx`, inside the `describe('useHumanVerification')` block, after the existing tests:

```typescript
  it('immediately resolves to verified when dev bypass is active', async () => {
    vi.mock('../devAuthBypass', () => ({
      isDevAuthBypassActive: () => true,
    }));
    vi.resetModules(); // force re-import so the mock takes effect

    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());

    await waitFor(() => expect(result.current.state).toBe('verified'));

    // Turnstile widget must NOT have been rendered
    const turnstile = (window as unknown as { turnstile: { render: ReturnType<typeof vi.fn> } }).turnstile;
    expect(turnstile.render).not.toHaveBeenCalled();

    vi.unmock('../devAuthBypass');
  });
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dashboard && npx vitest run lib/__tests__/useHumanVerification.test.tsx
```

Expected: the new test FAILS — bypass has no effect yet.

- [ ] **Step 3: Modify `useHumanVerification.ts`**

Add the import after the existing imports block (before the `export type`):

```typescript
import { isDevAuthBypassActive } from './devAuthBypass';
```

Then in the `useEffect` that calls `renderWidget`, add a short-circuit at the very top (before the inner async IIFE):

```typescript
  useEffect(() => {
    mountedRef.current = true;

    // DEV-ONLY: skip all Turnstile bootstrap when the dev bypass is active.
    // isDevAuthBypassActive() is inert in production builds by construction.
    if (isDevAuthBypassActive()) {
      setState('verified');
      flushVerified();
      return;
    }

    void (async () => {
      // ... rest of existing async IIFE unchanged
```

The full `useEffect` opening becomes:
```typescript
  useEffect(() => {
    mountedRef.current = true;

    if (isDevAuthBypassActive()) {
      setState('verified');
      flushVerified();
      return;
    }

    void (async () => {
      try {
        const status = await api.getVerifyStatus();
```

The cleanup function (`return () => { ... }`) is unchanged — still cleans up widget if one was mounted.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd dashboard && npx vitest run lib/__tests__/useHumanVerification.test.tsx
```

Expected: All tests PASS (the new one + the 6 existing).

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-557
git add dashboard/lib/useHumanVerification.ts dashboard/lib/__tests__/useHumanVerification.test.tsx
git commit -m "feat(dashboard): short-circuit useHumanVerification under dev bypass (#557)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Short-circuit `NicknameGate` when bypass is active

**Files:**
- Modify: `dashboard/components/NicknameGate.tsx` (add early-return guard)
- Modify: `dashboard/components/__tests__/NicknameGate.test.tsx` (add 1 test)

**Interfaces:**
- Consumes: `isDevAuthBypassActive()` from `dashboard/lib/devAuthBypass.ts`
- Produces: `NicknameGate` calls `onComplete({ nickname: 'dev', emailVerified: false, submissionCount: 0, submissionCap: 0 })` immediately when bypass is active, without calling any API.

- [ ] **Step 1: Write the failing test**

Add to `dashboard/components/__tests__/NicknameGate.test.tsx`, inside the `describe('NicknameGate')` block:

```typescript
  describe('dev auth bypass', () => {
    beforeEach(() => {
      vi.mock('../../lib/devAuthBypass', () => ({
        isDevAuthBypassActive: () => true,
      }));
    });

    afterEach(() => {
      vi.unmock('../../lib/devAuthBypass');
    });

    it('calls onComplete immediately with dev stub — no API calls', async () => {
      const onComplete = vi.fn();
      render(<NicknameGate code="TEST" onComplete={onComplete} />);

      await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
      expect(onComplete).toHaveBeenCalledWith({
        nickname: 'dev',
        emailVerified: false,
        submissionCount: 0,
        submissionCap: 0,
      });

      // Must not have called any API
      expect(mockGetProfile).not.toHaveBeenCalled();
    });
  });
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd dashboard && npx vitest run "components/__tests__/NicknameGate.test.tsx"
```

Expected: the new test FAILS — bypass has no effect on NicknameGate yet.

- [ ] **Step 3: Modify `NicknameGate.tsx`**

Add the import after the existing imports at the top:

```typescript
import { isDevAuthBypassActive } from '../lib/devAuthBypass';
```

Add an early `useEffect` at the top of the `NicknameGate` function body, before the `useGuestIdentity` call (insert after the `const identity = ...` line but before the state declarations):

```typescript
  // DEV-ONLY: skip all gate logic when the dev bypass is active.
  // isDevAuthBypassActive() is inert in production builds by construction.
  useEffect(() => {
    if (!isDevAuthBypassActive()) return;
    onComplete({ nickname: 'dev', emailVerified: false, submissionCount: 0, submissionCap: 0 });
  }, [onComplete]);
```

Place this effect immediately after `const identity = useGuestIdentity();` and before the state declarations.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd dashboard && npx vitest run "components/__tests__/NicknameGate.test.tsx"
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-557
git add dashboard/components/NicknameGate.tsx "dashboard/components/__tests__/NicknameGate.test.tsx"
git commit -m "feat(dashboard): short-circuit NicknameGate under dev bypass (#557)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Document the flag + full CI gate

**Files:**
- Modify: `.env.example` (add `NEXT_PUBLIC_DEV_AUTH_BYPASS` to the Frontend section)

- [ ] **Step 1: Add env var documentation to `.env.example`**

Append to the `# Frontend (Next.js)` section of `.env.example`:

```
# DEV-ONLY: skip Turnstile + NicknameGate bootstrap on guest pages so Playwright
# specs can run headless without a wrzdj_human cookie or nickname flow.
# Double-gated: active only when this is set AND NODE_ENV != 'production'.
# A prod build is INERT even if this var is somehow present (NODE_ENV is always
# 'production' in a Next.js production build). Never set in deployed environments.
# NEXT_PUBLIC_DEV_AUTH_BYPASS=1
```

- [ ] **Step 2: Run the full frontend CI gate**

```bash
cd dashboard
npm run lint
npx tsc --noEmit
npm test -- --run
```

Expected: All three commands exit 0.

- [ ] **Step 3: Reset next-env.d.ts if drifted**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-557
git checkout dashboard/next-env.d.ts 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-557
git add .env.example
git commit -m "docs: document NEXT_PUBLIC_DEV_AUTH_BYPASS in .env.example (#557)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Open PR

- [ ] **Step 1: Push branch**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-557
git push -u origin feat/issue-557
```

- [ ] **Step 2: Open PR**

```bash
gh pr create \
  --title "feat(dashboard): frontend DEV_AUTH_BYPASS — skip Turnstile + NicknameGate in dev (#557)" \
  --body "$(cat <<'EOF'
## Why

The backend `DEV_AUTH_BYPASS` (#555) already opens the API gates for headless testing.
Without a matching frontend bypass the Playwright guest specs (`02-guest-request`,
`04-search-pipeline`) are still blocked: the UI waits for a Turnstile solve and a nickname
before showing the search/submit form, which headless browsers can't complete.

## What

- New `dashboard/lib/devAuthBypass.ts` — double-gate utility (`isDevAuthBypassActive()`):
  active only when `NEXT_PUBLIC_DEV_AUTH_BYPASS` is truthy **and** `NODE_ENV !== 'production'`.
- `useHumanVerification`: early-returns `verified` when bypass is active, skipping all
  Turnstile script loading and server probes.
- `NicknameGate`: calls `onComplete` immediately with a `dev` stub guest when bypass is active.
- `.env.example` documents the new flag.

## Design decisions

- **Flag name:** `NEXT_PUBLIC_DEV_AUTH_BYPASS` — mirrors the backend `DEV_AUTH_BYPASS` name,
  `NEXT_PUBLIC_` prefix required so it is baked into the client bundle.
- **Double-gate location:** `dashboard/lib/devAuthBypass.ts` is the single source of truth;
  both `useHumanVerification` and `NicknameGate` import from it.
- **Stub nickname:** `'dev'` — arbitrary but deterministic; Playwright specs can assert on it if needed.
- **`emailVerified: false`:** matches the backend's dev guest (intentionally not email-verified).
- **Runtime dev-check:** `process.env.NODE_ENV !== 'production'` — Next.js always bakes
  `NODE_ENV=production` into production bundles, so the bypass code path is dead in prod
  even if the env var were somehow present.

## Testing

- [ ] `npm run lint` passes
- [ ] `npx tsc --noEmit` passes
- [ ] `npm test -- --run` passes (4 new tests: 4×devAuthBypass, 1×useHumanVerification, 1×NicknameGate)
- [ ] Manual dev: set `NEXT_PUBLIC_DEV_AUTH_BYPASS=1` in `.env` — `/join/<code>` goes directly to the search form (no Turnstile overlay, no nickname modal)
- [ ] Manual prod build: `next build` (without the flag) — `/join/<code>` still shows the Turnstile overlay as normal

🤖 Co-authored by Claude Opus 4.8. Closes #557.
EOF
)"
```
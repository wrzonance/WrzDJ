# Fix ThemeToggle / OnboardingOverlay Z-Index Conflict Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the ThemeToggle during an active onboarding tour so it no longer visually conflicts with the OnboardingOverlay backdrop (z-1050) and step card (z-1060).

**Architecture:** `ThemeToggle` reads `onboardingActive` from `HelpContext` (already wraps both DJ and admin layouts via `app/layout.tsx`) and returns `null` when a tour is running. No z-index changes, no new state, no layout modifications — the fix lives entirely in `ThemeToggle.tsx`.

**Tech Stack:** React 19, Next.js 16+, TypeScript strict, Vitest + Testing Library

---

## Branch

```bash
git checkout -b fix/theme-toggle-onboarding-conflict
```

---

## File Map

| Action | File | What changes |
|---|---|---|
| Modify | `dashboard/components/ThemeToggle.tsx` | Add `useHelp()` call; return `null` when `onboardingActive` |
| Create | `dashboard/components/__tests__/ThemeToggle.test.tsx` | New test file — two cases |

No other files need to change. `(dj)/layout.tsx` and `admin/layout.tsx` keep their existing ThemeToggle render — the toggle itself handles its own visibility.

---

## Background: Z-Index Ladder (for reference only — do not change these values)

| z-index | Element | File |
|---|---|---|
| 1050 | ThemeToggle wrapper div | `(dj)/layout.tsx:13`, `admin/layout.tsx:45` |
| 1050 | OnboardingOverlay backdrop | `OnboardingOverlay.tsx:82` |
| 1060 | OnboardingOverlay step card | `OnboardingOverlay.tsx:105` |
| 1200 | `.help-btn-container` | `globals.css:1213` |

The conflict: backdrop renders after toggle in DOM → paints over toggle at z-1050 tie. Step card at z-1060 fully covers toggle. Fix: hide toggle during tour instead of raising its z-index.

---

## Task 1: Write Failing Tests for ThemeToggle

**Files:**
- Create: `dashboard/components/__tests__/ThemeToggle.test.tsx`

- [ ] **Step 1.1: Create the test file with failing tests**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { ThemeToggle } from '../ThemeToggle';
import * as HelpContext from '@/lib/help/HelpContext';
import type { HelpContextValue } from '@/lib/help/types';

vi.mock('@/lib/theme', () => ({
  useTheme: () => ({ theme: 'dark', toggleTheme: vi.fn() }),
}));

function makeHelpContext(overrides: Partial<HelpContextValue> = {}): HelpContextValue {
  return {
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: vi.fn(),
    registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []),
    startOnboarding: vi.fn(),
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => false),
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(HelpContext, 'useHelp').mockReturnValue(makeHelpContext());
});

describe('ThemeToggle', () => {
  it('renders the toggle button when onboarding is not active', () => {
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(
      makeHelpContext({ onboardingActive: false })
    );
    render(<ThemeToggle />);
    expect(screen.getByRole('button', { name: /current theme/i })).toBeInTheDocument();
  });

  it('renders nothing when onboarding is active', () => {
    vi.spyOn(HelpContext, 'useHelp').mockReturnValue(
      makeHelpContext({ onboardingActive: true })
    );
    render(<ThemeToggle />);
    expect(screen.queryByRole('button', { name: /current theme/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 1.2: Run the tests to confirm they fail**

```bash
cd /home/adam/github/WrzDJ/dashboard && npm test -- --run components/__tests__/ThemeToggle.test.tsx
```

Expected output: both tests FAIL. The first test may pass (button exists), but the second test will FAIL because the current `ThemeToggle` doesn't read `onboardingActive` and always renders. You'll also see an error about `useHelp` not being found in `ThemeToggle`.

- [ ] **Step 1.3: Commit the failing tests**

```bash
cd /home/adam/github/WrzDJ
git add dashboard/components/__tests__/ThemeToggle.test.tsx
git commit -m "test(theme): failing tests for ThemeToggle visibility during onboarding"
```

---

## Task 2: Implement the Fix

**Files:**
- Modify: `dashboard/components/ThemeToggle.tsx`

- [ ] **Step 2.1: Add `useHelp` to ThemeToggle and gate on `onboardingActive`**

Replace the entire file content with:

```typescript
'use client';

import { useTheme, type Theme } from '@/lib/theme';
import { useHelp } from '@/lib/help/HelpContext';

const THEME_LABELS: Record<Theme, string> = {
  dark: 'Dark',
  'high-contrast': 'Hi-Con',
  daylight: 'Day',
};

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const { onboardingActive } = useHelp();

  if (onboardingActive) return null;

  return (
    <button
      onClick={toggleTheme}
      className="theme-toggle"
      title={`Theme: ${THEME_LABELS[theme]} (click to change)`}
      aria-label={`Current theme: ${THEME_LABELS[theme]}. Click to change.`}
    >
      <span className={`theme-toggle-icon theme-toggle-icon--${theme}`} />
      <span className="theme-toggle-label">{THEME_LABELS[theme]}</span>
    </button>
  );
}
```

- [ ] **Step 2.2: Run the tests to confirm they pass**

```bash
cd /home/adam/github/WrzDJ/dashboard && npm test -- --run components/__tests__/ThemeToggle.test.tsx
```

Expected output:
```
✓ ThemeToggle > renders the toggle button when onboarding is not active
✓ ThemeToggle > renders nothing when onboarding is active
```

- [ ] **Step 2.3: Run the full frontend test suite to check for regressions**

```bash
cd /home/adam/github/WrzDJ/dashboard && npm test -- --run
```

Expected: all tests pass. If any test imports `ThemeToggle` without mocking `useHelp`, it will throw "useHelp must be used within a HelpProvider". Fix by adding to that test: `vi.mock('@/lib/help/HelpContext', () => ({ useHelp: () => ({ onboardingActive: false }) }))`.

- [ ] **Step 2.4: Run TypeScript type check**

```bash
cd /home/adam/github/WrzDJ/dashboard && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 2.5: Commit the implementation**

```bash
cd /home/adam/github/WrzDJ
git add dashboard/components/ThemeToggle.tsx
git commit -m "fix(theme): hide ThemeToggle during onboarding tour to resolve z-index conflict"
```

---

## Task 3: Push and Open PR

- [ ] **Step 3.1: Push the branch**

```bash
git push -u origin fix/theme-toggle-onboarding-conflict
```

- [ ] **Step 3.2: Open a PR**

```bash
gh pr create \
  --title "fix(theme): hide ThemeToggle during onboarding tour" \
  --body "$(cat <<'EOF'
## Summary

- `ThemeToggle` now reads `onboardingActive` from `HelpContext` and returns `null` while a tour is running
- Resolves z-index conflict: backdrop at z-1050 and step card at z-1060 both painted over the toggle
- Chose Option B (hide toggle) over Option A (raise z-index) to avoid z-index arms race — theme isn't useful mid-tour

## Files Changed

- `dashboard/components/ThemeToggle.tsx` — add `useHelp()`, return `null` when `onboardingActive`
- `dashboard/components/__tests__/ThemeToggle.test.tsx` — new test file (two cases)

## Test Plan

- [ ] Run `npm test -- --run` in `dashboard/` — all tests pass
- [ ] Start a DJ session, open an event page, trigger the help tour — confirm ThemeToggle disappears during tour and reappears after Done/Skip
- [ ] Repeat in `/admin` — same behavior
- [ ] Confirm ThemeToggle renders normally on pages with no onboarding (no HelpSpots registered)

Closes #314
EOF
)"
```

---

## Self-Review

**Spec coverage check:**
- ✅ ThemeToggle hidden during onboarding tour — Task 2 implements this
- ✅ Backdrop z-1050 / card z-1060 no longer conflicts with toggle — fixed by hiding toggle
- ✅ Option B chosen (hide) over Option A (raise z-index) — as recommended in issue
- ✅ Files listed in issue covered: `ThemeToggle.tsx` (chosen over layout approach — cleaner single location)

**Placeholder scan:** No TBDs or vague steps. All steps include exact commands and code.

**Type consistency:** `HelpContextValue` is imported directly from `@/lib/help/types` in tests, matching its definition. `onboardingActive: boolean` is a direct destructure from `useHelp()` — matches `HelpState` interface at `lib/help/types.ts:12`.

**Edge cases handled:**
- Pages where HelpProvider has no registered spots: `onboardingActive` stays `false` → toggle renders normally
- The `useHelp` mock in tests uses the exact same `HelpContextValue` shape used across all other test files

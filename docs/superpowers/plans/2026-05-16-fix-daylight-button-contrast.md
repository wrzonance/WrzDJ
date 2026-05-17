# Fix Daylight Mode Button Contrast (Issue #315) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace four hardcoded dark hex backgrounds/colors on buttons and art placeholders with CSS variables so they render with correct contrast in daylight mode.

**Architecture:** One-line swap per occurrence — hardcoded hex values (`#333`, `#1a1a1a`, `#ededed`, `#666`) → appropriate CSS variables (`var(--surface-raised)`, `var(--card)`, `var(--text)`, `var(--text-secondary)`). No new abstractions; new test files for pages that lack them, additions to the existing kiosk-link test file.

**Tech Stack:** React/Next.js, TypeScript, Vitest, `@testing-library/react`, `@testing-library/jest-dom`

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dashboard/app/pending/page.tsx` (line 59) |
| Create | `dashboard/app/pending/__tests__/page.test.tsx` |
| Modify | `dashboard/app/kiosk-link/[code]/page.tsx` (lines 95–106, 146) |
| Modify | `dashboard/app/kiosk-link/[code]/__tests__/page.test.tsx` (add 2 tests) |
| Modify | `dashboard/app/join/[code]/components/MyRequestsTracker.tsx` (lines 88, 94) |
| Create | `dashboard/app/join/[code]/components/__tests__/MyRequestsTracker.test.tsx` |

---

## Setup

- [ ] **Create feature branch**

```bash
git checkout -b fix/daylight-button-contrast
```

---

## Task 1: Pending Page — Logout Button

**Root cause:** `background: '#333'` is always dark. In daylight mode, `.btn` inherits `color: var(--text)` → near-black text on dark background (~1.3:1 contrast).

**Files:**
- Modify: `dashboard/app/pending/page.tsx:59`
- Create: `dashboard/app/pending/__tests__/page.test.tsx`

---

- [ ] **Step 1: Create failing test**

Create `dashboard/app/pending/__tests__/page.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PendingPage from '../page';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    role: 'pending',
    logout: vi.fn(),
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    getMe: vi.fn().mockResolvedValue({ role: 'pending' }),
  },
}));

describe('PendingPage', () => {
  it('logout button uses theme-safe background', () => {
    render(<PendingPage />);
    const btn = screen.getByRole('button', { name: /logout/i });
    expect(btn).toHaveAttribute('style', expect.stringContaining('var(--surface-raised)'));
  });
});
```

- [ ] **Step 2: Run test — confirm FAIL**

```bash
cd dashboard && npm test -- --run "app/pending/__tests__/page.test.tsx"
```

Expected: FAIL — `style` attribute contains `#333`, not `var(--surface-raised)`.

- [ ] **Step 3: Fix the code**

In `dashboard/app/pending/page.tsx`, change line 59:

```tsx
// Before
style={{ background: '#333' }}

// After
style={{ background: 'var(--surface-raised)' }}
```

Full button after fix:
```tsx
<button
  className="btn"
  style={{ background: 'var(--surface-raised)' }}
  onClick={logout}
>
  Logout
</button>
```

- [ ] **Step 4: Run test — confirm PASS**

```bash
cd dashboard && npm test -- --run "app/pending/__tests__/page.test.tsx"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/pending/__tests__/page.test.tsx dashboard/app/pending/page.tsx
git commit -m "fix(theme): pending logout button uses var(--surface-raised) for daylight contrast"
```

---

## Task 2: Kiosk-Link Page — Event Selector + Try Again Buttons

**Root cause:**
- Event selector buttons: `background: '#1a1a1a'` + explicit `color: '#ededed'` → white text on dark background in all modes. In daylight mode this is always wrong.
- Try Again button: `background: '#333'` → same problem as pending logout.

**Files:**
- Modify: `dashboard/app/kiosk-link/[code]/page.tsx` (event button ~line 95, try-again button ~line 146)
- Modify: `dashboard/app/kiosk-link/[code]/__tests__/page.test.tsx` (add 2 tests)

---

- [ ] **Step 1: Add failing tests to existing test file**

Open `dashboard/app/kiosk-link/[code]/__tests__/page.test.tsx` and add these two tests inside the existing `describe('KioskLinkPage', ...)` block, after the last existing `it(...)`:

```tsx
  it('event selector buttons use theme-safe background and text color', async () => {
    render(<KioskLinkPage />);

    await waitFor(() => {
      const btn = screen.getByText('Friday Night').closest('button')!;
      expect(btn).toHaveAttribute('style', expect.stringContaining('var(--surface-raised)'));
      expect(btn).toHaveAttribute('style', expect.stringContaining('var(--text)'));
    });
  });

  it('try again button uses theme-safe background', async () => {
    const err = new Error('Test error');
    mockCompleteKioskPairing.mockRejectedValue(err);
    render(<KioskLinkPage />);

    await waitFor(() => screen.getByText('Friday Night'));
    fireEvent.click(screen.getByText('Friday Night').closest('button')!);

    await waitFor(() => {
      const tryAgainBtn = screen.getByRole('button', { name: /try again/i });
      expect(tryAgainBtn).toHaveAttribute('style', expect.stringContaining('var(--surface-raised)'));
    });
  });
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
cd dashboard && npm test -- --run "app/kiosk-link/\[code\]/__tests__/page.test.tsx"
```

Expected: the two new tests FAIL; the 5 existing tests still PASS.

- [ ] **Step 3: Fix the event selector button styles**

In `dashboard/app/kiosk-link/[code]/page.tsx`, find the event selector button (around line 92–107) and replace the `style` object:

```tsx
// Before
style={{
  width: '100%',
  textAlign: 'left',
  padding: '0.75rem 1rem',
  background: '#1a1a1a',
  border: '1px solid #333',
  borderRadius: '8px',
  color: '#ededed',
  cursor: 'pointer',
}}

// After
style={{
  width: '100%',
  textAlign: 'left',
  padding: '0.75rem 1rem',
  background: 'var(--surface-raised)',
  border: '1px solid #333',
  borderRadius: '8px',
  color: 'var(--text)',
  cursor: 'pointer',
}}
```

- [ ] **Step 4: Fix the try-again button style**

In `dashboard/app/kiosk-link/[code]/page.tsx`, find the Try Again button (around line 146):

```tsx
// Before
style={{ background: '#333' }}

// After
style={{ background: 'var(--surface-raised)' }}
```

- [ ] **Step 5: Run tests — confirm all PASS**

```bash
cd dashboard && npm test -- --run "app/kiosk-link/\[code\]/__tests__/page.test.tsx"
```

Expected: all 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add "dashboard/app/kiosk-link/[code]/page.tsx" "dashboard/app/kiosk-link/[code]/__tests__/page.test.tsx"
git commit -m "fix(theme): kiosk-link buttons use CSS variables for daylight contrast"
```

---

## Task 3: MyRequestsTracker — Art Placeholder

**Root cause:** When a request has no artwork, a placeholder div renders with `background: '#333'` and a music-note icon with `color: '#666'`. Both are hardcoded dark values — in daylight mode the background stays dark while everything around it is light.

**Files:**
- Modify: `dashboard/app/join/[code]/components/MyRequestsTracker.tsx` (lines 88, 94)
- Create: `dashboard/app/join/[code]/components/__tests__/MyRequestsTracker.test.tsx`

---

- [ ] **Step 1: Create failing test**

Create `dashboard/app/join/[code]/components/__tests__/MyRequestsTracker.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import MyRequestsTracker from '../MyRequestsTracker';

vi.mock('@/lib/api', () => ({
  api: {
    getMyRequests: vi.fn().mockResolvedValue({
      requests: [
        {
          id: 1,
          title: 'Test Song',
          artist: 'Test Artist',
          status: 'new',
          artwork_url: null,
          created_at: '2026-05-16T00:00:00Z',
          vote_count: 0,
        },
      ],
    }),
  },
}));

describe('MyRequestsTracker', () => {
  it('art placeholder uses theme-safe background', async () => {
    render(
      <MyRequestsTracker
        eventCode="EVT001"
        refreshKey={0}
        onRequestIdsLoaded={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Song')).toBeInTheDocument();
    });

    // The placeholder is a div with class guest-request-item-art (not an img)
    const placeholder = document.querySelector('div.guest-request-item-art');
    expect(placeholder).not.toBeNull();
    expect(placeholder!).toHaveAttribute('style', expect.stringContaining('var(--card)'));
  });

  it('art placeholder icon uses theme-safe text color', async () => {
    render(
      <MyRequestsTracker
        eventCode="EVT001"
        refreshKey={0}
        onRequestIdsLoaded={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Song')).toBeInTheDocument();
    });

    const placeholder = document.querySelector('div.guest-request-item-art');
    const icon = placeholder!.querySelector('span');
    expect(icon).not.toBeNull();
    expect(icon!).toHaveAttribute('style', expect.stringContaining('var(--text-secondary)'));
  });
});
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
cd dashboard && npm test -- --run "app/join/\[code\]/components/__tests__/MyRequestsTracker.test.tsx"
```

Expected: both tests FAIL — `style` attributes contain `#333` and `#666`, not the CSS variables.

- [ ] **Step 3: Fix the placeholder background**

In `dashboard/app/join/[code]/components/MyRequestsTracker.tsx`, find the art placeholder div (~line 85) and change:

```tsx
// Before
style={{
  background: '#333',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}}

// After
style={{
  background: 'var(--card)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}}
```

- [ ] **Step 4: Fix the icon color**

In the same file, change the inner span (~line 94):

```tsx
// Before
<span style={{ fontSize: '1.25rem', color: '#666' }}>&#9835;</span>

// After
<span style={{ fontSize: '1.25rem', color: 'var(--text-secondary)' }}>&#9835;</span>
```

- [ ] **Step 5: Run tests — confirm all PASS**

```bash
cd dashboard && npm test -- --run "app/join/\[code\]/components/__tests__/MyRequestsTracker.test.tsx"
```

Expected: both tests PASS.

- [ ] **Step 6: Run full test suite — confirm no regressions**

```bash
cd dashboard && npm test -- --run
```

Expected: all tests PASS, coverage thresholds met.

- [ ] **Step 7: Commit**

```bash
git add "dashboard/app/join/[code]/components/MyRequestsTracker.tsx" "dashboard/app/join/[code]/components/__tests__/MyRequestsTracker.test.tsx"
git commit -m "fix(theme): art placeholder uses CSS variables for daylight contrast"
```

---

## Wrap-Up

- [ ] **Push branch**

```bash
git push -u origin fix/daylight-button-contrast
```

- [ ] **Open PR**

```bash
gh pr create \
  --title "fix(theme): dark text on buttons in day mode (#315)" \
  --body "$(cat <<'EOF'
## Summary

- Replaces `background: '#333'` on pending page logout button with `var(--surface-raised)`
- Replaces `background: '#1a1a1a'` + `color: '#ededed'` on kiosk-link event selector buttons with `var(--surface-raised)` + `var(--text)`
- Replaces `background: '#333'` on kiosk-link try-again button with `var(--surface-raised)`
- Replaces `background: '#333'` + `color: '#666'` on MyRequestsTracker art placeholder with `var(--card)` + `var(--text-secondary)`

Fixes #315.

## Test plan

- [ ] New test: `app/pending/__tests__/page.test.tsx` — asserts logout button uses `var(--surface-raised)`
- [ ] Extended test: `app/kiosk-link/[code]/__tests__/page.test.tsx` — asserts event selector + try-again buttons use CSS variables
- [ ] New test: `app/join/[code]/components/__tests__/MyRequestsTracker.test.tsx` — asserts placeholder uses `var(--card)` + `var(--text-secondary)`
- [ ] Toggle day mode via the theme toggle in the DJ dashboard and verify all four locations visually
EOF
)"
```

# Theme Toggle Placement, Dashboard Migration & IdentityBar Dark Fix

**Date:** 2026-05-13  
**Author:** thewrz  
**Status:** Approved

---

## Problem

Three theming issues to resolve:

1. **`/dashboard` is outside the `(dj)` route group** — it is the DJ entry point (root redirects here) but has no ThemeToggle and uses hardcoded dark colors throughout. The `(dj)/layout.tsx` ThemeToggle only ever appears once a DJ navigates to `/events/[code]`.

2. **Admin ThemeToggle in wrong location** — renders in sidebar footer; should be in the upper right next to the help button, consistent with the DJ layout.

3. **IdentityBar flashes white on guest pages** — `/join/[code]` and `/collect/[code]` use hardcoded dark backgrounds (`#06060a`, `#0a0a12`) but `IdentityBar` uses CSS variables. In day mode, `var(--card)` resolves to `#ffffff`, producing a bright white bar over a dark page.

---

## Out of Scope

- No ThemeToggle on `/login`, `/register`, `/pending`, `/kiosk-pair`, `/kiosk-link`
- No changes to guest tower styling or kiosk display pages
- No structural changes to `(dj)/layout.tsx` — it is already correct

---

## Design

### Change 1 — Merge dashboard into `(dj)` route group

**Files:**
- `app/dashboard/page.tsx` → moved to `app/(dj)/dashboard/page.tsx`
- `app/(dj)/events/page.tsx` → deleted (duplicate)

Moving into `(dj)/` gives the dashboard ThemeToggle automatically from the layout. The URL `/dashboard` is unchanged — Next.js route group folders `()` do not affect URL paths.

**Merge: features from `(dj)/events/page.tsx` grafted into dashboard:**

| Feature | Source | Action |
|---|---|---|
| Cloud Providers Status (Tidal + Beatport badges) | `dashboard` | Keep |
| Activity Log Panel | `dashboard` | Keep |
| `loadData()` parallel fetch | `dashboard` | Keep |
| `HelpButton` + `OnboardingOverlay` | `events` | Add |
| `HelpSpot` wrappers on header, admin btn, create btn, event grid | `events` | Add |
| Account button (`<Link href="/account">`) | `events` | Add |
| CSS variables replacing hardcoded colors | `events` | Apply throughout |
| Bulk delete re-fetches from server (`await loadEvents()`) | `events` | Replace client-side filter |

**All hardcoded colors to replace with CSS vars:**

| Hardcoded | CSS var |
|---|---|
| `#7f1d1d` / `#fca5a5` (error) | `var(--color-danger-subtle)` / `var(--color-danger)` |
| `#333` (buttons) | `var(--surface-raised)` |
| `#9ca3af` (secondary text) | `var(--text-secondary)` |
| `#3b82f6` (accentColor, outline) | `var(--color-primary)` / `var(--color-accent-checkbox)` |
| `#6b21a8` (admin button) | `var(--color-admin)` |
| `#22c55e` / `#6b7280` (status dots) | Keep as-is — semantic status colors, not theme-sensitive |

**PAGE_ID** for help system: reuse `'events'` (same onboarding context as the page being retired).

### Change 2 — Admin ThemeToggle relocation

**File:** `dashboard/app/admin/layout.tsx`

- Remove `<ThemeToggle />` from `admin-sidebar-footer` div
- Add `<ThemeToggle />` at `position: fixed; top: 1rem; right: 4.5rem` (same as `(dj)/layout.tsx`)

### Change 3 — IdentityBar `forceDark` prop

**Files:**
- `dashboard/components/IdentityBar.tsx`
- `dashboard/app/join/[code]/page.tsx`
- `dashboard/app/collect/[code]/page.tsx`

Add `forceDark?: boolean` prop to `IdentityBar`. When `true`, replace CSS variable references with their dark-theme resolved values:

| CSS var | Hardcoded fallback |
|---|---|
| `var(--card)` | `#1a1a1a` |
| `var(--text-secondary)` | `#9ca3af` |
| `var(--border-subtle)` | `rgba(255,255,255,0.08)` |
| `var(--color-success)`, `var(--color-link)` | Keep as-is — legible on dark |

Both `/join/[code]/page.tsx` and `/collect/[code]/page.tsx` pass `forceDark={true}`.

---

## Files Changed

| File | Change |
|---|---|
| `app/dashboard/page.tsx` | Deleted — moved into `(dj)` group |
| `app/(dj)/dashboard/page.tsx` | New — merged dashboard with events page features |
| `app/(dj)/events/page.tsx` | Deleted — duplicate retired |
| `app/admin/layout.tsx` | Move ThemeToggle from sidebar footer to fixed top-right |
| `components/IdentityBar.tsx` | Add `forceDark` prop |
| `app/join/[code]/page.tsx` | Pass `forceDark={true}` |
| `app/collect/[code]/page.tsx` | Pass `forceDark={true}` |

`app/page.tsx` (root redirect to `/dashboard`) — **no change needed**.

---

## Testing

- Login → `/dashboard`: ThemeToggle visible top-right
- Switch to day mode on `/dashboard`: all colors respond (no hardcoded dark values remain)
- Cloud Providers Status and Activity Log still present
- Help tour still triggers for first-time visitors
- Account button visible in header
- Bulk delete re-fetches event list from server
- `/admin/*`: ThemeToggle visible top-right, not in sidebar footer
- Day mode → `/join/[code]` or `/collect/[code]`: IdentityBar stays dark
- Dark + high-contrast modes: all pages unchanged

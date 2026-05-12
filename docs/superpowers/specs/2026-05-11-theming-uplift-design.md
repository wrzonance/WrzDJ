# Theming Uplift & Consistency — Design Spec
<!-- self-reviewed 2026-05-11: token counts corrected (36 total, not 37; tier-2 is 14 not 15), collect path corrected -->

**Date:** 2026-05-11  
**Branch:** `feat/theming-uplift-consistency`  
**Status:** Approved — ready for implementation planning

---

## Problem

The dashboard has a `ThemeProvider` with three themes (`dark`, `high-contrast`, `daylight`) but only 6 CSS variables. The token set covers surfaces and typography but has zero semantic action colors. As a result:

- `#3b82f6` (primary blue) appears hardcoded **52 times** across TSX and CSS
- `#9ca3af` / `#aaa` / `#888` (secondary text near-duplicates) appear **141 combined times**
- `background: '#333'` is used on buttons because no better token exists
- Switching to `daylight` theme produces no meaningful visual change — all three themes are variants of "very dark"
- `ThemeToggle` only appears on the event detail page, not on other DJ or admin pages

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Daylight definition | True light mode (white/cream bg, dark text) | Only meaningful for outdoor/bright-venue use |
| Scope | DJ + admin pages only | Guest Tower UI, join, display, collect, Camelot wheel excluded — intentional design |
| Token depth | Full 3-tier design system (~36 vars) | Incomplete tokens leave bugs in light mode; full coverage makes future themes purely additive |
| ThemeToggle placement | Next.js route group `app/(dj)/layout.tsx` | Auto-applies to all future DJ pages without per-page imports |
| Migration strategy | 2 PRs (CSS-first, then TSX) | PR1 is zero-visual-change and low-risk; PR2 ships working light mode |

---

## Token Taxonomy (36 vars, 3 tiers)

### Naming rule: role, not value
- Good: `--color-link`, `--color-log-info-bg`, `--color-nickname-accent`
- Bad: `--color-60a5fa`, `--purple-thing`

### Tier 1 — Surfaces & Structure (9 vars)

| Token | Dark | High-Contrast | Daylight |
|---|---|---|---|
| `--bg` | `#0a0a0a` | `#000000` | `#f8fafc` |
| `--card` | `#1a1a1a` | `#111111` | `#ffffff` |
| `--surface-raised` *(new)* | `#111111` | `#0a0a0a` | `#f1f5f9` |
| `--text` | `#ededed` | `#ffffff` | `#0f172a` |
| `--text-secondary` | `#9ca3af` | `#d1d5db` | `#475569` |
| `--text-tertiary` | `#6b7280` | `#9ca3af` | `#64748b` |
| `--border` | `#333333` | `#555555` | `#e2e8f0` |
| `--border-subtle` *(new)* | `#222222` | `#333333` | `#f1f5f9` |
| `--color-overlay` *(new)* | `rgba(0,0,0,0.7)` | `rgba(0,0,0,0.85)` | `rgba(0,0,0,0.5)` |

**Palette optimization:** `--text-secondary` collapses `#9ca3af`, `#aaa`, `#888` (141 combined hits). `--surface-raised` replaces `#111`, `#222`, `#2a2a2a` (12 hits). `--border-subtle` replaces `#222`, `#2a2a2a` (8 hits).

### Tier 2 — Semantic Actions (14 vars)

| Token | Dark | High-Contrast | Daylight |
|---|---|---|---|
| `--color-primary` | `#3b82f6` | `#60a5fa` | `#2563eb` |
| `--color-primary-hover` | `#2563eb` | `#3b82f6` | `#1d4ed8` |
| `--color-primary-subtle` | `rgba(59,130,246,0.12)` | `rgba(59,130,246,0.2)` | `rgba(37,99,235,0.1)` |
| `--color-danger` | `#ef4444` | `#f87171` | `#dc2626` |
| `--color-danger-hover` | `#dc2626` | `#ef4444` | `#b91c1c` |
| `--color-danger-subtle` | `rgba(239,68,68,0.12)` | `rgba(239,68,68,0.2)` | `rgba(220,38,38,0.1)` |
| `--color-success` | `#22c55e` | `#4ade80` | `#16a34a` |
| `--color-success-hover` | `#16a34a` | `#22c55e` | `#15803d` |
| `--color-success-subtle` | `rgba(34,197,94,0.12)` | `rgba(34,197,94,0.2)` | `rgba(22,163,74,0.1)` |
| `--color-warning` | `#f59e0b` | `#fbbf24` | `#d97706` |
| `--color-warning-hover` | `#d97706` | `#f59e0b` | `#b45309` |
| `--color-warning-subtle` | `rgba(245,158,11,0.12)` | `rgba(245,158,11,0.2)` | `rgba(245,158,11,0.1)` |
| `--color-admin` | `#6b21a8` | `#7c3aed` | `#7c3aed` |
| `--color-admin-subtle` | `rgba(107,33,168,0.15)` | `rgba(124,58,237,0.2)` | `rgba(124,58,237,0.1)` |

### Tier 3 — Named UI Roles (13 vars)

| Token | Dark | High-Contrast | Daylight | Replaces |
|---|---|---|---|---|
| `--color-link` | `#60a5fa` | `#93c5fd` | `#2563eb` | links, info badges, identity bar (11 hits) |
| `--color-nickname-accent` | `#a78bfa` | `#c4b5fd` | `#7c3aed` | request nicknames everywhere (7 hits) |
| `--color-code-accent` | `#3b82f6` | `#60a5fa` | `#2563eb` | event codes in monospace |
| `--color-focus-ring` | `rgba(59,130,246,0.4)` | `rgba(59,130,246,0.6)` | `rgba(37,99,235,0.3)` | input/btn focus box-shadow |
| `--color-scrollbar` | `#444444` | `#666666` | `#cbd5e1` | hardcoded `#444` `#555` |
| `--color-log-info-bg` | `#1e3a5f` | `#1e3a5f` | `#dbeafe` | activity log badge |
| `--color-log-info-text` | `#60a5fa` | `#93c5fd` | `#1d4ed8` | activity log badge |
| `--color-log-warning-bg` | `#78350f` | `#92400e` | `#fef3c7` | activity log badge |
| `--color-log-warning-text` | `#fbbf24` | `#fde68a` | `#92400e` | activity log badge |
| `--color-log-error-bg` | `#7f1d1d` | `#991b1b` | `#fee2e2` | activity log badge |
| `--color-log-error-text` | `#f87171` | `#fca5a5` | `#991b1b` | activity log badge |
| `--color-accent-checkbox` | `#3b82f6` | `#60a5fa` | `#2563eb` | CSS `accent-color` on inputs |
| `--color-live-badge` | `#ef4444` | `#f87171` | `#dc2626` | pulsing LIVE badge (unique semantic role) |

---

## Architecture

### ThemeToggle Placement: Route Group

```
app/
  (dj)/
    layout.tsx          ← NEW: ThemeToggle + shared DJ wrapper
    events/             ← MOVED from app/events/ (URL unchanged)
      page.tsx
      [code]/page.tsx   ← remove existing manual ThemeToggle
    account/            ← MOVED from app/account/ (URL unchanged)
      page.tsx
  admin/
    layout.tsx          ← add ThemeToggle to existing sidebar footer slot
  join/                 ← UNTOUCHED
  e/                    ← UNTOUCHED (display/kiosk)
  collect/              ← UNTOUCHED
```

Route groups (`(dj)`) are transparent to Next.js routing — `/events` and `/account` URLs are unchanged. All future DJ pages added under `(dj)/` automatically receive ThemeToggle with no per-page imports.

The `(dj)/layout.tsx` is also a candidate home for the auth redirect guard if it is currently duplicated across individual pages.

### Excluded from theming

The following have intentional design languages independent of the theme system and must not be modified:

- `app/e/[code]/display/` — kiosk display page
- `app/join/` — guest join page  
- `app/collect/[code]/` — pre-event collection (Tower UI)
- Camelot wheel component — fixed color semantics (music theory)
- Tower guest UI constants (`#06060a`, `#00f0ff`, `#ff2bd6`) in `components/` and `app/collect/`

---

## Migration: 2 PRs

### PR1 — Token foundation + `globals.css` (zero visual change)

**Files touched:** `lib/theme-vars.ts`, `app/globals.css`

1. Expand `lib/theme-vars.ts` from 6 → 37 tokens
   - Dark values: final production values
   - High-contrast values: full 37-token set
   - Daylight values: identical to dark at this stage (placeholders — light mode ships in PR2)
2. Replace every hardcoded hex/rgba in `app/globals.css` with CSS vars
   - ~40 replacements across structural classes, badges, buttons, admin sidebar, log levels, scrollbar, toggle switch, identity bar
3. **Invariant:** dark theme must be pixel-identical to pre-PR1. CI passes. No light mode yet.

### PR2 — TSX inline styles + light theme + route group

**Files touched:** `lib/theme-vars.ts`, `app/(dj)/layout.tsx` *(new)*, `app/(dj)/events/page.tsx`, `app/(dj)/events/[code]/page.tsx`, `app/(dj)/account/page.tsx`, `app/admin/layout.tsx`, ~30 additional TSX files with inline style colors

1. Create `app/(dj)/layout.tsx` with ThemeToggle in header area
2. Move `app/events/` → `app/(dj)/events/`, `app/account/` → `app/(dj)/account/`
3. Remove manual ThemeToggle from `app/(dj)/events/[code]/page.tsx` (now inherited from layout)
4. Add ThemeToggle to `app/admin/layout.tsx` sidebar footer
5. Systematic grep pass — replace all inline style hardcoded colors in TSX with CSS vars
   - Priority order: `#9ca3af`/`#aaa`/`#888` → `var(--text-secondary)` (141 hits), `#3b82f6` → `var(--color-primary)` (52 hits), `#ef4444` → `var(--color-danger)` (29 hits), etc.
6. Fill complete daylight values in `lib/theme-vars.ts` (all 37 tokens)
7. Update high-contrast to full 37-token set
8. Update ThemeToggle label: "daylight" → "Day"
9. Manual QA: events list, event detail, admin overview, admin users, admin settings, admin integrations, account page — all in daylight mode

---

## Out of Scope

- Kiosk display page theming
- Guest-facing pages (join, collect, Tower UI)
- Camelot wheel
- Any new features or layout changes beyond ThemeToggle placement
- Animation or motion changes
- Typography changes

---

## Testing

- **PR1:** `npm run lint` + `npx tsc --noEmit` + `npm test -- --run`. Dark theme visual spot-check (must be identical to pre-PR1).
- **PR2:** Same CI suite. Manual light mode QA across all DJ + admin pages. Check: no invisible text, no invisible cards, no hardcoded `rgba(255,255,255,x)` surfaces remaining on DJ/admin pages.

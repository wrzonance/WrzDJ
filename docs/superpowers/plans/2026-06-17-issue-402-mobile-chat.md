# Issue #402 — Mobile Chat View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the WrzDJSet agent chat a usable mobile surface — a floating "Agent" FAB
(carrying the critique grade) that opens a full-viewport overlay with the complete agent
experience — without making the desktop 3-column workspace responsive.

**Architecture:** Extract `ChatSidebar`'s chat logic into a `useAgentChat` hook and a
presentational `ChatPanelBody`. The desktop `ChatSidebar` and a new `MobileAgentOverlay`
both wrap `ChatPanelBody`. A `useIsMobile` hook (matchMedia 720px, hydration-guarded) lets
`page.tsx` render EITHER the desktop sidebar OR the mobile overlay — never both — so only
one `useAgentChat` mounts and fetches.

**Tech Stack:** Next.js / React 19, TypeScript (strict), vanilla CSS modules
(`setbuilder.module.css`), Vitest + Testing Library (jsdom).

## Global Constraints

- Frontend only. No backend/API changes.
- Vanilla CSS + inline React styles — NO Tailwind, NO UI framework. Dark theme
  (bg `#0a0a0a`, cards `#1a1a1a`, text `#ededed`), mobile-first.
- ≥44px touch targets; single-column stacking on mobile (consistent with #438).
- Desktop layout (≥721px) must remain byte-for-byte unchanged.
- Existing `ChatSidebar.test.tsx` must stay green (it is the desktop regression guard).
- Honor vitest coverage gates: branches 68 / functions 65 / lines 78 / statements 77.
- Commit format: `feat(setbuilder): …` ending with
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## File Structure

- `components/useIsMobile.ts` (new) — matchMedia hook, hydration-guarded.
- `components/useAgentChat.ts` (new) — all chat state + actions + `formatAgentError`.
- `components/ChatPanelBody.tsx` (new) — presentational body (context meta, critique card,
  error, message list w/ tool cards + score updates, composer w/ suggestion chips + input).
  Houses `ToolCard`, `CritiqueCard`, `PersonaToggle` and the pure render helpers
  (`flagTone`, `formatFlag`, `lockSkipReasons`, `critiqueFlags`).
- `components/MobileAgentOverlay.tsx` (new) — FAB + full-viewport overlay wrapping the body.
- `components/ChatSidebar.tsx` (modify) — thin desktop shell wrapping the body.
- `[setId]/page.tsx` (modify) — pick sidebar OR overlay via `useIsMobile`.
- `setbuilder.module.css` (modify) — FAB, overlay, mobile legibility, hide desktop chat col.
- `components/__tests__/useIsMobile.test.tsx` (new)
- `components/__tests__/ChatPanelBody.test.tsx` (new)
- `components/__tests__/MobileAgentOverlay.test.tsx` (new)

---

## Task 1: `useIsMobile` hook

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/useIsMobile.ts`
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/useIsMobile.test.tsx`

**Interfaces:**
- Produces: `useIsMobile(maxWidthPx?: number = 720): boolean` — `false` on first render
  (SSR-safe), reflects `matchMedia('(max-width: {n}px)').matches` after mount, updates on
  `change`.

- [ ] Step 1: Write failing test (default false, true when match, reacts to change event).
- [ ] Step 2: Run — expect FAIL (module missing).
- [ ] Step 3: Implement hook: `useState(false)` + `useEffect` subscribing to the MediaQueryList.
- [ ] Step 4: Run — expect PASS.
- [ ] Step 5: Commit.

## Task 2: `useAgentChat` hook + `ChatPanelBody`, refactor `ChatSidebar`

**Files:**
- Create: `components/useAgentChat.ts`, `components/ChatPanelBody.tsx`
- Modify: `components/ChatSidebar.tsx`
- Create: `components/__tests__/ChatPanelBody.test.tsx`
- Guard: `components/__tests__/ChatSidebar.test.tsx` (must stay green, unchanged)

**Interfaces:**
- Produces: `useAgentChat(setId: number, opts: { open: boolean; refreshToken?: number;
  onMutationApplied: () => void }): AgentChatController` where `AgentChatController = {
  persona, setPersona, critique, entries, historyMeta, input, setInput, busy, error,
  suggestions, send }`.
- Produces: `ChatPanelBody({ chat: AgentChatController })` — presentational; owns scrollRef +
  autoscroll; renders meta/critique/error/messages/composer.
- Produces: `PersonaToggle({ persona, onChange })` exported from `ChatPanelBody.tsx`.
- Consumes (ChatSidebar): `useAgentChat`, `ChatPanelBody`, `PersonaToggle`.

- [ ] Step 1: Add `ChatPanelBody.test.tsx` — render with a stub controller (no API): asserts
  critique-card, a tool card, suggestion chip click → `send(chip)`, Send button → `send()`.
- [ ] Step 2: Run — expect FAIL (module missing).
- [ ] Step 3: Extract `useAgentChat.ts` (move state/effects/send + `formatAgentError`).
- [ ] Step 4: Create `ChatPanelBody.tsx` (move ToolCard/CritiqueCard/PersonaToggle + render
  helpers + body JSX + scrollRef/autoscroll).
- [ ] Step 5: Rewrite `ChatSidebar.tsx` to a thin shell (collapsed button + header w/
  PersonaToggle + Collapse) wrapping `ChatPanelBody`, driven by `useAgentChat`.
- [ ] Step 6: Run `ChatPanelBody.test.tsx` AND `ChatSidebar.test.tsx` — expect PASS (both).
- [ ] Step 7: Commit.

## Task 3: `MobileAgentOverlay`

**Files:**
- Create: `components/MobileAgentOverlay.tsx`
- Create: `components/__tests__/MobileAgentOverlay.test.tsx`

**Interfaces:**
- Consumes: `useAgentChat`, `ChatPanelBody`, `PersonaToggle`.
- Produces: `MobileAgentOverlay({ setId, refreshToken?, onMutationApplied })` — renders a FAB
  (grade badge from critique) that toggles a full-viewport overlay; overlay header has a
  back/close affordance + grade + PersonaToggle; body is `ChatPanelBody`. History loads only
  while the overlay is open.

- [ ] Step 1: Write failing test (mock `@/lib/api` like ChatSidebar.test): FAB shows grade
  after critique resolves; click FAB → overlay (critique-card) appears; type + Send →
  `chatWithSetAgent` called; close affordance hides the overlay.
- [ ] Step 2: Run — expect FAIL (module missing).
- [ ] Step 3: Implement the overlay.
- [ ] Step 4: Run — expect PASS.
- [ ] Step 5: Commit.

## Task 4: Wire `page.tsx` + CSS

**Files:**
- Modify: `[setId]/page.tsx`
- Modify: `setbuilder.module.css`

**Interfaces:**
- Consumes: `useIsMobile`, `MobileAgentOverlay`, existing `ChatSidebar`.

- [ ] Step 1: In `page.tsx`, compute `isMobile = useIsMobile()`. Render the `.panelChat`
  `<ChatSidebar>` only when `!isMobile`; render `<MobileAgentOverlay>` (outside the grid)
  only when `isMobile`. Single `useAgentChat` mount either way.
- [ ] Step 2: CSS — at `max-width:720px`: hide `.panelChat`, collapse `.workspace` grid to a
  single column (pool/transport/timeline stack), style `.agentFab` (≥44px, fixed
  bottom-right, grade badge) and `.agentOverlay` (fixed inset:0 full-viewport, header w/ back +
  grade + persona, scrollable body, sticky composer); ensure tool cards / critique / chips are
  legible (single-column, ≥44px taps).
- [ ] Step 3: Run full FE CI (`npm run lint && npx tsc --noEmit && npm test -- --run`) — PASS,
  coverage gates met. `git checkout next-env.d.ts` if the build touched it.
- [ ] Step 4: Commit.

---

## Self-Review

- **Spec coverage:** mobile chat surface (overlay) ✓; tool cards legible (Task 4 CSS) ✓;
  suggestion chips touch-usable (≥44px, Task 4) ✓; critique card adapted (single-column) ✓;
  single fetch (Task 4 single-mount) ✓; desktop unchanged (PersonaToggle keeps header
  identical; CSS changes gated behind 720px) ✓.
- **Placeholder scan:** none — each task names exact files, interfaces, and test intent.
- **Type consistency:** `AgentChatController` shape and `useAgentChat`/`ChatPanelBody`/
  `PersonaToggle`/`MobileAgentOverlay` signatures are consistent across Tasks 1-4.

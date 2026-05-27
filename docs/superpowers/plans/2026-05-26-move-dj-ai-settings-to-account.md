# Move DJ AI connector/model settings into the account page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the DJ-facing AI connector UI (connect/test/rotate/delete, model hint, Hermes onboarding) from `/settings/ai` into the existing `/account` page, redirect the old route, and update tests — keeping the admin `/admin/ai` UI untouched.

**Architecture:** Extract the existing `/settings/ai` page body into a reusable client component `components/AiProvidersSection.tsx`. Render it as a third inline card section inside `/account`. Delete the old `/settings/ai` route and add a server-side redirect in `next.config.js` so bookmarks 308 to `/account`. Preserve fail-closed policy behavior verbatim (it moves with the component).

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript (strict), vanilla CSS + inline styles, Vitest + Testing Library.

---

### Task 1: Extract AI providers UI into a reusable component

**Files:**
- Create: `dashboard/components/AiProvidersSection.tsx`
- Reference (source of logic): `dashboard/app/(dj)/settings/ai/page.tsx`

The component contains ALL connector logic from the current page: policy fetch (`fetchPolicySoft` → `getLlmPolicy`), `allowedTypes` fail-closed memo, connectors list, create form (all provider types incl. bedrock/azure/openai_compatible/openrouter dropdown), test, delete. It must NOT include the page-level `<main>` wrapper, the "← Dashboard" link header, the `useAuth`/`useRouter` auth-redirect (those stay at the page level — `/account` already does the auth gate). It exports a default React component `AiProvidersSection` rendering a `<section>` that begins with an `<h2>AI / Model providers</h2>` and the existing intro paragraph, then "Connected providers" and the add-provider form.

- [ ] **Step 1: Create the component** by moving the body. Keep every form field, label text (e.g. `Provider`, `Display name`, `API key`, `Resource name`, `Bedrock model ID`, `Model (optional)`), the OpenRouter model fetch effect, and the fail-closed `allowedTypes` logic identical so existing test assertions still hold. The top of the rendered output is an intro `<h2>` + `<p>`; the rest is the two `<section>`s. Wrap all of it in a single fragment/section with `style={{ marginTop: '2rem' }}` matching the account-page card rhythm (it will live inside its own card in Task 2, so use a plain wrapper, not a `.card`).

- [ ] **Step 2: Type-check** — `cd dashboard && npx tsc --noEmit`. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add dashboard/components/AiProvidersSection.tsx
git commit -m "refactor(ai): extract AI providers UI into reusable component"
```

---

### Task 2: Render the AI section inside /account and delete old route

**Files:**
- Modify: `dashboard/app/(dj)/account/page.tsx`
- Modify: `dashboard/next.config.js` (add `redirects()`)
- Delete: `dashboard/app/(dj)/settings/ai/page.tsx`
- Delete: `dashboard/app/(dj)/settings/ai/__tests__/page.test.tsx` (logic re-tested via component in Task 3)
- Delete dir if empty: `dashboard/app/(dj)/settings/`

- [ ] **Step 1: Import and render** `AiProvidersSection` in `/account`. Add a third card `<div>` (same wrapper style as Change Email card: `{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginTop: '1.5rem' }`) below Change Email, containing `<AiProvidersSection />`. Widen the page `<main>` maxWidth from `480px` to `720px` so the provider form (which used `720px`) is not cramped.

- [ ] **Step 2: Add redirect** in `next.config.js`:

```js
async redirects() {
  return [
    { source: '/settings/ai', destination: '/account', permanent: true },
  ];
},
```

- [ ] **Step 3: Delete** the old route file, its test, and the now-empty `settings/` dir.

- [ ] **Step 4: Grep** `grep -rn "/settings/ai" dashboard/ --include="*.ts" --include="*.tsx" | grep -v node_modules` → expect no remaining nav/link hits (only possibly api-types doc comments, which are fine).

- [ ] **Step 5: Type-check + lint** — `cd dashboard && npx tsc --noEmit && npm run lint`. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/\(dj\)/account/page.tsx dashboard/next.config.js
git add -u dashboard/app/\(dj\)/settings
git commit -m "feat(ai): move DJ AI settings into account page; redirect old route (#357)"
```

---

### Task 3: Move/adapt the AI tests to the component + account page

**Files:**
- Create: `dashboard/components/__tests__/AiProvidersSection.test.tsx` (port the old settings/ai tests, importing the component instead of the page; drop the `next/navigation`/`useAuth` mocks that the page-level no longer needs but keep `next/link` mock if used)
- Modify: `dashboard/app/(dj)/account/__tests__/page.test.tsx` (add the AI api methods to the `@/lib/api` mock so the section can mount inside the account page without throwing, and assert the AI heading renders)

- [ ] **Step 1: Port connector tests** to `AiProvidersSection.test.tsx` — same assertions (lists connectors, fail-closed hides providers, policy filtering, azure/bedrock/openrouter fields, test, delete). Render `<AiProvidersSection />` directly. Keep `vi.mock('next/link', ...)` if the component still uses `Link` (it should NOT — Link header stays on the page; remove the import). Mock `@/lib/api` methods used: `listLlmConnectors`, `getLlmPolicy`, `createLlmConnector`, `testLlmConnector`, `deleteLlmConnector`, `listOpenRouterModels`, `getAdminLlmPolicy` (for the "reads DJ-scoped not admin" test).

- [ ] **Step 2: Update account page test** — extend the existing `vi.mock('@/lib/api', ...)` to add `listLlmConnectors: () => Promise.resolve([])` and `getLlmPolicy: () => Promise.reject(new Error('x'))` (fail-closed, no extra UI). Add a test: AI heading `AI / Model providers` is in the document.

- [ ] **Step 3: Run frontend tests** — `cd dashboard && npm test -- --run`. Expected: PASS, coverage thresholds met.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/__tests__/AiProvidersSection.test.tsx dashboard/app/\(dj\)/account/__tests__/page.test.tsx
git commit -m "test(ai): relocate AI provider tests to component + account page (#357)"
```

---

## Self-Review

- Spec coverage: relocate UI (Task 1+2) ✓; update nav/links (Task 2 grep — only the page itself referenced it) ✓; redirect old route (Task 2) ✓; admin /admin/ai untouched (not touched by any task) ✓; tests moved (Task 3) ✓; fail-closed preserved (logic moved verbatim, retested) ✓.
- Placeholder scan: none.
- Type consistency: component name `AiProvidersSection` used consistently in Tasks 1–3.

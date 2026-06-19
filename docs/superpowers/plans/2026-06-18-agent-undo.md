# Agent-action Undo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WrzDJSet agent chat mutations undoable by routing them through the dashboard's existing document-history stack, so `Ctrl+Z` / ↶ reverts an agent edit exactly like a manual one.

**Architecture:** Frontend-only. Extend `useSetDocumentHistory.commit` with an optional `shouldRecord(result)` predicate (backward-compatible), then wrap `useAgentChat.send`'s chat call in `commit` so a mutating turn becomes one undo entry. The `after`-snapshot publish drives the existing `snapshotVersion` reload, replacing the agent path's `onMutationApplied`/`refreshToken` refresh. No backend change — `build_snapshot`/`restore_snapshot` + `GET`/`PUT /sets/{id}/document` already exist.

**Tech Stack:** Next.js / React 19, TypeScript (strict), Vitest + @testing-library/react. Spec: `docs/superpowers/specs/2026-06-18-agent-undo-design.md`. Issue: #493.

## Global Constraints

- **No backend changes.** Only `dashboard/` files.
- **Backward-compatible `commit`.** Existing two-arg callers (manual edits in `page.tsx`, `BuilderWorkspace`, `PoolPanel`) must keep identical behavior; the new third parameter is optional and defaults to "always record".
- **Frontend CI must pass between tasks:** from `dashboard/`, `npm run lint`, `npx tsc --noEmit`, and `npm test -- --run` all green (vitest coverage gate: 68% branches / 65% functions / 78% lines / 77% statements).
- **Vanilla CSS / inline styles only** — no Tailwind, no UI framework (no new UI is added here regardless).
- **All paths are relative to the repo root** `/home/adam/github/WrzDJ`. Run `npm` commands from `dashboard/`.

---

### Task 1: Add `shouldRecord` predicate to `commit`

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/useSetDocumentHistory.ts` (type at line 9; `commit` at lines 129-156)
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/useSetDocumentHistory.test.tsx`

**Interfaces:**
- Produces: `BuilderCommit = <T>(label: string, action: () => Promise<T> | T, shouldRecord?: (result: T) => boolean) => Promise<T>`. When `shouldRecord(result)` is false, `commit` publishes the new snapshot but adds no undo entry and leaves the redo stack intact. Default predicate is `() => true` (unchanged behavior).

- [ ] **Step 1: Add the failing tests**

In `__tests__/useSetDocumentHistory.test.tsx`, add a no-record button to `Harness` (inside the `<div>`, after the existing `commit` button on line 59):

```tsx
      <button onClick={() => void history.commit('No-record', mutate, () => false)}>
        commit-norecord
      </button>
```

Then add these two tests inside the `describe('useSetDocumentHistory', ...)` block:

```tsx
  it('publishes the new snapshot but records no undo entry when shouldRecord is false', async () => {
    let serverDoc = snapshot(null);
    mockApi.getSetDocument.mockImplementation(() => Promise.resolve(clone(serverDoc)));
    mockApi.putSetDocument.mockImplementation((_setId: number, doc: SetDocumentSnapshot) => {
      serverDoc = clone(doc);
      return Promise.resolve(clone(serverDoc));
    });

    render(
      <Harness mutate={() => Promise.resolve().then(() => void (serverDoc = snapshot(8.5)))} />,
    );
    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('none'));

    fireEvent.click(screen.getByText('commit-norecord'));

    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('8.5'));
    expect(screen.getByTestId('undo-depth')).toHaveTextContent('0');
  });

  it('leaves the redo stack intact when a non-recording commit runs', async () => {
    let serverDoc = snapshot(null);
    mockApi.getSetDocument.mockImplementation(() => Promise.resolve(clone(serverDoc)));
    mockApi.putSetDocument.mockImplementation((_setId: number, doc: SetDocumentSnapshot) => {
      serverDoc = clone(doc);
      return Promise.resolve(clone(serverDoc));
    });

    render(
      <Harness mutate={() => Promise.resolve().then(() => void (serverDoc = snapshot(8.5)))} />,
    );
    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('none'));

    fireEvent.click(screen.getByText('commit')); // records, target -> 8.5
    await waitFor(() => expect(screen.getByTestId('undo-depth')).toHaveTextContent('1'));
    fireEvent.click(screen.getByText('undo')); // redo-depth -> 1
    await waitFor(() => expect(screen.getByTestId('redo-depth')).toHaveTextContent('1'));

    fireEvent.click(screen.getByText('commit-norecord')); // must not clear redo
    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('8.5'));
    expect(screen.getByTestId('redo-depth')).toHaveTextContent('1');
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `dashboard/`): `npm test -- --run useSetDocumentHistory`
Expected: the two new tests FAIL — the current `commit` ignores the third arg and always records / clears redo, so `undo-depth` becomes `1` and `redo-depth` becomes `0`.

- [ ] **Step 3: Implement the predicate**

In `useSetDocumentHistory.ts`, change the `BuilderCommit` type (line 9) to:

```ts
export type BuilderCommit = <T>(
  label: string,
  action: () => Promise<T> | T,
  shouldRecord?: (result: T) => boolean,
) => Promise<T>;
```

Replace the `commit` callback body (lines 129-156) with (only the signature default and the `if (shouldRecord(result))` guard change):

```ts
  const commit: BuilderCommit = useCallback(
    async (label, action, shouldRecord = () => true) => {
      if (!beginOperation()) {
        throw new Error('Another document history operation is already in progress');
      }
      try {
        const before = await fetchCurrent();
        setIsSaving(true);
        setIsDirty(true);
        setSaveError(null);
        const result = await action();
        const after = await api.getSetDocument(setId);
        if (shouldRecord(result)) {
          setUndoStack((prev) => [...prev, { label, snapshot: before }].slice(-50));
          setRedoStack([]);
        }
        publishSnapshot(after);
        setLastSavedAt(new Date());
        setIsDirty(false);
        return result;
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : 'Save failed');
        throw error;
      } finally {
        setIsSaving(false);
        finishOperation();
      }
    },
    [beginOperation, fetchCurrent, finishOperation, publishSnapshot, setId],
  );
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `dashboard/`): `npm test -- --run useSetDocumentHistory`
Expected: PASS — including the pre-existing record/undo/redo and autosave tests (backward compatibility).

- [ ] **Step 5: Type-check and commit**

```bash
cd dashboard && npx tsc --noEmit && npm run lint
git add "dashboard/app/(dj)/setbuilder/components/useSetDocumentHistory.ts" \
        "dashboard/app/(dj)/setbuilder/components/__tests__/useSetDocumentHistory.test.tsx"
git commit -m "feat(setbuilder): add shouldRecord predicate to history commit (#493)"
```

---

### Task 2: Bridge `useAgentChat.send` through `commit`

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/useAgentChat.ts` (options at lines 64-71; `send` at lines 142-183)
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/useAgentChat.test.tsx`

**Interfaces:**
- Consumes: `BuilderCommit` from Task 1.
- Produces: `useAgentChat(setId, { open, refreshToken?, onMutationApplied, commit? })`. When `commit` is provided, a send wraps the chat call in `commit('Agent · <message>', action, didMutate)` and does NOT call `onMutationApplied`. When `commit` is absent, behavior is unchanged (calls `onMutationApplied` on a mutating turn). `didMutate(res) = [...res.tool_calls, ...res.assistant_message.tool_calls].some(t => t.mutating)`.

- [ ] **Step 1: Add the failing tests**

In `__tests__/useAgentChat.test.tsx`, add these tests inside the `describe('useAgentChat', ...)` block. (Helper `assistantMessage` and `mockApi` already exist in the file.)

```tsx
  function mutatingResult() {
    return {
      message: 'Rebuilt.',
      assistant_message: assistantMessage({
        tool_calls: [
          {
            id: 'a1',
            name: 'autobuild',
            args: {},
            rationale: 'Rebuild from pool',
            result: {},
            mutating: true,
            display_summary: 'Rebuilt the set.',
          },
        ],
      }),
      tool_calls: [],
      slots: [],
      affected_transition_scores: [],
    };
  }

  it('routes a mutating turn through commit as one labeled undo entry', async () => {
    mockApi.chatWithSetAgent.mockResolvedValue(mutatingResult());
    const commit = vi.fn((_label: string, action: () => Promise<unknown>) => action());
    const onMutationApplied = vi.fn();

    const { result } = renderHook(() =>
      useAgentChat(9, { open: true, onMutationApplied, commit }),
    );
    await act(async () => {
      await result.current.send('rebuild the set');
    });

    expect(commit).toHaveBeenCalledTimes(1);
    const [label, , shouldRecord] = commit.mock.calls[0] as [
      string,
      unknown,
      (r: { tool_calls: { mutating: boolean }[]; assistant_message: { tool_calls: { mutating: boolean }[] } }) => boolean,
    ];
    expect(label).toBe('Agent · rebuild the set');
    expect(shouldRecord({ tool_calls: [], assistant_message: { tool_calls: [{ mutating: true }] } })).toBe(true);
    expect(shouldRecord({ tool_calls: [], assistant_message: { tool_calls: [{ mutating: false }] } })).toBe(false);
    expect(onMutationApplied).not.toHaveBeenCalled();
  });

  it('falls back to onMutationApplied when no commit is provided', async () => {
    mockApi.chatWithSetAgent.mockResolvedValue(mutatingResult());
    const onMutationApplied = vi.fn();

    const { result } = renderHook(() => useAgentChat(9, { open: true, onMutationApplied }));
    await act(async () => {
      await result.current.send('rebuild the set');
    });

    expect(onMutationApplied).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `dashboard/`): `npm test -- --run useAgentChat`
Expected: the "routes through commit" test FAILS — `useAgentChat` does not yet accept or call `commit` (so `commit` is never invoked). The fallback test passes already (current behavior).

- [ ] **Step 3: Implement the bridge**

In `useAgentChat.ts`, add imports near the top (after line 5):

```ts
import type { AgentChatOut } from '@/lib/api-types';
import type { BuilderCommit } from './useSetDocumentHistory';
```

Change the options destructuring + type (lines 66-70) to include `commit`:

```ts
  {
    open,
    refreshToken = 0,
    onMutationApplied,
    commit,
  }: {
    open: boolean;
    refreshToken?: number;
    onMutationApplied: () => void;
    commit?: BuilderCommit;
  },
```

Replace the body of the `try` block in `send` (lines 160-175) with:

```ts
    try {
      const didMutate = (res: AgentChatOut) =>
        [...res.tool_calls, ...res.assistant_message.tool_calls].some((tool) => tool.mutating);
      const label = `Agent · ${message.slice(0, 40)}`;
      const action = () => api.chatWithSetAgent(setId, { message });
      const result = commit ? await commit(label, action, didMutate) : await action();
      setEntries((prev) => [
        ...prev.filter((entry) => entry.id !== pendingEntry.id),
        {
          id: pendingEntry.id,
          role: 'user',
          content: message,
          display_summary: null,
          tool_calls: [],
          affected_transition_scores: [],
        },
        result.assistant_message,
      ]);
      // With commit, the published snapshot bumps snapshotVersion and the
      // workspace reloads; only the no-history fallback needs the manual refresh.
      if (!commit && didMutate(result)) onMutationApplied();
    } catch (err) {
```

(The `catch`/`finally` blocks on lines 176-182 are unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `dashboard/`): `npm test -- --run useAgentChat`
Expected: PASS — both new tests and all existing `useAgentChat` tests.

- [ ] **Step 5: Type-check and commit**

```bash
cd dashboard && npx tsc --noEmit && npm run lint
git add "dashboard/app/(dj)/setbuilder/components/useAgentChat.ts" \
        "dashboard/app/(dj)/setbuilder/components/__tests__/useAgentChat.test.tsx"
git commit -m "feat(setbuilder): bridge agent chat turns into the undo stack (#493)"
```

---

### Task 3: Thread `commit` through the chat surfaces and the page

**Files:**
- Modify: `dashboard/app/(dj)/setbuilder/components/ChatSidebar.tsx` (props lines 12-25)
- Modify: `dashboard/app/(dj)/setbuilder/components/MobileAgentOverlay.tsx` (props lines 15-28)
- Modify: `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` (ChatSidebar mount lines 465-471; MobileAgentOverlay mount lines 476-480)
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx`

**Interfaces:**
- Consumes: `useAgentChat`'s `commit?` option (Task 2), `history.commit: BuilderCommit` (already mounted in `page.tsx` line 93).

- [ ] **Step 1: Add the failing test**

In `__tests__/ChatSidebar.test.tsx`, add this test inside the `describe('ChatSidebar', ...)` block. It mounts the sidebar with a fake `commit` and asserts the bridge is used. (The file already mocks `api` with `critiqueSet`, `chatWithSetAgent`, `getSetAgentHistory` and sets `chatWithSetAgent` to a mutating `swap_slots` result in `beforeEach`.)

```tsx
  it('routes sends through the provided commit instead of onMutationApplied', async () => {
    const commit = vi.fn((_label: string, action: () => Promise<unknown>) => action());
    const onMutationApplied = vi.fn();
    render(
      <ChatSidebar
        setId={5}
        open
        onToggle={() => {}}
        onMutationApplied={onMutationApplied}
        commit={commit}
      />,
    );
    await waitFor(() => expect(mockApi.getSetAgentHistory).toHaveBeenCalledWith(5));

    fireEvent.change(screen.getByPlaceholderText(/tell the agent/i), {
      target: { value: 'swap the opener' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
    expect(commit.mock.calls[0][0]).toBe('Agent · swap the opener');
    expect(onMutationApplied).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `dashboard/`): `npm test -- --run ChatSidebar`
Expected: FAIL — `ChatSidebar` does not yet accept a `commit` prop, so `commit` is never called (and tsc would reject the prop).

- [ ] **Step 3: Add the `commit` prop to both chat surfaces**

In `ChatSidebar.tsx`, add the import (after line 4):

```ts
import type { BuilderCommit } from './useSetDocumentHistory';
```

Change the props (lines 12-25) to add `commit` and pass it through:

```tsx
export default function ChatSidebar({
  setId,
  open,
  onToggle,
  refreshToken = 0,
  onMutationApplied,
  commit,
}: {
  setId: number;
  open: boolean;
  onToggle: () => void;
  refreshToken?: number;
  onMutationApplied: () => void;
  commit?: BuilderCommit;
}) {
  const chat = useAgentChat(setId, { open, refreshToken, onMutationApplied, commit });
```

In `MobileAgentOverlay.tsx`, add the same import (after line 5) and change the props (lines 15-28):

```tsx
export default function MobileAgentOverlay({
  setId,
  refreshToken = 0,
  onMutationApplied,
  commit,
}: {
  setId: number;
  refreshToken?: number;
  onMutationApplied: () => void;
  commit?: BuilderCommit;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);
  const chat = useAgentChat(setId, { open, refreshToken, onMutationApplied, commit });
```

- [ ] **Step 4: Pass `history.commit` from the page**

`commit` is gated on `historyEnabled` (page.tsx line 92: `!isLoading && isAuthenticated && role !== 'pending'`). When history is disabled, `history.commit` throws on use (`fetchCurrent` rejects with "Document history is not ready"), so pass `undefined` in that case and `useAgentChat` falls back to `onMutationApplied`.

In `[setId]/page.tsx`, add `commit={historyEnabled ? history.commit : undefined}` to the `<ChatSidebar>` mount (after line 470):

```tsx
            <ChatSidebar
              setId={Number(setId)}
              open={chatOpen}
              onToggle={() => setChatOpen((open) => !open)}
              refreshToken={refreshToken}
              onMutationApplied={() => setRefreshToken((v) => v + 1)}
              commit={historyEnabled ? history.commit : undefined}
            />
```

And to the `<MobileAgentOverlay>` mount (after line 479):

```tsx
        <MobileAgentOverlay
          setId={Number(setId)}
          refreshToken={refreshToken}
          onMutationApplied={() => setRefreshToken((v) => v + 1)}
          commit={historyEnabled ? history.commit : undefined}
        />
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `dashboard/`): `npm test -- --run ChatSidebar`
Expected: PASS — the new test and all existing `ChatSidebar` tests (which omit `commit` and exercise the unchanged fallback path).

- [ ] **Step 6: Full frontend CI**

Run (from `dashboard/`):

```bash
npm run lint
npx tsc --noEmit
npm test -- --run
```

Expected: all green, coverage gate met. If `page.test.tsx` mocks `ChatSidebar`/`MobileAgentOverlay`, it is unaffected by the new optional prop; if it renders them, the optional `commit` defaults to `undefined` (fallback) and tests stay green.

- [ ] **Step 7: Commit**

```bash
git add "dashboard/app/(dj)/setbuilder/components/ChatSidebar.tsx" \
        "dashboard/app/(dj)/setbuilder/components/MobileAgentOverlay.tsx" \
        "dashboard/app/(dj)/setbuilder/[setId]/page.tsx" \
        "dashboard/app/(dj)/setbuilder/components/__tests__/ChatSidebar.test.tsx"
git commit -m "feat(setbuilder): wire history.commit into the agent chat surfaces (#493)"
```

---

## Manual verification (after Task 3)

1. Start the app, open a set in the builder, open the agent chat.
2. Ask the agent to make a change (e.g. "swap the first two tracks"). Confirm the timeline updates.
3. Press `Ctrl+Z` (or click ↶). Confirm the change reverts and the ↶ tooltip read `Agent · swap the first two tracks` before the undo.
4. Ask the agent a non-mutating question (e.g. "why is transition 2 flagged?"). Confirm no new undo entry appears (↶ depth unchanged).

## What this unblocks

Once merged, every agent mutation — including the destructive Family 3 tools (`autobuild`/`run_pass1`, `fill_to_duration`, #491) and Family 4 imports — is undoable for free, because the captured snapshot is the whole document. This satisfies the #491 "Task 0" gate; those tools then need only their standard tool implementation, no per-tool undo wiring.

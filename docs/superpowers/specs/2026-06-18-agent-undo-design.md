# Agent-action undo — design spec

**Issue:** #493 · **Gates:** #491 (Family 3 destructive tools), #442 Family 4 (imports)
**Date:** 2026-06-18 · **Status:** approved (brainstorm)

## Problem

WrzDJSet agent chat mutations bypass the dashboard's existing undo system. A DJ
can `Ctrl+Z` a manual drag-reorder but **cannot** undo an agent edit. The
destructive Family 3 tools (`autobuild`/`run_pass1`, `fill_to_duration`) and
Family 4 imports rewrite or mass-mutate the set, and have no recovery path — so
they are blocked until undo covers agent actions.

## Key finding: undo already exists

The dashboard already ships a complete undo/redo system in
`dashboard/app/(dj)/setbuilder/components/useSetDocumentHistory.ts`:

- A client-side 50-deep snapshot stack (`undoStack`/`redoStack`), each entry
  `{ label, SetDocumentSnapshot }`.
- `Ctrl/Cmd+Z` / `Shift+Z` / `Ctrl+Y` shortcuts + a `HistoryControls` ↶/↷ toolbar
  with depth badges and next-action labels.
- A `commit(label, action)` pattern: manual edits wrap their API call so a
  before-snapshot is captured and pushed for undo.
- Restore via the existing `PUT /sets/{id}/document` → `document_snapshot.restore_snapshot`
  (full delete-and-recreate of slots/pool/curve with `pool:` id remapping).

The **only** gap: agent chat mutations (`useAgentChat.send`) do not go through
`commit()`. They bump a `refreshToken` to reload slots, so agent changes never
enter the undo stack.

This work is therefore a **bridge into the existing stack**, not a new undo
system. No backend change is required — `build_snapshot`/`restore_snapshot` and
`GET`/`PUT /sets/{id}/document` (issue #395) already suffice.

## Decisions (locked)

1. **Unified global undo.** A mutating agent turn pushes one entry onto the same
   stack manual edits use; `Ctrl+Z` / ↶ undoes it identically. No separate
   per-message undo concept.
2. **Frontend bridge via `commit()`.** The pre-mutation snapshot is captured
   client-side by the existing `commit` path. No backend change, no new response
   field.
3. **Granularity: one undo entry per mutating agent turn** (the chat turn is the
   DJ's unit of action), not per tool.
4. **Scope: every mutating agent turn is undoable** (consistent with manual
   edits), not destructive-tools-only. The `shouldRecord` predicate makes this
   the simplest implementation as well as the most consistent UX.

## Design

### Change A — extend `commit` with a `shouldRecord` predicate

`useSetDocumentHistory.commit` currently always pushes an undo entry. Add an
optional predicate so a wrapped call records only when it actually mutated:

```ts
type BuilderCommit = <T>(
  label: string,
  action: () => Promise<T> | T,
  shouldRecord?: (result: T) => boolean, // default: () => true
) => Promise<T>;
```

Inside `commit`, after `const result = await action()` and capturing `after`,
push `{ label, snapshot: before }` to `undoStack` **only if**
`shouldRecord(result)`; always `publishSnapshot(after)`, clear redo, and reset
dirty/save state as today. Existing two-arg callers are unaffected (predicate
defaults to always-record). This is the single behavioral change in the hook.

### Change B — bridge `useAgentChat.send`

Thread the page-level `commit` (and `enabled` flag) down to the chat surface
(`ChatSidebar` / `MobileAgentOverlay` → `useAgentChat`), replacing the current
`onMutationApplied` refresh callback. In `send`, wrap the chat call:

```ts
const mutated = (res: AgentChatOut) =>
  [...res.tool_calls, ...res.assistant_message.tool_calls].some((t) => t.mutating);

const result = await commit(
  `Agent · ${truncate(message, 40)}`,
  () => api.chatWithSetAgent(setId, { message }),
  mutated,
);
```

A mutating turn → one undo entry labeled e.g. `Agent · rebuild the set`,
undoable with the same `Ctrl+Z` / ↶ as a manual drag. A pure-conversation turn →
no entry. The `after` publish bumps `snapshotVersion`, which already drives the
`BuilderWorkspace` reload — so the agent path's separate `onMutationApplied` /
`refreshToken` refresh is **removed** (a single refresh path, not two).

### Why this covers Family 3 and Family 4 for free

`SetDocumentSnapshot` is the whole document — settings, slots, curve points, and
**pool**. So:

- `autobuild` / `fill_to_duration` rewrite slots → undo restores the prior order.
- `import_from_event` / `import_from_tidal` add pool tracks → undo restores the
  pre-import pool (`restore_snapshot` deletes and recreates the pool).

No per-tool undo wiring is ever needed. Any current or future agent mutation is
undoable the moment it ships. This satisfies the #491 "Task 0" gate.

## Edge cases & error handling

- **Lock during LLM latency.** `commit` holds the single-operation lock for the
  whole turn, so manual undo/edit is blocked while the agent runs. Acceptable —
  chat input is already disabled while `busy`. Deliberate, not worked around.
- **History disabled / not loaded.** If `commit` is unavailable (history hook
  `enabled === false`, or the document has not loaded yet), `send` falls back to
  today's behavior (send + reload, no undo entry) rather than throwing.
- **Failed turn.** `commit` already routes errors to `saveError` and pushes
  nothing; the agent error surfaces exactly as today, with no phantom undo entry.
- **Label.** `Agent · <first ~40 chars of the message>` — known up front, reads
  well in the ↶ tooltip and the undo toast (`Undid Agent · …`).

## Testing (frontend, vitest — no backend change)

- `commit` with `shouldRecord` returning `false`: publishes `after`, pushes **no**
  undo entry; returning `true`: pushes exactly one. Existing two-arg callers
  still record.
- `useAgentChat.send` with a mutating response → exactly one undo entry with the
  expected label; with a non-mutating response → zero entries.
- Undo after an agent turn calls `PUT /sets/{id}/document` with the captured
  `before` snapshot (i.e. the turn is reversible end to end).
- History-disabled fallback: `send` does not throw and still posts the chat.

## Scope boundary (YAGNI)

Not building: per-tool undo buttons, a server-side undo log, agent-specific redo
affordances, or multi-turn batching. The unified stack already provides redo,
keyboard shortcuts, depth labels, and autosave.

## Acceptance criteria

- [ ] `commit` accepts an optional `shouldRecord` predicate; two-arg callers
  unchanged.
- [ ] A mutating agent turn produces one undo entry; a non-mutating turn produces
  none.
- [ ] `Ctrl+Z` / ↶ after an agent edit restores the exact pre-turn document.
- [ ] The redundant agent `onMutationApplied`/`refreshToken` refresh is removed;
  the workspace reloads via `snapshotVersion`.
- [ ] Graceful fallback when history is disabled.
- [ ] Frontend test suite green at the configured coverage gate; `tsc`/lint clean.

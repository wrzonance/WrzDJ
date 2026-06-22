# Design — `autobuild` + `fill_to_duration` agent tools (#491, #442 Family 3)

**Date:** 2026-06-21
**Issue:** #491 (epic #442, Family 3 — structural/destructive)
**Branch:** `feat/issue-491-autobuild-fill-duration`

## Why

Family 3 of the WrzDJSet agent toolkit adds the two *wholesale / destructive*
structural tools. The reversible Family 3 tools (`move_range` #481, pairing tools
#482) already shipped; these two are different because they rewrite the timeline
en masse:

- **`autobuild`** — regenerate the entire ordering from the pool + curve.
- **`fill_to_duration`** — keep appending pool tracks until the set reaches its
  target duration.

#442 flagged these as *"higher impact: needs undo UX"* — the original gate. That
gate is now satisfied (see below), so the tools are unblocked.

## The undo gate is already closed (changes #491's Task 0)

#491's written Task 0 assumed a **backend** capture-before-destroy plus a
per-ToolCard *"Undo this rebuild"* button. That is no longer the right design:
**#493 / #494 already shipped a global undo** that snapshots the *whole document*
before every mutating agent turn.

- `useSetDocumentHistory.commit()` captures `before = fetchCurrent()` (full
  document) *before* running the action, then pushes that snapshot onto the undo
  stack when `shouldRecord(result)` is true.
- `useAgentChat.send()` wraps the whole turn in `commit()` with
  `shouldRecord = didMutate` (true when any returned tool call has
  `mutating: true`).

So any mutating agent turn — including a future `autobuild` — is automatically
captured-before and revertible via ⌘Z / the Undo button, **for free**, as long as
the tool lands in `MUTATION_TOOLS`. Building a second, per-tool undo path would
duplicate state the global undo already captures.

**Decision (user-approved):** rely on the existing global undo; do **not** build a
second undo path. Address the real concern — *discoverability* of undo for a
wholesale rebuild — with a small hint on the destructive ToolCards, and prove
safety with a backend snapshot round-trip identity test.

## Architecture & boundaries

Two new mutating tools live in a **new module**
`server/app/services/setbuilder/agent_tools_structural.py`.

Rationale for a new module rather than extending `agent_tools_mutations.py`: that
file is already 500 lines (the house budget edge), and the rule is *never add to a
file already over budget — extract first*. A dedicated module also gives a clean
cohesion boundary: wholesale/structural ops vs. the granular per-slot edits.

Each tool follows the established toolkit contract:

- Signature `_tool_x(db, set_obj, payload) -> tuple[dict[str, Any], set[int]]`.
- `db.flush()`, never `db.commit()` — `chat_with_agent` owns the single per-turn
  commit/rollback so a multi-tool turn stays atomic.
- Owner-scoped structurally: `set_obj` arrives already scoped via
  `set_service.get_owned_set`.
- Member of `MUTATION_TOOLS` → rationale is required *and* the frontend global
  undo records the turn.
- **Never** writes the `requests` table (pinned by a regression test).

## `autobuild`

Thin wrapper over `pass1_deterministic.build_set(db, set_obj)`, which already
honors locked slots (`_locked_slots` → `locked_by_pos`) and saved pairings
(`PAIRING_BOOST_POINTS`), regenerates the order, persists, and rescoring.

**Supporting change:** `build_set` currently commits internally (in
`_persist_slots` and its `recompute_transition_scores` call). Add a
`commit: bool = True` parameter threaded through both, so the agent path calls
`build_set(db, set_obj, commit=False)` (flush only) and the turn owns the commit.
The single existing REST caller (`api/setbuilder.py:672`) keeps the default
`True` → behavior unchanged.

- Result: `{"slot_count": int, "iterations": int}`.
- Affected positions: all slot positions (whole set rescored).
- Spec: a bare `ToolSpec` (only `rationale` required) with a description that
  makes the *wholesale* nature explicit so the model treats it as destructive.

## `fill_to_duration`

- Guard: `set_obj.target_duration_sec` unset → `AgentToolError("Set a target
  duration first")`.
- Estimate the current total from each slot's pool-track `duration_sec`
  (fallback `AVG_TRACK_LENGTH_SEC` for missing values).
- Append **unused** pool tracks (not already referenced by a slot's `track_id`),
  in deterministic pool order, via the existing
  `_insert_track_at(db, set_obj, track, position)` primitive at the tail — which
  already refuses to displace a locked slot.
- Stop when: estimated total ≥ target **OR** pool exhausted **OR** a hard cap
  `MAX_FILL_INSERTS` is reached (safety bound required by the issue).
- `log()` the number of tracks added.
- Result: `{"inserted_count": int, "estimated_total_sec": int, "target_duration_sec":
  int, "capped": bool, "pool_exhausted": bool}`; affected = the new positions.

**Track-selection is intentionally simple** (pool order, not quality-ranked): the
DJ can run `autobuild` afterward to reorder. This keeps the tool small and avoids
duplicating pass-1 candidate scoring.

## Wiring (additive spots)

- `agent_common.py` — add `"autobuild"`, `"fill_to_duration"` to `MUTATION_TOOLS`.
- `agent_tool_specs.py` — add two bare `ToolSpec`s (required: `["rationale"]`).
- `pass2_agent.py` `apply_tool_call` handlers dict — `+2` entries, importing the
  new `agent_tools_structural` module.
- `agent_display.py` `_tool_display_summary` — `+2` cases:
  - autobuild → *"Rebuilt the set: N slots, M refinement passes."*
  - fill_to_duration → *"Filled toward target: added N tracks (~X min), now Y min."*

## Frontend — undo discoverability only

`dashboard/app/(dj)/setbuilder/components/ChatPanelBody.tsx`, in `ToolCard`:

- A `DESTRUCTIVE_TOOL_NAMES = new Set(['autobuild', 'fill_to_duration'])`.
- When `tool.name` is in the set, render a hint line:
  *"Rebuilt your whole set — press ⌘Z (or Undo) to revert."*
- One small CSS class in `setbuilder.module.css`. Keys off `tool.name`; no
  API/type changes (`AppliedToolCall` is generated and already carries `name`).

## Tests (TDD; must hold the 85% backend coverage gate)

**Backend**
- `autobuild` regenerates order honoring locked slots; requires rationale; leaves
  `requests` untouched.
- **Turn atomicity:** an `autobuild` followed by a failing tool in the same turn
  rolls back entirely (proves `commit=False`).
- `fill_to_duration`: stops at target; respects `MAX_FILL_INSERTS` (logged);
  never moves locked slots; errors with no `target_duration_sec`; leaves
  `requests` untouched.
- **Snapshot round-trip identity:** `build_snapshot → restore_snapshot` returns
  the exact prior slot order / targets / curve / pool (acceptance criterion that
  replaces the per-tool undo button). Use a set whose slots reference real pool
  tracks (so the synthetic-`pool:<id>` remap path is meaningful).

**Frontend**
- `ToolCard` renders the undo hint for `autobuild` / `fill_to_duration` and not
  for other tools.

## Acceptance criteria (mapped from #491)

- [x] Task 0 (undo): satisfied by the global undo (#493/#494) + discoverability
  hint; round-trip identity test proves restore fidelity.
- [ ] After `autobuild`, restoring the captured snapshot returns the exact prior
  slot order/targets/curve (round-trip test).
- [ ] `autobuild` honors locked slots; `fill_to_duration` stops at target with a
  bounded, logged insert count.
- [ ] Both owner-scoped, require rationale, in `MUTATION_TOOLS`, render in
  ToolCard, leave `requests` untouched (regression tests).
- [ ] TDD throughout; full backend suite green at the coverage gate.

## Out of scope

- Family 4 cross-surface imports (`import_from_event` / `import_from_tidal`) —
  separate issue under #442.
- Any quality-ranked `fill_to_duration` selection.
- A second / per-tool undo affordance (global undo already covers it).

🤖 Co-authored by Claude Opus 4.8 (1M context). Part of #442 (Family 3, structural).

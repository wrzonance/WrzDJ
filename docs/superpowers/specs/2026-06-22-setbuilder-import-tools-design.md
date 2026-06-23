# Design — connected-service import agent tools (#524, #442 Family 4a)

**Date:** 2026-06-22
**Issue:** #524 (epic #442, Family 4 — cross-surface imports; slice **4a** = connected services)
**Branch:** `feat/issue-524-import-agent-tools`

## Why

Family 4 of epic #442 lets the WrzDJSet chat agent **import a track pool from chat**, not only via the import modal. Slice **4a** covers the three *connected-service* sources; the public-URL importer (`import_from_url`, Spotify/Tidal) is the follow-up slice **4b** (separate spec/PR).

Three tools:
- **`import_from_event`** — a DJ-owned event's non-rejected requests → pool (read-only on `requests`).
- **`import_from_tidal`** — a connected-account Tidal playlist → pool.
- **`import_from_beatport`** — a connected-account Beatport playlist → pool.

## Architecture & boundaries

New module `server/app/services/setbuilder/agent_tools_imports.py` (cohesion: cross-surface imports; keeps `agent_tools_mutations.py` at its 500-line budget). Each tool follows the toolkit contract:

- Signature `_tool_x(db, set_obj, payload) -> tuple[dict[str, Any], set[int]]`.
- Member of `MUTATION_TOOLS` → rationale required; dispatched only through `apply_tool_call`'s closed allowlist.
- Owner-scoped: `set_obj` arrives via `get_owned_set`; events scoped to `created_by_user_id == set_obj.owner_id`; playlists come from the owner's own connected accounts.
- **Never** writes the `requests` table (pinned by a regression test).
- Wraps the existing service path: `pool.candidates_from_*` → `pool.get_or_create_source` → `pool.import_candidates`.

Imports change the **pool, not the timeline**, so affected positions = `set()` (like `add_pairing`); no transition rescoring.

## Supporting change — `import_candidates(commit=...)`

`pool.import_candidates` commits internally (`db.commit()`), like `build_set` did before #491. Add `commit: bool = True`; the agent path calls it with `commit=False` so the chat turn owns the single commit/rollback (atomic across a multi-tool turn). The three REST callers (`api/setbuilder.py` event/tidal/beatport import handlers) keep the default → unchanged.

## Name-or-id resolution (core new logic)

Each tool takes one human-friendly arg and resolves it to a concrete source via a shared helper:

```
_resolve_one(query, items, id_getter, name_getter, *, what) -> item
```

- If `query` is all digits → match where `str(id_getter(item)) == query`.
- Else → case-insensitive substring match on `name_getter(item)`.
- **Exactly 1 match** → return it.
- **0 matches** → `AgentToolError(f"No {what} matched '{query}'. Available: <list of names>")`.
- **>1 match** → `AgentToolError(f"'{query}' matched several {what}s: <list>. Be more specific.")`.

Per-tool wiring of the helper:
- **`import_from_event(event)`** — items = the owner's events (`Event.created_by_user_id == set_obj.owner_id`, ordered most-recent-first); `id_getter = .id`, `name_getter = .name`. Resolve → `event_id` → `pool.candidates_from_event(db, owner, event_id)` (returns `(event, candidates)` or `None`; `None` is treated as not-found and shouldn't happen post-resolution but is guarded).
- **`import_from_tidal(playlist)` / `import_from_beatport(playlist)`** — first connection check (`owner.tidal_access_token` / `owner.beatport_access_token`); if missing → `AgentToolError("Connect your Tidal account first")`. Then `items = tidal.list_user_playlists(db, owner)` / `beatport.list_user_playlists(db, owner)`; resolve → `playlist_id` → `pool.candidates_from_tidal/beatport(db, owner, playlist_id)`.

`owner` = the `User` who owns the set. The tools receive `set_obj`; the resolver obtains the owner from `set_obj.owner` if that relationship exists, else `db.get(User, set_obj.owner_id)` (confirm during planning) — the same identity the REST layer uses as `current_user`, which is guaranteed to equal the set owner because `get_owned_set` already enforced it.

## Error handling

All failure modes raise `AgentToolError` (turn rolls back, agent surfaces a clean message):
- Account not connected (Tidal/Beatport).
- `tidal.TidalFetchError` → `AgentToolError("Couldn't fetch that Tidal playlist")`.
- Beatport returns `[]` on fetch failure (existing semantics) → if the resolved playlist yields no candidates, `AgentToolError`.
- Resolution 0/many (above).

## Wiring & result shape

The usual additive spots:
- `agent_common.py` — `MUTATION_TOOLS` += `import_from_event`, `import_from_tidal`, `import_from_beatport`.
- `agent_tool_specs.py` — 3 `ToolSpec`s. `import_from_event` schema `{event: string, rationale: string}` (required both); tidal/beatport `{playlist: string, rationale: string}`. Descriptions note name-or-id and that they import into the pool.
- `pass2_agent.py` — import the 3 handlers; add to the `handlers` dict.
- `agent_display.py` — 3 `_tool_display_summary` cases.

Result dict: `{"added": int, "deduped": int, "source_label": str, "source_kind": str}`. Display summary, e.g.:
*"Imported 18 tracks from event 'Friday Wedding' into the pool (3 duplicates skipped)."*
*"Imported 24 tracks from Tidal playlist 'Peak Hours' (1 duplicate skipped)."*

## Undo

Pool sources + tracks are part of `build_snapshot`, so imports are captured by the existing global-undo stack (#493/#494) once the tools are in `MUTATION_TOOLS`. Imports are **additive** (they grow the pool; they don't replace the timeline like `autobuild`), so **no destructive-undo hint and no frontend change** — 4a is backend-only.

## Tests (TDD; 85% backend coverage gate)

Mock the external edges (`list_user_playlists`, `candidates_from_tidal/beatport`) so tests don't hit the network; use real DB rows for events + pool.

Per tool:
- resolve by id; resolve by name (substring, case-insensitive)
- 0-match → `AgentToolError` listing options; ambiguous (>1) → `AgentToolError`
- successful import → correct `added`/`deduped`, pool grew, `requests` untouched
- rationale required; membership in `MUTATION_TOOLS`
- display summary text

Tidal/Beatport additionally:
- not-connected → `AgentToolError`
- Tidal `TidalFetchError` → `AgentToolError`; Beatport empty-fetch → `AgentToolError`

Plus:
- `import_candidates(commit=False)` defers persistence (rollback discards; default commits) — mirrors #491's `build_set` test.
- shared `_resolve_one` unit tests (id, name, 0, many).

## Acceptance criteria (mapped from #524)

- [ ] Three tools resolve by id and by name; 0/ambiguous → `AgentToolError` listing options.
- [ ] Successful import reports added/deduped; pool grows; `requests` untouched (regression tests).
- [ ] Owner-scoped, require rationale, in `MUTATION_TOOLS`, render in ToolCard.
- [ ] `import_candidates(commit=False)` keeps the agent turn atomic.
- [ ] TDD; backend suite green at the coverage gate.

## Out of scope

- 4b public-URL import (`import_from_url`, Spotify/Tidal public URLs) — separate spec/PR.
- Any frontend change (additive imports need no destructive-undo hint).
- Spotify *connected-account* import (only public-URL Spotify exists upstream).

🤖 Co-authored by Claude Opus 4.8 (1M context). Part of #442 (Family 4a).

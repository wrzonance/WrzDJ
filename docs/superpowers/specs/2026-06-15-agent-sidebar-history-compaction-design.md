# Agent Sidebar History + Compact Context Design

## Goal

Make the WrzDJSet agent sidebar behave like a durable conversation without
turning every page load or agent turn into a large, expensive LLM prompt.

The sidebar should:

- Own a stable viewport with independent scrolling for the critique card,
  conversation history, and composer.
- Persist conversation history server-side per DJ + set.
- Confirm and expose the actual context model: LLM providers do not remember
  prior turns unless WrzDJ sends the relevant context each call.
- Never render raw JSON tool payloads in the chat. Agent returns should describe
  which tracks were added, removed, reordered, swapped, or otherwise adjusted.
- Bound the prompt sent to the LLM by using backend-managed compact context
  rather than sending the full transcript every time.

## Current Behavior

Frontend:

- `dashboard/app/(dj)/setbuilder/components/ChatSidebar.tsx` stores chat entries
  in React state only.
- It sends `history` as the last 30 text turns on each `api.chatWithSetAgent`
  call.
- It renders raw JSON via `JSON.stringify(tool.args)` inside `ToolCard`.
- `.chatScroll` exists, but the sidebar's practical scroll behavior depends on
  the grid/flex containment around the full sidebar.

Backend:

- `POST /api/setbuilder/sets/{set_id}/agent/chat` accepts client-provided
  history.
- `pass2_agent.chat_with_agent()` builds a fresh `ChatRequest` on each turn:
  current set JSON, supplied history, and the new user message.
- `Gateway.dispatch()` is provider-agnostic and stateless. It logs token counts,
  not prompt or completion content.

Open issues reviewed:

- #402 Mobile chat view: nearby future mobile surface, but not this desktop
  persistence/context change.
- #397 Locked slots UI refinements: nearby agent messaging around skipped locked
  slots.
- #409 Taste-profile training: future agent context input.

No open issue directly covers durable agent sidebar history, bounded context, or
raw JSON removal.

## Design Decisions

### 1. Store Full Transcript Separately From Model Context

WrzDJ owns the full transcript for display. The LLM context is a derived,
bounded projection of that transcript.

The sidebar loads full history through a normal WrzDJ API call. Loading history
must not call an LLM provider.

### 2. Server Is the Source of Agent Context

The browser no longer sends authoritative history to `/agent/chat`.

On each user turn, the backend:

1. Loads the current set snapshot.
2. Loads the persisted agent session for `(set_id, user_id)`.
3. Builds bounded model context from:
   - current set JSON
   - compact summary of older conversation and decisions
   - latest recent turns
   - current user message
4. Dispatches exactly one normal agent LLM call for the user turn.
5. Applies validated tool calls.
6. Generates deterministic human-readable action summaries.
7. Persists the user turn and assistant turn.
8. Compacts only if configured thresholds are crossed.

### 3. Compact Context Is Backend-Managed

Do not rely on provider-specific state APIs such as OpenAI Conversations or
`previous_response_id` for the product behavior. WrzDJ's LLM gateway supports
multiple providers and should keep a provider-agnostic context contract.

Prompt caching may help cost/latency for some providers, but it is not the
primary solution: caching does not shrink context and does not prevent
context-window overflow. WrzDJ must explicitly bound what it sends.

### 4. Deterministic Summaries First

Tool-call summaries should be generated from validated tool results and current
track metadata, not by asking the LLM to summarize its own mutations.

Examples:

- `swap_slots`: "Swapped slot 1 Track A with slot 2 Track B."
- `reorder_slot`: "Moved Track A from slot 4 to slot 7."
- `remove_slot`: "Removed Track A from slot 5."
- `insert_from_pool`: "Added Track A at slot 8."
- `search_and_insert`: "Added Track A from the pool search at slot 8."
- `bump_energy`: "Raised target energy by 0.5 across 12 slots."
- `set_peak_at`: "Set slot 10 Track A as the energy peak at 9.5."
- `add_slow_window`: "Added slow window First Dance from 0:35 to 3:20."
- `analyze_transition`: "Analyzed transition into slot 6: 88."
- `critique_set`: "Recomputed critique context."

The raw tool payload remains available in structured backend data where useful
for tests/debugging, but it is not rendered in the chat bubble.

### 5. Compaction Should Be Rare and Predictable

The first implementation should avoid an LLM compaction call during ordinary
page load and ordinary short conversations.

Compaction runs after a turn only when thresholds are crossed, for example:

- persisted turns since last compaction exceed a configured count, or
- estimated prompt context exceeds a configured character/token budget.

The compact context should include:

- stable user preferences stated during the conversation
- decisions already made by the agent
- mutation history relevant to future turns
- unresolved user requests or constraints
- a short note that the current set JSON is authoritative for actual timeline
  state

For tool-heavy history, deterministic compaction is enough. If natural-language
conversation grows beyond the budget, a low-cost LLM summarization pass may be
used behind the threshold, but it must be explicit and counted separately from
normal agent turns.

## Proposed Backend Shape

### Models

Add a small owner-scoped session model, keyed by DJ + set.

`SetAgentSession`

- `id`
- `set_id`
- `user_id`
- `context_summary`
- `summary_turn_cursor`
- `created_at`
- `updated_at`

`SetAgentMessage`

- `id`
- `session_id`
- `role`: `user | assistant`
- `content`
- `display_summary`
- `tool_calls_json`
- `affected_transition_scores_json`
- `created_at`

Notes:

- The transcript is not public and remains owner-scoped through the set access
  check.
- The current product uses owner-only set access. Future collaborator behavior
  from #408 should extend the keying decision if editors get agent access.

### API

`GET /api/setbuilder/sets/{set_id}/agent/history`

- Authenticated DJ only.
- Returns the persisted transcript and compact-summary metadata needed for UI
  transparency.
- Does not call the LLM.

`POST /api/setbuilder/sets/{set_id}/agent/chat`

- Request body becomes primarily `{ message: string }`.
- Backend loads context itself.
- Response includes the newly persisted assistant turn plus slots and affected
  transition scores.

Optional:

`DELETE /api/setbuilder/sets/{set_id}/agent/history`

- Clear transcript and compact summary for this DJ + set.
- Useful, but can be deferred if first-pass scope needs to stay smaller.

### Prompt Builder

Replace client-supplied history with backend context assembly:

1. `Message(role="user", content=_set_context(db, set_obj))`
2. If present, `Message(role="assistant", content=context_summary)` or a
   clearly labeled user/context message.
3. Recent persisted turns, bounded by count and estimated size.
4. Current `Message(role="user", content=message)`.

The system prompt should explicitly say the set JSON is authoritative and the
conversation summary is historical context only.

## Proposed Frontend Shape

`ChatSidebar`

- Loads history when mounted/opened for the set.
- Renders the full persisted transcript in the sidebar scroll region.
- Sends only `{ message }` for new turns.
- Appends optimistic user turn while pending.
- Reconciles with server-persisted assistant turn after response.
- Uses a dedicated scrollable history viewport with stable `min-height: 0`,
  fixed composer, and no page-level scroll bleed.

UI text should include concise context transparency, for example in a small
status/detail line rather than a tutorial block:

- "Uses compact context + recent turns"
- "Full history saved for this set"

Do not render raw JSON. Render deterministic summaries and rationale as readable
conversation content.

## Testing Plan

Backend:

- API test: history loads without calling `Gateway.dispatch`.
- API test: chat persists user + assistant turns.
- Service test: `chat_with_agent` builds context from persisted summary + recent
  turns, not client payload history.
- Service test: compaction threshold does not run below budget and does run above
  budget.
- Service test: deterministic summaries for swap, reorder, remove, insert, and
  analyze tools.
- API ownership test: another DJ cannot read or mutate a set's agent history.
- Migration drift check after model changes.

Frontend:

- `ChatSidebar` loads and renders persisted history.
- Sending a message posts only `{ message }`, not the full `history` array.
- Tool returns render human-readable summaries, not JSON strings.
- Sidebar history region scrolls independently and composer remains visible.
- Mutation response still triggers `onMutationApplied`.

Verification:

- Backend CI subset for setbuilder agent tests.
- Frontend ChatSidebar test suite.
- Full repo checks before PR as listed in `AGENTS.md`.

## Open Implementation Notes

- Use a conservative first-pass context budget. Exact token counting is
  provider-specific, so begin with a character estimate and keep constants
  backend-local.
- Do not store provider conversation IDs in this first pass; that would couple
  WrzDJSet behavior to specific providers and complicate connector switching.
- LLM compaction, if enabled later, should go through `Gateway.dispatch` with
  `purpose="set_builder"` or a more specific `purpose` if added.
- Because `Gateway.dispatch` logs counts only, compaction calls will be visible
  in telemetry without leaking transcript content.


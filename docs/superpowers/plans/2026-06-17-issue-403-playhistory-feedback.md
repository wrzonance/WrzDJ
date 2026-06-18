# Play-History Feedback Loop (#403) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive-on-read a planned-vs-actual playback report for a set attached to an event, and
let the DJ feed real consecutive plays back into `SetPairing.use_count` via an explicit action.

**Architecture:** A new read-only service `services/setbuilder/playhistory_feedback.py` matches the
set's ordered slots against the event's `play_history` using the ladder
`spotify_track_id` exact → `dedupe_sig` exact → fuzzy artist+title (reusing `track_normalizer`,
`pool.dedupe_signature`, and the `now_playing` weighting). Two owner-scoped endpoints expose the
report (GET) and the explicit pairing bump (POST). A `PlaybackReportOverlay` (PairingsOverlay mold)
renders it, shown only when the set has an `event_id`.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), Next.js/React 19 + vanilla CSS (frontend),
pytest + vitest.

## Global Constraints

- No schema migration; no outcome persistence; no ISRC enrichment (`play_history` has NO ISRC).
- Reuse matching/normalization utilities — do not reinvent.
- SECURITY INVARIANT: read-only on `play_history` AND `requests`; the ONLY write is
  `SetPairing.use_count` via the explicit apply action. Owner-scoped via `get_owned_set`.
- 400 if the set has no event attached.
- Backend coverage gate ≥85%. Frontend: vanilla CSS + inline styles, NO Tailwind.
- Conventional Commits; commit body trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Feedback service — matching + report + apply

**Files:**
- Create: `server/app/services/setbuilder/playhistory_feedback.py`
- Test: `server/tests/test_setbuilder_playhistory_feedback.py`

**Interfaces:**
- Produces:
  - `build_feedback_report(db: Session, set_obj: Set) -> FeedbackReport`
  - `apply_outcomes_to_pairings(db: Session, set_obj: Set, report: FeedbackReport) -> int`
  - dataclasses `SlotFeedback(slot_id, position, track_id, title, artist, outcome, play_order,
    played_at, deck)`, `UnplannedPlay(play_order, title, artist, played_at, deck)`,
    `FeedbackReport(event_id, slots, unplanned, summary)` where `summary` is
    `ReportSummary(total_planned, total_played, played, skipped, out_of_order, unplanned)`.
  - outcome strings: `"played" | "skipped" | "out_of_order" | "substituted"`.

Matching: planned = slots with a resolvable pool track (by `track_id` or `pool:{id}`), in position
order. Greedy per slot over unconsumed plays; tier priority spotify(0)→dedupe(1)→fuzzy(2),
fuzzy combined = title·0.7 + artist·0.3, threshold 0.8. out_of_order = matched slot whose play_order
rank ≠ position rank among matched slots. unplanned = plays consumed by no slot (outcome
`substituted`). apply bumps a pairing's `use_count` once when its `(from,into)` track_ids appear as
matched plays at adjacent `play_order` (b.play_order == a.play_order + 1); returns distinct count.

- [ ] Write failing service tests (each rung, skipped, out_of_order, substituted, apply consecutive,
  apply ignores non-consecutive, requests-untouched regression).
- [ ] Run → FAIL (module missing).
- [ ] Implement `playhistory_feedback.py`.
- [ ] Run → PASS. Commit.

### Task 2: Schemas + endpoints + openapi

**Files:**
- Modify: `server/app/schemas/setbuilder.py` (append `SlotOutcome`, `PlaybackSlotOutcomeOut`,
  `UnplannedPlayOut`, `PlaybackReportSummary`, `PlayHistoryFeedbackOut`, `ApplyPairingFeedbackOut`)
- Modify: `server/app/api/setbuilder.py` (import `playhistory_feedback`; add
  `GET /sets/{set_id}/playback-report` + `POST /sets/{set_id}/playback-report/apply-pairings`)
- Modify: `server/openapi.json` (regenerate)
- Test: `server/tests/test_setbuilder_playhistory_feedback.py` (API: 200 shape, 400 no event,
  404 unowned, apply returns bumped + pairings)

**Interfaces:**
- Consumes Task 1 service.
- Produces `PlayHistoryFeedbackOut{event_id, slots[], unplanned[], summary}` and
  `ApplyPairingFeedbackOut{bumped, pairings: PairingsState}`.

- [ ] Write failing API tests.
- [ ] Implement schemas + endpoints; regenerate openapi.
- [ ] Run backend CI green. Commit.

### Task 3: Frontend overlay + wiring

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/PlaybackReportOverlay.tsx`
- Create: `dashboard/app/(dj)/setbuilder/components/__tests__/PlaybackReportOverlay.test.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` (button shown only when `set.event_id`)
- Modify: `dashboard/app/(dj)/setbuilder/setbuilder.module.css` (overlay styles, reuse pairings mold)
- Modify: `dashboard/lib/api.ts` (`getPlaybackReport`, `applyPlaybackPairings`)
- Modify: `dashboard/lib/api-types.ts` (type aliases) + regenerate `api-types.generated.ts`

- [ ] Regenerate generated types from openapi.
- [ ] Write failing vitest (renders 4 outcome states + unplanned; Apply calls API).
- [ ] Implement overlay + api + page wiring + css.
- [ ] Run frontend CI green. Commit.
